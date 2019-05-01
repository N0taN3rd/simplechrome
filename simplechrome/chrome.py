from asyncio import AbstractEventLoop, Future
from inspect import isawaitable
from subprocess import Popen
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from pyee2 import EventEmitterS

from ._typings import SlotsT
from .connection import ClientType
from .errors import BrowserError
from .events import Events
from .helper import Helper
from .page import Page
from .target import Target

__all__ = ["Chrome", "BrowserContext"]


class Chrome(EventEmitterS):
    __slots__: SlotsT = [
        "_closeCallback",
        "_connection",
        "_contexts",
        "_defaultContext",
        "_defaultViewport",
        "_ignoreHTTPSErrors",
        "_page",
        "_process",
        "_screenshotTaskQueue",
        "_targetInfo",
        "_targets",
    ]

    @staticmethod
    async def create(
        connection: ClientType,
        contextIds: List[str],
        ignoreHTTPSErrors: bool,
        defaultViewport: Optional[Dict[str, int]] = None,
        process: Optional[Popen] = None,
        closeCallback: Optional[Callable[[], Any]] = None,
        targetInfo: Optional[Dict] = None,
        loop: Optional[AbstractEventLoop] = None,
    ) -> "Chrome":
        browser = Chrome(
            connection,
            contextIds,
            ignoreHTTPSErrors,
            defaultViewport,
            process,
            closeCallback,
            targetInfo,
            loop,
        )
        await connection.send("Target.setDiscoverTargets", {"discover": True})
        return browser

    def __init__(
        self,
        connection: ClientType,
        contextIds: List[str],
        ignoreHTTPSErrors: bool,
        defaultViewport: Optional[Dict[str, int]] = None,
        process: Optional[Popen] = None,
        closeCallback: Optional[Callable[[], Any]] = None,
        targetInfo: Optional[Dict] = None,
        loop: Optional[AbstractEventLoop] = None,
    ) -> None:
        super().__init__(loop=Helper.ensure_loop(loop))
        self._ignoreHTTPSErrors: bool = ignoreHTTPSErrors
        self._process: Optional[Popen] = process
        self._defaultViewport: Optional[Dict[str, int]] = defaultViewport
        self._screenshotTaskQueue: List = []
        self._connection: ClientType = connection
        self._targetInfo: Optional[Dict] = targetInfo
        self._page: Optional[Page] = None
        # self.on("error", lambda e: print("Chrome error", e))

        browserContextId = None
        if self._targetInfo is not None:
            browserContextId = self._targetInfo.get("browserContextId", None)
        self._defaultContext: BrowserContext = BrowserContext(
            connection, self, browserContextId
        )

        self._contexts: Dict[str, BrowserContext] = {}
        for contextId in contextIds:
            self._contexts[contextId] = BrowserContext(
                connection, self, contextId, self._loop
            )

        self._closeCallback: Callable[
            ..., Any
        ] = closeCallback if closeCallback is not None else Helper.noop

        self._targets: Dict[str, Target] = dict()
        self._connection.on(self._connection.Events.Disconnected, self._on_close)
        self._connection.on("Target.targetCreated", self._targetCreated)
        self._connection.on("Target.targetDestroyed", self._targetDestroyed)
        self._connection.on("Target.targetInfoChanged", self._targetInfoChanged)

    @property
    def process(self) -> Optional[Popen]:
        return self._process

    @property
    def wsEndpoint(self) -> str:
        """Return websocket end point url."""
        return self._connection.ws_url

    @property
    def defaultBrowserContext(self) -> "BrowserContext":
        return self._defaultContext

    def browserContexts(self) -> List["BrowserContext"]:
        contexts = [self._defaultContext]
        for cntx in self._contexts.values():
            contexts.append(cntx)
        return contexts

    def targets(self) -> List[Target]:
        """Get all targets of this browser."""
        return [target for target in self._targets.values() if target.initialized]

    def target(self, target_id: str) -> Optional[Target]:
        return self._targets.get(target_id)

    async def createIncognitoBrowserContext(self) -> "BrowserContext":
        nc = await self._connection.send("Target.createBrowserContext")
        contextId = nc.get("browserContextId")
        context = BrowserContext(self._connection, self, contextId)
        self._contexts[contextId] = context
        return context

    async def newPage(self) -> Page:
        return await self._defaultContext.newPage()

    async def waitForTarget(
        self,
        predicate: Callable[[Target], bool],
        timeout: Optional[Union[int, float]] = 30,
    ) -> Optional[Target]:
        existingTarget = None
        for target in self._targets.values():
            if target.initialized and predicate(target):
                existingTarget = target
                break
        if existingTarget is not None:
            return existingTarget
        existingTargetPromise: Future = self._loop.create_future()

        def check(atarget: "Target") -> None:
            if predicate(atarget) and not existingTargetPromise.done():
                existingTargetPromise.set_result(atarget)

        listeners = [
            Helper.addEventListener(self, Events.Chrome.TargetCreated, check),
            Helper.addEventListener(self, Events.Chrome.TargetChanged, check),
        ]

        existingTargetPromise.add_done_callback(
            lambda future: Helper.removeEventListeners(listeners)
        )

        if timeout is None:
            return await existingTargetPromise

        return await Helper.waitWithTimeout(
            existingTargetPromise, timeout, taskName="target", loop=self._loop
        )

    async def pages(self) -> List[Page]:
        """Get all pages of this browser."""
        pages = []
        for target in self.targets():
            page = await target.page()
            if page:
                pages.append(page)
        return pages

    async def createPageInContext(self, contextId: Optional[str]) -> Page:
        args = dict(url="about:blank")
        if contextId is not None:
            args["browserContextId"] = contextId
        createdTarget = await self._connection.send("Target.createTarget", args)
        target = self._targets.get(createdTarget["targetId"])
        if not await target._initializedPromise:
            raise BrowserError("Failed to create target for new page.")
        page = await target.page()
        return page

    async def version(self) -> str:
        version = await self._getVersion()
        return version["product"]

    async def userAgent(self) -> str:
        version = await self._getVersion()
        return version.get("userAgent", "")

    async def close(self) -> None:
        results = self._closeCallback()
        if results and isawaitable(results):
            await results
        await self.disconnect()

    async def disconnect(self) -> None:
        await self._connection.dispose()

    async def _disposeContext(self, contextId: Optional[str]) -> None:
        params = dict()
        if contextId is not None:
            params["browserContextId"] = contextId
        await self._connection.send("Target.disposeBrowserContext", params)
        self._contexts.pop(contextId, None)

    async def _targetCreated(self, event: Dict) -> None:
        tinfo = event["targetInfo"]
        browserContextId = tinfo.get("browserContextId")
        if browserContextId is not None and browserContextId in self._contexts:
            context = self._contexts.get(browserContextId)
        else:
            context = self._defaultContext
        targetId = tinfo["targetId"]
        target = Target(
            tinfo,
            context,
            lambda: self._connection.create_session(targetId),
            self._ignoreHTTPSErrors,
            self._defaultViewport,
            self._screenshotTaskQueue,
            self._loop,
        )
        if targetId in self._targets:
            raise BrowserError("target should not exist before create.")
        self._targets[targetId] = target
        if await target._initializedPromise:
            self.emit(Events.Chrome.TargetCreated, target)
            context.emit(Events.BrowserContext.TargetCreated, target)

    async def _targetDestroyed(self, event: Dict) -> None:
        target = self._targets[event["targetId"]]
        target._initializedCallback(False)
        self._targets.pop(event["targetId"], None)
        target._closedCallback()
        if await target._initializedPromise:
            self.emit(Events.Chrome.TargetDestroyed, target)
            target.browserContext.emit(Events.BrowserContext.TargetDestroyed, target)

    async def _targetInfoChanged(self, event: Dict) -> None:
        target = self._targets.get(event["targetInfo"]["targetId"])
        if not target:
            raise BrowserError("target should exist before targetInfoChanged")
        previousURL = target.url
        wasInitialized = target.initialized
        target._targetInfoChanged(event["targetInfo"])
        if wasInitialized and previousURL != target.url:
            self.emit(Events.Chrome.TargetChanged, target)
            target.browserContext.emit(Events.BrowserContext.TargetChanged, target)

    def _getVersion(self) -> Awaitable[Dict[str, str]]:
        return self._connection.send("Browser.getVersion")

    def _on_close(self) -> None:
        self.emit(Events.Chrome.Disconnected, None)

    def __str__(self) -> str:
        return f"Chrome(targetInfo={self._targetInfo})"

    def __repr__(self) -> str:
        return self.__str__()


class BrowserContext(EventEmitterS):

    __slots__: SlotsT = ["_browser", "_id", "client"]

    def __init__(
        self,
        client: ClientType,
        browser: Chrome,
        contextId: Optional[str] = None,
        loop: Optional[AbstractEventLoop] = None,
    ) -> None:
        super().__init__(loop=Helper.ensure_loop(loop))
        self.client: ClientType = client
        self._browser = browser
        self._id = contextId

    def targets(self) -> List["Target"]:
        targets = []
        for t in self._browser.targets():
            if t.browserContext is self:
                targets.append(t)
        return targets

    def isIncognito(self) -> bool:
        return self._id is None

    def newPage(self) -> Awaitable[Page]:
        cntx = self._id
        if self is self._browser._defaultContext:
            cntx = None
        return self._browser.createPageInContext(cntx)

    def browser(self) -> Chrome:
        return self._browser

    def waitForTarget(
        self,
        predicate: Callable[["Target"], bool],
        timeout: Optional[Union[int, float]],
    ) -> Awaitable[Optional["Target"]]:
        return self._browser.waitForTarget(
            lambda target: target.browserContext is self and predicate(target), timeout
        )

    async def pages(self) -> List[Page]:
        pages = []
        for target in self.targets():
            if target.type == "page":
                page = await target.page()
                if page is not None:
                    pages.append(page)
        return pages

    async def clearPermissionOverrides(self) -> None:
        opts = dict()
        if self._id is not None:
            opts["browserContextId"] = self._id
        await self.client.send("Browser.resetPermissions", opts)

    async def overridePermissions(self, origin: str, permissions: List[str]) -> None:
        webPermissionToProtocol: Dict[str, str] = {
            "geolocation": "geolocation",
            "midi": "midi",
            "notifications": "notifications",
            "push": "push",
            "camera": "videoCapture",
            "microphone": "audioCapture",
            "background-sync": "backgroundSync",
            "ambient-light-sensor": "sensors",
            "accelerometer": "sensors",
            "gyroscope": "sensors",
            "magnetometer": "sensors",
            "accessibility-events": "accessibilityEvents",
            "clipboard-read": "clipboardRead",
            "clipboard-write": "clipboardWrite",
            "payment-handler": "paymentHandler",
            # chrome-specific permissions we have.
            "midi-sysex": "midiSysex",
        }
        protocolPermissions = []
        for permission in permissions:
            protocolPermission = webPermissionToProtocol.get(permission)
            if protocolPermission is None:
                raise Exception(f"Unknown permission {permission}")
            protocolPermissions.append(protocolPermission)
        opts = dict(origin=origin, permissions=protocolPermissions)
        if self._id is not None:
            opts["browserContextId"] = self._id
        await self.client.send("Browser.resetPermissions", opts)

    async def close(self) -> None:
        if self._id is not None:
            await self._browser._disposeContext(self._id)

    def __str__(self) -> str:
        return f"BrowserContext(id={self._id})"

    def __repr__(self) -> str:
        return self.__str__()
