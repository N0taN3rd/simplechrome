from asyncio import Event, Future, Task
from typing import Awaitable, Callable, Dict, List, Optional, TYPE_CHECKING

from ._typings import Loop, OptionalLoop, OptionalTask, SlotsT, TargetInfo, Viewport
from .connection import SessionType
from .events import Events
from .helper import Helper
from .page import Page

if TYPE_CHECKING:
    from .chrome import BrowserContext, Chrome  # noqa: F401

__all__ = ["Target"]


class Target:
    __slots__: SlotsT = [
        "__weakref__",
        "_targetInfo",
        "_browserContext",
        "_sessionFactory",
        "_ignoreHTTPSErrors",
        "_defaultViewport",
        "_screenshotTaskQueue",
        "_loop",
        "_targetId",
        "_isolateWorlds",
        "_isInitialized",
        "_initializedEvent",
        "_initializedPromise",
        "_isClosedPromise",
        "_pagePromise",
    ]

    def __init__(
        self,
        targetInfo: TargetInfo,
        browserContext: "BrowserContext",
        sessionFactory: Callable[[], Awaitable[SessionType]],
        ignoreHTTPSErrors: bool,
        defaultViewport: Optional[Viewport] = None,
        screenshotTaskQueue: Optional[List] = None,
        loop: OptionalLoop = None,
    ) -> None:
        self._targetInfo: TargetInfo = targetInfo
        self._browserContext: "BrowserContext" = browserContext
        self._sessionFactory: Callable[[], Awaitable[SessionType]] = sessionFactory
        self._ignoreHTTPSErrors: bool = ignoreHTTPSErrors
        self._defaultViewport: Optional[Viewport] = defaultViewport
        self._screenshotTaskQueue: List = screenshotTaskQueue or []
        self._loop: Loop = Helper.ensure_loop(loop)
        self._targetId: str = self._targetInfo["targetId"]
        self._isolateWorlds: bool = True
        self._isInitialized: bool = False
        self._initializedEvent: Event = Event(loop=self._loop)
        self._initializedPromise: Task = self._loop.create_task(self._on_initialized())
        self._isClosedPromise: Future = self._loop.create_future()
        self._pagePromise: OptionalTask = None
        if self._targetInfo["type"] != "page" or self._targetInfo["url"] != "":
            self._isInitialized = True
            self._initializedEvent.set()

    @property
    def target_id(self) -> str:
        return self._targetInfo["targetId"]

    @property
    def initialized(self) -> bool:
        return self._isInitialized

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
            or _type == "background_page"
            or _type == "browser"
        ):
            return _type
        return "other"

    @property
    def is_page_type(self) -> bool:
        _type: str = self._targetInfo["type"]
        return _type == "page" or _type == "browser"

    @property
    def opener(self) -> Optional["Target"]:
        openerId = self._targetInfo.get("openerId")
        if openerId is not None:
            return self.browser.target(openerId)
        return openerId

    @property
    def browser(self) -> "Chrome":
        return self._browserContext.browser()

    @property
    def browserContext(self) -> "BrowserContext":
        return self._browserContext

    def page(self) -> Awaitable[Page]:
        if self.is_page_type or self._pagePromise is None:
            self._pagePromise = self._loop.create_task(self._create_page_for_target())
        return self._pagePromise

    def createSession(self) -> Awaitable[SessionType]:
        """Create a Chrome Devtools Protocol session attached to the target."""
        return self._sessionFactory()

    def _targetInfoChanged(self, targetInfo: Dict) -> None:
        self._targetInfo = targetInfo

        if not self._isInitialized and (
            self._targetInfo["type"] != "page" or self._targetInfo["url"] != ""
        ):
            self._isInitialized = True
            self._initializedEvent.set()
            return

    def _initializedCallback(self, bl: bool) -> None:
        self._isInitialized = bl
        if bl:
            self._initializedEvent.set()

    def _closedCallback(self) -> None:
        if self._isClosedPromise and not self._isClosedPromise.done():
            self._initializedEvent.set()
            self._isInitialized = False
            self._isClosedPromise.set_result(None)

    async def _create_page_for_target(self) -> Page:
        client = await self._sessionFactory()
        page = await Page.create(
            client,
            self,
            self._defaultViewport,
            self._ignoreHTTPSErrors,
            self._isolateWorlds,
            self._screenshotTaskQueue,
            self._loop,
        )
        return page

    async def _on_initialized(self) -> bool:
        await self._initializedEvent.wait()
        success = self._isInitialized
        if not success:
            return False
        opener = self.opener
        if opener is None or opener._pagePromise is None or self.type != "page":
            return True
        opener_page: Page = await opener._pagePromise
        if opener_page.listener_count(Events.Page.Dialog) == 0:
            return True
        popupPage = await self.page()
        opener_page.emit(Events.Page.Popup, popupPage)
        return True
