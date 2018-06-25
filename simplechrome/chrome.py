import asyncio
from subprocess import Popen
from types import SimpleNamespace  # type: ignore
from typing import Awaitable, Callable, Dict, List, Optional

from pyee import EventEmitter

from .connection import Connection, CDPSession
from .errors import BrowserError
from .page import Page

__all__ = ["Chrome", "BrowserContext", "Target"]


class Chrome(EventEmitter):
    Events: SimpleNamespace = SimpleNamespace(
        TargetCreated="targetcreated",
        TargetDestroyed="targetdestroyed",
        TargetChanged="targetchanged",
        Disconnected="disconnected",
    )

    def __init__(
        self,
        connection: Connection,
        contextIds: List[str],
        ignoreHTTPSErrors: bool,
        setDefaultViewport: bool,
        process: Optional[Popen] = None,
        closeCallback: Callable[[], Awaitable[None]] = None,
    ) -> None:
        super().__init__()
        self.process: Optional[Popen] = process
        self.ignoreHTTPSErrors: bool = ignoreHTTPSErrors
        self._setDefaultViewport: bool = setDefaultViewport
        self._screenshotTaskQueue: List = []
        self._connection: Connection = connection

        self._defaultContext: BrowserContext = BrowserContext(self, None)

        self._contexts: Dict[str, BrowserContext] = dict()
        for contextId in contextIds:
            self._contexts[contextId] = BrowserContext(self, contextId)

        def _dummy_callback() -> Awaitable[None]:
            fut = asyncio.get_event_loop().create_future()
            fut.set_result(None)
            self.emit(Chrome.Events.Disconnected, None)
            return fut

        if closeCallback:
            self._closeCallback = closeCallback
        else:
            self._closeCallback = _dummy_callback

        self._targets: Dict[str, Target] = dict()
        self._connection.set_close_callback(self._on_close)
        self._connection.on("Target.targetCreated", self._targetCreated)
        self._connection.on("Target.targetDestroyed", self._targetDestroyed)
        self._connection.on("Target.targetInfoChanged", self.targetInfoChanged)

    def targets(self) -> List["Target"]:
        """Get all targets of this browser."""
        return [target for target in self._targets.values() if target._isInitialized]

    async def newPage(self) -> Page:
        page = await self._defaultContext.newPage()
        return page

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
        context = BrowserContext(self, contextId)
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

    @staticmethod
    async def create(
        connection: Connection,
        contextIds: List[str],
        ignoreHTTPSErrors: bool,
        appMode: bool,
        process: Optional[Popen] = None,
        closeCallback: Callable[[], Awaitable[None]] = None,
    ) -> "Chrome":
        browser = Chrome(
            connection, contextIds, ignoreHTTPSErrors, appMode, process, closeCallback
        )
        await connection.send("Target.setDiscoverTargets", {"discover": True})
        return browser

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

    async def _targetDestroyed(self, event: dict) -> None:
        target = self._targets[event["targetId"]]
        target._initializedCallback(False)
        del self._targets[event["targetId"]]
        if await target._initializedPromise:
            self.emit(self.Events.TargetDestroyed, target)
            target.browserContext.emit(Chrome.Events.TargetDestroyed, target)

    async def targetInfoChanged(self, event: dict) -> None:
        target = self._targets.get(event["targetInfo"]["targetId"])
        if not target:
            raise BrowserError("target should exist before targetInfoChanged")
        target.targetInfoChanged(event["targetInfo"])

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


class BrowserContext(EventEmitter):
    Events = SimpleNamespace(
        TargetCreated="targetcreated",
        TargetDestroyed="targetdestroyed",
        TargetChanged="targetchanged",
    )

    def __init__(self, browser: Chrome, contextId) -> None:
        super().__init__()
        self._browser = browser
        self._id = contextId

    def targets(self) -> List["Target"]:
        targets = []
        for t in self._browser.targets():
            if t != self:
                targets.append(t)
        return targets

    def isIncognito(self) -> bool:
        return self._id is not None

    def newPage(self) -> Awaitable[Page]:
        return self._browser.createPageInContext(self._id)

    def browser(self) -> Chrome:
        return self._browser

    async def close(self):
        await self._browser._disposeContext(self._id)


class Target(object):
    """Browser's target class."""

    def __init__(
        self, targetInfo: dict, browserContext: BrowserContext, browser: Chrome
    ) -> None:
        self._browser = browser
        self._browserContext = browserContext
        self._targetInfo = targetInfo
        self._targetId = targetInfo["targetId"]
        self._page = None

        self._initializedPromise: asyncio.Future = asyncio.get_event_loop().create_future()
        self._isInitialized = (
            self._targetInfo["type"] != "page" or self._targetInfo["url"] != ""
        )
        if self._isInitialized:
            self._initializedCallback(True)

    def _initializedCallback(self, bl: bool) -> None:
        if not self._initializedPromise.done():
            self._initializedPromise.set_result(bl)

    async def createCDPSession(self) -> CDPSession:
        """Create a Chrome Devtools Protocol session attached to the target."""
        return await self._browser._connection.createSession(self._targetId)

    async def page(self) -> Optional[Page]:
        """Get page of this target."""
        if self._targetInfo["type"] == "page" and self._page is None:
            client = await self._browser._connection.createSession(self._targetId)
            new_page = await Page.create(
                client,
                self,
                self._browser.ignoreHTTPSErrors,
                self._browser._setDefaultViewport,
                self._browser._screenshotTaskQueue,
            )
            self._page = new_page
            return new_page
        return self._page

    @property
    def browserContext(self):
        return self._browserContext

    @property
    def url(self) -> str:
        """Get url of this target."""
        return self._targetInfo["url"]

    @property
    def type(self) -> str:
        """Get type of this target."""
        _type = self._targetInfo["type"]
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
        previousURL = self._targetInfo["url"]
        self._targetInfo = targetInfo

        if not self._isInitialized and (
            self._targetInfo["type"] != "page" or self._targetInfo["url"] != ""
        ):
            self._isInitialized = True
            self._initializedCallback(True)
            return
        if previousURL != targetInfo["url"]:
            self._browser.emit(Chrome.Events.TargetChanged, self)
