# -*- coding: utf-8 -*-
import asyncio
from asyncio import AbstractEventLoop, Future
from subprocess import Popen
from typing import Awaitable, Callable, Dict, List, Optional, Union, Any
from async_timeout import timeout as aiotimeout
import attr
from pyee import EventEmitter

from .connection import Client, TargetSession
from .errors import BrowserError
from .page import Page
from .helper import Helper
from .util import ensure_loop

__all__ = ["Chrome", "BrowserContext", "Target"]


@attr.dataclass(slots=True)
class ChromeEvents(object):
    TargetCreated: str = attr.ib(default="targetcreated")
    TargetDestroyed: str = attr.ib(default="targetdestroyed")
    TargetChanged: str = attr.ib(default="targetchanged")
    Disconnected: str = attr.ib(default="disconnected")


class Chrome(EventEmitter):
    Events: ChromeEvents = ChromeEvents()

    def __init__(
        self,
        connection: Union[Client, TargetSession],
        contextIds: List[str],
        ignoreHTTPSErrors: bool,
        defaultViewport: Optional[Dict[str, int]] = None,
        process: Optional[Popen] = None,
        closeCallback: Optional[Callable[[], Awaitable[None]]] = None,
        targetInfo: Optional[Dict] = None,
        loop: Optional[AbstractEventLoop] = None,
    ) -> None:
        super().__init__(loop=ensure_loop(loop))
        self.process: Optional[Popen] = process
        self.ignoreHTTPSErrors: bool = ignoreHTTPSErrors
        self._defaultViewport: Optional[Dict[str, int]] = defaultViewport
        self._screenshotTaskQueue: List = []
        self._connection: Union[Client, TargetSession] = connection
        self._targetInfo: Optional[Dict] = targetInfo
        browserContextId = None
        if self._targetInfo is not None:
            browserContextId = targetInfo.get("browserContextId", None)
        self._defaultContext: BrowserContext = BrowserContext(
            connection, self, browserContextId
        )
        self._contexts: Dict[str, BrowserContext] = dict()
        self._page: Optional[Page] = None
        for contextId in contextIds:
            self._contexts[contextId] = BrowserContext(connection, self, contextId, self._loop)

        def _dummy_callback() -> Awaitable[None]:
            fut = self._loop.create_future()
            fut.set_result(None)
            self.emit(Chrome.Events.Disconnected, None)
            return fut

        if closeCallback:
            self._closeCallback = closeCallback
        else:
            self._closeCallback = _dummy_callback

        self._targets: Dict[str, Target] = dict()
        self._connection.on(self._connection.Events.Disconnected, self._on_close)
        self._connection.on("Target.targetCreated", self._targetCreated)
        self._connection.on("Target.targetDestroyed", self._targetDestroyed)
        self._connection.on("Target.targetInfoChanged", self.targetInfoChanged)

    @staticmethod
    async def create(
        connection: Client,
        contextIds: List[str],
        ignoreHTTPSErrors: bool,
        defaultViewport: Optional[Dict[str, int]] = None,
        process: Optional[Popen] = None,
        closeCallback: Callable[[], Awaitable[None]] = None,
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
            loop
        )
        await connection.send("Target.setDiscoverTargets", {"discover": True})
        return browser

    async def page(self) -> Page:
        """The default page for the target connected to"""
        if self._page is None:
            targetId = self._targetInfo["targetId"]
            if targetId in self._targets:
                target = self._targets[targetId]
            else:
                target = Target(self._targetInfo, self._defaultContext, self)
                self._targets[targetId] = target
            await target._initializedPromise
            page = await Page.create(
                self._connection,
                target,
                self._defaultViewport,
                self.ignoreHTTPSErrors,
                self._screenshotTaskQueue,
                self._loop
            )
            target._page = page
            self._page = page
        return self._page

    def targets(self) -> List["Target"]:
        """Get all targets of this browser."""
        return [target for target in self._targets.values() if target._isInitialized]

    async def waitForTarget(
        self,
        predicate: Callable[["Target"], bool],
        timeout: Optional[Union[int, float]] = 30,
    ) -> Optional["Target"]:
        existingTarget = None
        for target in self._targets.values():
            if target._isInitialized and predicate(target):
                existingTarget = target
                break
        if existingTarget is not None:
            return existingTarget
        existingTargetPromise: Future = self._loop.create_future()

        def check(atarget: "Target") -> None:
            if predicate(atarget) and not existingTargetPromise.done():
                existingTargetPromise.set_result(atarget)

        listeners = [
            Helper.addEventListener(self, Chrome.Events.TargetCreated, check),
            Helper.addEventListener(self, Chrome.Events.TargetChanged, check),
        ]

        existingTargetPromise.add_done_callback(
            lambda future: Helper.removeEventListeners(listeners)
        )

        if timeout is None:
            return await existingTargetPromise

        try:
            async with aiotimeout(timeout, loop=self._loop):
                existingTarget = await existingTargetPromise
        except asyncio.TimeoutError:
            pass

        return existingTarget

    async def newPage(self) -> Page:
        return await self._defaultContext.newPage()

    async def pages(self) -> List[Page]:
        """Get all pages of this browser."""
        pages = []
        for target in self.targets():
            page = await target.page()
            if page:
                pages.append(page)
        return pages

    async def version(self) -> str:
        version = await self._getVersion()
        return version["product"]

    async def userAgent(self) -> str:
        version = await self._getVersion()
        return version.get("userAgent", "")

    async def close(self) -> None:
        await self._closeCallback()  # Launcher.killChrome()
        await self.disconnect()

    async def disconnect(self) -> None:
        await self._connection.dispose()

    async def createIncognitoBrowserContext(self) -> "BrowserContext":
        nc = await self._connection.send("Target.createBrowserContext")
        contextId = nc.get("browserContextId")
        context = BrowserContext(self._connection, self, contextId)
        self._contexts[contextId] = context
        return context

    def browserContexts(self) -> List["BrowserContext"]:
        contexts = [self._defaultContext]
        for cntx in self._contexts.values():
            contexts.append(cntx)
        return contexts

    @property
    def wsEndpoint(self) -> str:
        """Retrun websocket end point url."""
        return self._connection.url

    def _on_close(self) -> None:
        self.emit(Chrome.Events.Disconnected, None)

    async def _disposeContext(self, contextId: Optional[str]) -> None:
        if contextId is not None:
            await self._connection.send(
                "Target.disposeBrowserContext", dict(browserContextId=contextId)
            )
            del self._contexts[contextId]

    async def _targetCreated(self, event: dict) -> None:
        tinfo = event["targetInfo"]
        browserContextId = tinfo.get("browserContextId")
        if browserContextId is not None and browserContextId in self._contexts:
            context = self._contexts.get(browserContextId)
        else:
            context = self._defaultContext
        targetId = tinfo["targetId"]
        target = Target(tinfo, context, self)
        if targetId in self._targets:
            raise BrowserError("target should not exist before create.")
        self._targets[targetId] = target
        if await target._initializedPromise:
            self.emit(self.Events.TargetCreated, target)
            context.emit(self.Events.TargetCreated, target)

    async def _targetDestroyed(self, event: dict) -> None:
        target = self._targets[event["targetId"]]
        target._initializedCallback(False)
        del self._targets[event["targetId"]]
        target._closedCallback()
        if await target._initializedPromise:
            self.emit(self.Events.TargetDestroyed, target)
            target.browserContext.emit(Chrome.Events.TargetDestroyed, target)

    async def targetInfoChanged(self, event: dict) -> None:
        target = self._targets.get(event["targetInfo"]["targetId"])
        if not target:
            raise BrowserError("target should exist before targetInfoChanged")
        previousURL = target.url
        target.targetInfoChanged(event["targetInfo"])
        if previousURL != target.url:
            self.emit(Chrome.Events.TargetChanged, target)
            target.browserContext.emit(Chrome.Events.TargetChanged, target)

    async def createPageInContext(self, contextId: Optional[str]) -> Page:
        args = dict(url="about:blank")
        if contextId is not None:
            args["browserContextId"] = contextId
        createdTarget = await self._connection.send("Target.createTarget", args)
        if asyncio.isfuture(createdTarget):
            createdTarget = await createdTarget
        target = self._targets.get(createdTarget["targetId"])
        if not await target._initializedPromise:
            raise BrowserError("Failed to create target for new page.")
        page = await target.page()
        return page

    def _getVersion(self) -> Awaitable[Dict[str, str]]:
        return self._connection.send("Browser.getVersion")


@attr.dataclass(slots=True)
class BrowserContextEvents(object):
    TargetCreated: str = attr.ib(default="targetcreated")
    TargetDestroyed: str = attr.ib(default="targetdestroyed")
    TargetChanged: str = attr.ib(default="targetchanged")


class BrowserContext(EventEmitter):
    Events: BrowserContextEvents = BrowserContextEvents()

    def __init__(
        self,
        client: Union[Client, TargetSession],
        browser: Chrome,
        contextId: Optional[str] = None,
        loop: Optional[AbstractEventLoop] = None,
    ) -> None:
        super().__init__(loop=ensure_loop(loop))
        self.client: Union[Client, TargetSession] = client
        self._browser = browser
        self._id = contextId

    def targets(self) -> List["Target"]:
        targets = []
        for t in self._browser.targets():
            if t.browserContext is self:
                targets.append(t)
        return targets

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

    def isIncognito(self) -> bool:
        return self._id is not None

    def newPage(self) -> Awaitable[Page]:
        cntx = self._id
        if self is self._browser._defaultContext:
            cntx = None
        return self._browser.createPageInContext(cntx)

    def browser(self) -> Chrome:
        return self._browser

    async def close(self) -> None:
        cntx = self._id
        if self is self._browser._defaultContext:
            cntx = None
        if cntx is not None:
            return
        await self._browser._disposeContext(cntx)


class Target(object):
    """Browser's target class."""

    def __init__(
        self,
        targetInfo: Dict[str, str],
        browserContext: BrowserContext,
        browser: Chrome,
        loop: Optional[AbstractEventLoop] = None,
    ) -> None:
        self._browser: Chrome = browser
        self._browserContext: BrowserContext = browserContext
        self._targetInfo: Dict[str, str] = targetInfo
        self._targetId = targetInfo["targetId"]
        self._page: Optional[Page] = None
        self._loop = ensure_loop(loop)

        self._isClosedPromise: Future = self._loop.create_future()
        self._initializedPromise: Future = self._loop.create_future()
        self._isInitialized = (
            self._targetInfo["type"] != "page" or self._targetInfo["url"] != ""
        )
        if self._isInitialized:
            self._initializedCallback(True)

    def _initializedCallback(self, bl: bool) -> None:
        if not self._initializedPromise.done():
            self._initializedPromise.set_result(bl)

    def _closedCallback(self) -> None:
        self._isClosedPromise.set_result(None)

    async def createTargetSession(self) -> TargetSession:
        """Create a Chrome Devtools Protocol session attached to the target."""
        return await self._browser._connection.createTargetSession(self._targetId)

    async def page(self) -> Optional[Page]:
        """Get page of this target."""
        is_page = (
            self._targetInfo["type"] == "page"
            or self._targetInfo["type"] == "background_page"
        )
        if is_page and self._page is None:
            client = await self._browser._connection.createTargetSession(self._targetId)
            new_page = await Page.create(
                client,
                self,
                self._browser._defaultViewport,
                self._browser.ignoreHTTPSErrors,
                self._browser._screenshotTaskQueue,
                self._loop
            )
            self._page = new_page
            return new_page
        return self._page

    @property
    def opener(self) -> Optional["Target"]:
        openerId = self._targetInfo.get("openerId")
        if openerId is not None:
            return self.browser._targets.get(openerId)
        return openerId

    @property
    def browser(self) -> "Chrome":
        return self._browserContext.browser()

    @property
    def browserContext(self) -> "BrowserContext":
        return self._browserContext

    @property
    def url(self) -> str:
        """Get url of this target."""
        return self._targetInfo["url"]

    @property
    def type(self) -> str:
        """Get type of this target."""
        _type: str = self._targetInfo["type"]
        if (
            _type == "page"
            or _type == "service_worker"
            or _type == "page"
            or _type == "background_page"
            or _type == "browser"
        ):
            return _type
        return "other"

    def targetInfoChanged(self, targetInfo: dict) -> None:
        self._targetInfo = targetInfo

        if not self._isInitialized and (
            self._targetInfo["type"] != "page" or self._targetInfo["url"] != ""
        ):
            self._isInitialized = True
            self._initializedCallback(True)
            return
