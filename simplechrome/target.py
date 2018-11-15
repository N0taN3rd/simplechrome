from asyncio import AbstractEventLoop, Future
from typing import Dict, Optional, TYPE_CHECKING

from .connection import SessionType
from .page import Page
from .util import ensure_loop


if TYPE_CHECKING:
    from .chrome import BrowserContext, Chrome  # noqa: F401

__all__ = ["Target"]


class Target(object):
    """Browser's target class."""

    def __init__(
        self,
        targetInfo: Dict[str, str],
        browserContext: "BrowserContext",
        browser: "Chrome",
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

    async def createCDPSession(self) -> SessionType:
        """Create a Chrome Devtools Protocol session attached to the target."""
        return await self._browser._connection.createCDPSession(self._targetId)

    async def page(self) -> Optional[Page]:
        """Get page of this target."""
        is_page = (
            self._targetInfo["type"] == "page"
            or self._targetInfo["type"] == "background_page"
        )
        if is_page and self._page is None:
            client = await self._browser._connection.createCDPSession(self._targetId)
            new_page = await Page.create(
                client,
                self,
                self._browser._defaultViewport,
                self._browser.ignoreHTTPSErrors,
                self._browser._screenshotTaskQueue,
                self._loop,
            )
            self._page = new_page
            return new_page
        return self._page

    def targetInfoChanged(self, targetInfo: dict) -> None:
        self._targetInfo = targetInfo

        if not self._isInitialized and (
            self._targetInfo["type"] != "page" or self._targetInfo["url"] != ""
        ):
            self._isInitialized = True
            self._initializedCallback(True)
            return

    def _initializedCallback(self, bl: bool) -> None:
        if self._initializedPromise and not self._initializedPromise.done():
            self._initializedPromise.set_result(bl)

    def _closedCallback(self) -> None:
        if self._isClosedPromise and not self._isClosedPromise.done():
            self._isClosedPromise.set_result(None)
