"""Page module."""
import asyncio
import base64
import logging
import mimetypes
from asyncio import Future, Task
from typing import (
    Any,
    Awaitable,
    Callable,
    ClassVar,
    Dict,
    List,
    Optional,
    TYPE_CHECKING,
    Union,
)

import aiofiles
import math
from pyee2 import EventEmitterS

from ._typings import (
    CDPEvent,
    HTTPHeaders,
    Number,
    OptionalLoop,
    OptionalViewport,
    SlotsT,
    Viewport,
)
from .connection import ClientType, Connection
from .console_message import ConsoleMessage
from .dialog import Dialog
from .emulation_manager import EmulationManager
from .errors import PageError
from .events import Events
from .execution_context import ElementHandle, JSHandle, createJSHandle
from .frame_manager import Frame, FrameManager
from .helper import Helper
from .input import Keyboard, Mouse, Touchscreen
from .network import Cookie, Request, Response
from .network_manager import NetworkManager
from .timeoutSettings import TimeoutSettings
from .tracing import Tracing
from .log import Log, LogEntry

if TYPE_CHECKING:
    from .target import Target  # noqa: F401

logger = logging.getLogger(__name__)

__all__ = ["Page"]


class Page(EventEmitterS):
    __slots__: SlotsT = [
        "__weakref__",
        "_client",
        "_closed",
        "_emulationManager",
        "_frameManager",
        "_javascriptEnabled",
        "_keyboard",
        "_lifecycle_emitting",
        "_log",
        "_mouse",
        "_mouse",
        "_networkManager",
        "_screenshotTaskQueue",
        "_target",
        "_timeoutSettings",
        "_touchscreen",
        "_tracing",
        "_viewport",
    ]

    PaperFormats: ClassVar[Dict[str, Dict[str, Number]]] = {
        "letter": {"width": 8.5, "height": 11},
        "legal": {"width": 8.5, "height": 14},
        "tabloid": {"width": 11, "height": 17},
        "ledger": {"width": 17, "height": 11},
        "a0": {"width": 33.1, "height": 46.8},
        "a1": {"width": 23.4, "height": 33.1},
        "a2": {"width": 16.5, "height": 23.4},
        "a3": {"width": 11.7, "height": 16.5},
        "a4": {"width": 8.27, "height": 11.7},
        "a5": {"width": 5.83, "height": 8.27},
    }

    @staticmethod
    async def create(
        client: ClientType,
        target: "Target",
        defaultViewport: OptionalViewport = None,
        ignoreHTTPSErrors: bool = False,
        isolateWorlds: bool = True,
        screenshotTaskQueue: list = None,
        loop: OptionalLoop = None,
    ) -> "Page":
        """Async function which makes new page object."""
        page = Page(
            client,
            target,
            ignoreHTTPSErrors=ignoreHTTPSErrors,
            isolateWorlds=isolateWorlds,
            screenshotTaskQueue=screenshotTaskQueue,
            loop=loop,
        )

        await asyncio.gather(
            page.frame_manager.initialize(),
            page.network_manager.initialize(),
            page.log.enable(),
            loop=loop,
        )
        if defaultViewport is not None:
            await page.setViewport(defaultViewport)
        return page

    def __init__(
        self,
        client: ClientType,
        target: "Target",
        ignoreHTTPSErrors: bool = False,
        isolateWorlds: bool = True,
        screenshotTaskQueue: list = None,
        loop: OptionalLoop = None,
    ) -> None:
        super().__init__(loop=Helper.ensure_loop(loop))
        self._closed: bool = False
        self._client: ClientType = client
        self._target: "Target" = target
        self._log: Log = Log(self._client, loop=self._loop)
        self._keyboard: Keyboard = Keyboard(client)
        self._mouse: Mouse = Mouse(client, self._keyboard)
        self._timeoutSettings: TimeoutSettings = TimeoutSettings()
        self._touchscreen: Touchscreen = Touchscreen(client, self._keyboard)
        self._networkManager: NetworkManager = NetworkManager(
            client, ignoreHTTPSErrors=ignoreHTTPSErrors, loop=self._loop
        )
        self._frameManager: FrameManager = FrameManager(
            client,
            timeoutSettings=self._timeoutSettings,
            page=self,
            networkManager=self._networkManager,
            isolateWorlds=isolateWorlds,
            loop=self._loop,
        )
        self._networkManager.setFrameManager(self._frameManager)
        self._emulationManager: EmulationManager = EmulationManager(client)
        self._tracing: Tracing = Tracing(client)
        self._javascriptEnabled: bool = True
        self._lifecycle_emitting: bool = False
        self._viewport: Optional[Dict[str, Any]] = None

        if screenshotTaskQueue is None:
            screenshotTaskQueue = []
        self._screenshotTaskQueue: List = screenshotTaskQueue

        _fm = self._frameManager
        _fm.on(
            Events.FrameManager.FrameAttached,
            lambda event: self.emit(Events.Page.FrameAttached, event),
        )
        _fm.on(
            Events.FrameManager.FrameDetached,
            lambda event: self.emit(Events.Page.FrameDetached, event),
        )
        _fm.on(
            Events.FrameManager.FrameNavigated,
            lambda event: self.emit(Events.Page.FrameNavigated, event),
        )
        _fm.on(
            Events.FrameManager.FrameNavigatedWithinDocument,
            lambda event: self.emit(Events.Page.FrameNavigatedWithinDocument, event),
        )

        _nm = self._networkManager
        _nm.on(
            Events.NetworkManager.Request,
            lambda event: self.emit(Events.Page.Request, event),
        )
        _nm.on(
            Events.NetworkManager.Response,
            lambda event: self.emit(Events.Page.Response, event),
        )
        _nm.on(
            Events.NetworkManager.RequestFailed,
            lambda event: self.emit(Events.Page.RequestFailed, event),
        )
        _nm.on(
            Events.NetworkManager.RequestFinished,
            lambda event: self.emit(Events.Page.RequestFinished, event),
        )

        self._log.on(Events.Log.EntryAdded, self._onLogEntryAdded)

        client.on("Page.domContentEventFired", self._onDomContentEventFired)
        client.on("Page.loadEventFired", self._onLoadEventFired)
        client.on("Page.javascriptDialogOpening", self._onDialog)
        client.on("Runtime.consoleAPICalled", self._onConsoleAPI)
        client.on("Runtime.exceptionThrown", self._onExceptionThrown)
        client.on("Inspector.targetCrashed", self._onTargetCrashed)

        def closed(*args: Any, **kwargs: Any) -> None:
            self.emit(Events.Page.Close)
            self._closed = True

        self._target._isClosedPromise.add_done_callback(closed)

    @property
    def frame_manager(self) -> FrameManager:
        return self._frameManager

    @property
    def network_manager(self) -> NetworkManager:
        return self._networkManager

    @property
    def emulation_manager(self) -> EmulationManager:
        return self._emulationManager

    @property
    def keyboard(self) -> Keyboard:
        """Get :class:`~simplechrome.input.Keyboard` object."""
        return self._keyboard

    @property
    def touchscreen(self) -> Touchscreen:
        """Get :class:`~simplechrome.input.Touchscreen` object."""
        return self._touchscreen

    @property
    def mouse(self) -> Mouse:
        """Get :class:`~simplechrome.input.Mouse` object."""
        return self._mouse

    @property
    def tracing(self) -> Tracing:
        return self._tracing

    @property
    def log(self) -> Log:
        return self._log

    @property
    def target(self) -> "Target":
        """Return a target this page created from."""
        return self._target

    @property
    def mainFrame(self) -> Optional[Frame]:
        """Get main :class:`~simplechrome.frame_manager.Frame` of this page."""
        return self._frameManager.mainFrame

    @property
    def url(self) -> str:
        """Get url of this page."""
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.url

    @property
    def frames(self) -> List[Frame]:
        """Get all frames of this page."""
        return list(self._frameManager.frames())

    @property
    def viewport(self) -> dict:
        """Get viewport dict.

        Field of returned dict is same as :meth:`setViewport`.
        """
        return self._viewport

    def setDefaultNavigationTimeout(self, timeout: Number) -> None:
        """Change the default maximum navigation timeout.

        This method changes the default timeout of 30 seconds for the following
        methods:

        * :meth:`goto`
        * :meth:`goBack`
        * :meth:`goForward`
        * :meth:`reload`
        * :meth:`waitForNavigation`

        :arg int timeout: Maximum navigation time in milliseconds.
        """
        self._frameManager.setDefaultNavigationTimeout(timeout)

    def setDefaultTimeout(self, timeout: Number) -> None:
        self._timeoutSettings.setDefaultTimeout(timeout)

    def setDefaultJSTimeout(self, timeout: Number) -> None:
        self._timeoutSettings.setDefaultJSTimeout(timeout)

    def network_idle_promise(
        self, num_inflight: int = 2, idle_time: int = 2, global_wait: int = 60
    ) -> Awaitable[None]:
        return self._frameManager.network_idle_promise(
            num_inflight=num_inflight, idle_time=idle_time, global_wait=global_wait
        )

    def enable_lifecycle_emitting(self) -> None:
        self._frameManager.on(Events.FrameManager.LifecycleEvent, self._on_lifecycle)

    def disable_lifecycle_emitting(self) -> None:
        self._frameManager.disable_lifecycle_emitting()
        self._frameManager.remove_listener(
            Events.FrameManager.LifecycleEvent, self._on_lifecycle
        )

    def tap(self, selector: str) -> Awaitable[None]:
        """Tap the element which matches the ``selector``.

        :param selector: A selector to search element to touch.
        """
        frame = self.mainFrame
        if frame is None:
            raise PageError("no main frame")
        return frame.tap(selector)

    def querySelectorEval(
        self, selector: str, pageFunction: str, *args: Any
    ) -> Awaitable[Any]:
        """Execute function with an element which matches ``selector``.

        :arg str selector: A selector to query page for.
        :arg str pageFunction: String of JavaScript function to be evaluated on
                               browser. This function takes an element which
                               matches the selector as a first argument.
        :arg Any args: Arguments to pass to ``pageFunction``.

        This method raises error if no element matched the ``selector``.
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.querySelectorEval(selector, pageFunction, *args)

    def querySelectorAllEval(
        self, selector: str, pageFunction: str, *args: Any
    ) -> Awaitable[Any]:
        """Execute function with all elements which matches ``selector``.

        :arg str selector: A selector to query page for.
        :arg str pageFunction: String of JavaScript function to be evaluated on
                               browser. This function takes Array of the
                               matched elements as the first argument.
        :arg Any args: Arguments to pass to ``pageFunction``.
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.querySelectorAllEval(selector, pageFunction, *args)

    def querySelectorAll(self, selector: str) -> Awaitable[List["ElementHandle"]]:
        """Get all element which matches `selector` as a list.

        :arg str selector: A selector to search element.
        :return List[ElementHandle]: List of
            :class:`~simplechrome.element_handle.ElementHandle` which matches the
            ``selector``. If no element is matched to the ``selector``, return
            empty list.
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.querySelectorAll(selector)

    def querySelector(self, selector: str) -> Awaitable[Optional["ElementHandle"]]:
        """Get an Element which matches ``selector``.

        :param selector: A selector to search element.
        :return Optional[ElementHandle]: If element which matches the
            ``selector`` is found, return its
            :class:`~simplechrome.element_handle.ElementHandle`. If not found,
            returns ``None``.
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.querySelector(selector)

    def xpath(self, expression: str) -> Awaitable[List[ElementHandle]]:
        """Evaluate XPath expression.

        If there is no such element in this page, return None.

        :arg str expression: XPath string to be evaluated.
        """
        frame = self.mainFrame
        if not frame:
            raise Exception("no main frame.")
        return frame.xpath(expression)

    def evaluateHandle(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> Awaitable[JSHandle]:
        """Execute function on this page.

        Difference between :meth:`~simplechrome.page.Page.evaluate` and
        :meth:`~simplechrome.page.Page.evaluateHandle` is that
        ``evaluateHandle`` returns JSHandle object (not value).

        :arg str pageFunction: JavaScript function to be executed.
        """
        if not self.mainFrame:
            raise PageError("no main frame.")
        return self.mainFrame.evaluateHandle(pageFunction, *args, withCliAPI=withCliAPI)

    def addScriptTag(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> Awaitable[ElementHandle]:
        """Add script tag to this page.

        One of ``url``, ``path`` or ``content`` option is necessary.
            * ``url`` (string): URL of a script to add.
            * ``path`` (string): Path to the local JavaScript file to add.
            * ``content`` (string): JavaScript string to add.

        :return ElementHandle: :class:`~simplechrome.element_handle.ElementHandle`
                               of added tag.
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.addScriptTag(options, **kwargs)

    def addStyleTag(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> Awaitable[ElementHandle]:
        """Add style or link tag to this page.

        One of ``url``, ``path`` or ``content`` option is necessary.
            * ``url`` (string): URL of the link tag to add.
            * ``path`` (string): Path to the local CSS file to add.
            * ``content`` (string): CSS string to add.

        :return ElementHandle: :class:`~simplechrome.element_handle.ElementHandle`
                               of added tag.
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.addStyleTag(options, **kwargs)

    def content(self) -> Awaitable[str]:
        """Get the whole HTML contents of the page."""
        frame = self.mainFrame
        if frame is None:
            raise PageError("No main frame.")
        return frame.content()

    def title(self) -> Awaitable[str]:
        """Get page title."""
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.title()

    def click(
        self,
        selector: str,
        button: str = "left",
        clickCount: int = 1,
        delay: Number = 0,
    ) -> Awaitable[None]:
        """Click element which matches ``selector``

        :param selector: The query selector to be used
        :param button: ``left``, ``right``, or ``middle``, defaults to ``left``
        :param clickCount: defaults to 1
        :param delay: Time to wait between ``mousedown`` and ``mouseup`` in milliseconds. Defaults to 0.
        """
        frame = self.mainFrame
        if frame is None:
            raise PageError("No main frame.")
        return frame.click(selector, button, clickCount, delay)

    def hover(self, selector: str) -> Awaitable[None]:
        """Mouse hover the element which matches ``selector``.

        If no element matched the ``selector``, raise ``PageError``.
        """
        frame = self.mainFrame
        if frame is None:
            raise PageError("No main frame.")
        return frame.hover(selector)

    def focus(self, selector: str) -> Awaitable[None]:
        """Focus the element which matches ``selector``.

        If no element matched the ``selector``, raise ``PageError``.
        """
        frame = self.mainFrame
        if frame is None:
            raise PageError("No main frame.")
        return frame.focus(selector)

    def select(self, selector: str, *values: str) -> Awaitable[List[str]]:
        """Select options and return selected values.

        If no element matched the ``selector``, raise ``ElementHandleError``.
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.select(selector, *values)

    def type(self, selector: str, text: str, delay: Number = 0) -> Awaitable[None]:
        """Type characters.

        This method sends ``keydown``, ``keypress``/``input``, and ``keyup``
        event for each character in the ``text``.

        To press a special key, like ``Control`` or ``ArrowDown``, use
        :meth:`press` method.

        :param selector: The query selector to be used
        :param text: Text to type into this element.
        :param delay: Optional amount of ``delay`` that specifies the amount
         of time to wait between key presses in seconds. Defaults to 0.
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.type(selector, text, delay)

    def waitFor(
        self,
        selectorOrFunctionOrTimeout: Union[str, Number],
        options: Optional[Dict] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[Optional[JSHandle]]:
        """Wait for function, timeout, or element which matches on page.

        This method behaves differently with respect to the first argument:

        * If ``selectorOrFunctionOrTimeout`` is number (int or float), then it
          is treated as a timeout in milliseconds and this returns future which
          will be done after the timeout.
        * If ``selectorOrFunctionOrTimeout`` is a string of JavaScript
          function, this method is a shortcut to :meth:`waitForFunction`.
        * If ``selectorOrFunctionOrTimeout`` is a selector string or xpath
          string, this method is a shortcut to :meth:`waitForSelector` or
          :meth:`waitForXPath`. If the string starts with ``//``, the string is
          treated as xpath.

        simplechrome tries to automatically detect function or selector, but
        sometimes miss-detects. If not work as you expected, use
        :meth:`waitForFunction` or :meth:`waitForSelector` dilectly.

        :arg selectorOrFunctionOrTimeout: A selector, xpath, or function
                                          string, or timeout (milliseconds).
        :arg Any args: Arguments to pass the function.
        :return: Return awaitable object which resolves to a JSHandle of the
                 success value.

        Available options: see :meth:`waitForFunction` or
        :meth:`waitForSelector`
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.waitFor(selectorOrFunctionOrTimeout, options, *args, **kwargs)

    def waitForSelector(
        self, selector: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> Awaitable[Optional[ElementHandle]]:
        """Wait until element which matches ``selector`` appears on page.

        Wait for the ``selector`` to appear in page. If at the moment of
        callingthe method the ``selector`` already exists, the method will
        return immediately. If the selector doesn't appear after the
        ``timeout`` milliseconds of waiting, the function will raise error.

        :arg str selector: A selector of an element to wait for.
        :return: Return awaitable object which resolves when element specified
                 by selector string is added to DOM.

        This method accepts the following options:

        * ``visible`` (bool): Wait for element to be present in DOM and to be
          visible; i.e. to not have ``display: none`` or ``visibility: hidden``
          CSS properties. Defaults to ``False``.
        * ``hidden`` (bool): Wait for eleemnt to not be found in the DOM or to
          be hidden, i.e. have ``display: none`` or ``visibility: hidden`` CSS
          properties. Defaults to ``False``.
        * ``timeout`` (int|float): Maximum time to wait for in milliseconds.
          Defaults to 30000 (30 seconds).
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.waitForSelector(selector, options, **kwargs)

    def waitForXPath(
        self, xpath: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> Awaitable[Optional[ElementHandle]]:
        """Wait until eleemnt which matches ``xpath`` appears on page.

        Wait for the ``xpath`` to appear in page. If the moment of calling the
        method the ``xpath`` already exists, the method will return
        immediately. If the xpath doesn't appear after ``timeout`` millisecons
        of waiting, the function will raise exception.


        :arg str xpath: A [xpath] of an element to wait for.
        :return: Return awaitable object which resolves when element specified
                 by xpath string is added to DOM.

        Avalaible options are:

        * ``visible`` (bool): wait for element to be present in DOM and to be
          visible, i.e. to not have ``display: none`` or ``visibility: hidden``
          CSS properties. Defaults to ``False``.
        * ``hidden`` (bool): wait for element to not be found in the DOM or to
          be hidden, i.e. have ``display: none`` or ``visibility: hidden`` CSS
          properties. Defaults to ``False``.
        * ``timeout`` (int|float): maximum time to wait for in milliseconds.
          Defaults to 30000 (30 seconds).
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.waitForXPath(xpath, options, **kwargs)

    def waitForFunction(
        self, pageFunction: str, options: Dict = None, *args: Any, **kwargs: Any
    ) -> Awaitable[Optional[JSHandle]]:
        """Wait until the function completes and returns a truethy value.

        :arg Any args: Arguments to pass to ``pageFunction``.
        :return: Return awaitable object which resolves when the
                 ``pageFunction`` returns a truethy value. It resolves to a
                 :class:`~simplechrome.execution_context.JSHandle` of the truethy
                 value.

        This method accepts the following options:

        * ``polling`` (str|number): An interval at which the ``pageFunction``
          is executed, defaults to ``raf``. If ``polling`` is a number, then
          it is treated as an interval in milliseconds at which the function
          would be executed. If ``polling`` is a string, then it can be one of
          the following values:

          * ``raf``: to constantly execute ``pageFunction`` in
            ``requestAnimationFrame`` callback. This is the tightest polling
            mode which is suitable to observe styling changes.
          * ``mutation``: to execute ``pageFunction`` on every DOM mutation.

        * ``timeout`` (int|float): maximum time to wait for in milliseconds.
        """
        frame = self.mainFrame
        if not frame:
            raise PageError("no main frame.")
        return frame.waitForFunction(pageFunction, options, *args, **kwargs)

    def enableNetworkCache(self) -> Awaitable[None]:
        return self._networkManager.enableNetworkCache()

    def disableNetworkCache(self) -> Awaitable[None]:
        return self._networkManager.disableNetworkCache()

    def cookies(self, *urls: str) -> Awaitable[List[Cookie]]:
        """Get all cookies that are for the supplied URLs

        Defaults to the current pages URL
        :return: A list of the cookies that match if any
        """
        if not urls:
            cookies_for_urls = [self.url]
        else:
            cookies_for_urls = list(urls)
        return self._networkManager.getCookies(cookies_for_urls)

    def getAllCookies(self) -> Awaitable[List[Cookie]]:
        """Get all cookies

        :return: A list of the pages cookies if any
        """
        return self._networkManager.getAllCookies()

    async def captureSnapshot(self, format_: str = "mhtml") -> str:
        """Returns a snapshot of the page as a string. For MHTML format,
        the serialization includes iframes, shadow DOM, external resources,
        and element-inline styles.
        EXPERIMENTAL


        :param format_: Format (defaults to mhtml)
        :return: Serialized page data.
        """
        result = await self._frameManager.captureSnapshot(format_)
        return result

    async def enable_violation_reporting(self) -> None:
        await self._log.startViolationsReport(
            [
                {"name": "blockedEvent", "threshold": 1},
                {"name": "blockedParser", "threshold": 1},
            ]
        )

    async def setBypassCSP(self, enabled: bool) -> None:
        await self._client.send("Page.setBypassCSP", {"enabled": enabled})

    async def setJavaScriptEnabled(self, enabled: bool) -> None:
        """Set JavaScript enable/disable."""
        await self._emulationManager.setScriptExecutionDisabled(not enabled)

    async def setViewport(self, viewport: Viewport) -> None:
        """Set viewport.

        Available options are:
            * ``width`` (int): page width in pixel.
            * ``height`` (int): page height in pixel.
            * ``deviceScaleFactor`` (float): Default to 1.0.
            * ``isMobile`` (bool): Default to ``False``.
            * ``hasTouch`` (bool): Default to ``False``.
            * ``isLandscape`` (bool): Default to ``False``.
        :param viewport: The viewport definition to be used
        """
        needsReload = await self._emulationManager.emulateViewport(viewport)
        self._viewport = viewport
        if needsReload:
            await self.reload()

    async def setWindowBounds(self, bounds: Dict) -> None:
        windowDescriptor = await self.getWindowDescriptor()
        await self._client.send(
            "Browser.setWindowBounds",
            {"windowId": windowDescriptor["windowId"], "bounds": bounds},
        )

    async def setRequestInterception(self, value: bool) -> None:
        """Enable/disable request interception."""
        await self._networkManager.setRequestInterception(value)

    async def setOfflineMode(self, enabled: bool) -> None:
        """Set offline mode enable/disable."""
        await self._networkManager.setOfflineMode(enabled)

    async def setExtraHTTPHeaders(self, headers: HTTPHeaders) -> None:
        """Set extra http headers."""
        return await self._networkManager.setExtraHTTPHeaders(headers)

    async def setUserAgent(self, userAgent: str) -> None:
        """Set user agent to use in this page."""
        await self._networkManager.setUserAgent(userAgent)

    async def setContent(self, html: str) -> None:
        """Set content to this page."""
        frame = self.mainFrame
        if frame is None:
            raise PageError("No main frame.")
        await frame.setContent(html)

    async def setCacheEnabled(self, enabled: bool = True) -> None:
        """Enable/Disable cache for each request.

        By default, caching is enabled.
        """
        await self._networkManager.setCacheEnabled(enabled)

    async def getWindowDescriptor(self) -> Dict:
        return await self._client.send(
            "Browser.getWindowForTarget", {"targetId": self._target._targetId}
        )

    async def getWindowBounds(self) -> Dict:
        windowDescriptor = await self.getWindowDescriptor()
        return windowDescriptor.get("bounds")

    async def stopLoading(self) -> None:
        await self._client.send("Page.stopLoading")

    async def queryObjects(self, prototypeHandle: JSHandle) -> JSHandle:
        """Iterate js heap and finds all the objects with the handle.

        :arg JSHandle prototypeHandle: JSHandle of prototype object.
        """
        if not self.mainFrame:
            raise PageError("no main frame.")
        context = await self.mainFrame.executionContext()
        if not context:
            raise PageError("No context.")
        return await context.queryObjects(prototypeHandle)

    async def deleteCookie(self, *cookies: Dict) -> None:
        """Delete cookie."""
        pageURL = self.url
        for cookie in cookies:
            item = dict(**cookie)
            if not cookie.get("url") and pageURL.startswith("http"):
                item["url"] = pageURL
            await self._networkManager.deleteCookies(item)

    async def setCookie(self, *cookies: Dict) -> None:
        """Set cookies."""
        pageURL = self.url
        startsWithHTTP = pageURL.startswith("http")
        items = []
        for cookie in cookies:
            item = dict(**cookie)
            if "url" not in item and startsWithHTTP:
                item["url"] = pageURL
            if item.get("url") == "about:blank":
                name = item.get("name", "")
                raise PageError(f'Blank page can not have cookie "{name}"')
            if item.get("url", "").startswith("data:"):
                name = item.get("name", "")
                raise PageError(f'Data URL page can not have cookie "{name}"')
            items.append(item)
        await self.deleteCookie(*items)
        if items:
            await self._networkManager.setCookies(items)

    async def authenticate(self, credentials: Dict[str, str]) -> Any:
        """Provide credentials for http authentication.

        ``credentials`` should be ``None`` or dict which has ``username`` and
        ``password`` field.
        """
        return await self._networkManager.authenticate(credentials)

    async def metrics(self) -> Dict[str, Any]:
        """Get metrics."""
        response = await self._client.send("Performance.getMetrics")
        return self._buildMetricsObject(response["metrics"])

    async def goto(
        self,
        url: str,
        options: Optional[Dict[str, Union[str, Number]]] = None,
        **kwargs: Any,
    ) -> Optional[Response]:
        """Go to the ``url``.

        :arg string url: URL to navigate page to. The url should include
            scheme, e.g. ``https://``.
        :arg dict options:

        Available options are:

        * ``timeout`` (int): Maximum navigation time in seconds, defaults
          to 30 seconds, pass ``0`` to desable timeout. The default value can
          be changed by using the :meth:`setDefaultNavigationTimeout` method.
        * ``waitUntil`` (str|List[str]): When to consider navigation succeeded,
          defaults to ``load``. Given a list of event strings, navigation is
          considered to be successful after all events have been fired. Events
          can be either:

          * ``load``: when ``load`` event is fired.
          * ``documentloaded``: when the ``DOMContentLoaded`` event is fired.
          * ``networkidle0``: when there are no more than 0 network connections
            for at least 500 ms.
          * ``networkidle0``: when there are no more than 2 network connections
            for at least 500 ms.

        * ``all_frames`` (bool): should all frames or only the top frame be checked
           for the the value of ``waitUntil``, defaults to `True`

        * ``transition`` (str): Intended transition type. Can be one of:

          * `link`, `typed`, `address_bar`, `auto_bookmark`, `auto_subframe`, `manual_subframe`, `generated`,
            `auto_toplevel`, `form_submit`, `reload`, `keyword`, `keyword_generated`, `other`.

        * ``referrer`` (str): Referrer URL. Defaults to the referrer value set using page.setExtraHTTPHeaders
        if that key exists
        """
        return await self._frameManager.mainFrame.goto(url, options, **kwargs)

    async def reload(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> Optional[Response]:
        """Reload this page.

        Available options are same as :meth:`goto` method.
        """
        options = Helper.merge_dict(options, kwargs)
        response = (
            await asyncio.gather(
                self.waitForNavigation(options), self._client.send("Page.reload")
            )
        )[0]
        return response

    async def waitForNavigation(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> Optional[Response]:
        """Wait for navigation.

        Available options are same as :meth:`goto` method.
        """
        return await self._frameManager.mainFrame.waitForNavigation(options, **kwargs)

    async def waitForRequest(
        self,
        urlOrPredicate: Union[str, Callable[[Request], bool]],
        options: Optional[Dict] = None,
        **kwargs: Any,
    ) -> Union[Future, Task]:
        timeout = Helper.merge_dict(options, kwargs).get("timeout", 30)

        def wrapped_predicate(req: Request) -> bool:
            if isinstance(urlOrPredicate, str):
                return req.url == urlOrPredicate
            return urlOrPredicate(req)

        return Helper.waitForEvent(
            self._networkManager,
            Events.NetworkManager.Request,
            wrapped_predicate,
            timeout,
        )

    async def waitForResponse(
        self,
        urlOrPredicate: Union[str, Callable[[Response], bool]],
        options: Optional[Dict] = None,
        **kwargs: Any,
    ) -> Union[Future, Task]:
        timeout = Helper.merge_dict(options, kwargs).get("timeout", 30)

        def wrapped_predicate(res: Response) -> bool:
            if isinstance(urlOrPredicate, str):
                return res.url == urlOrPredicate
            return urlOrPredicate(res)

        return Helper.waitForEvent(
            self._networkManager,
            Events.NetworkManager.Response,
            wrapped_predicate,
            timeout,
        )

    async def goBack(self, options: Dict = None, **kwargs: Any) -> Optional[Response]:
        """Navigate to the previous page in history.

        Available options are same as :meth:`goto` method.
        """
        options = Helper.merge_dict(options, kwargs)
        return await self._go(-1, options)

    async def goForward(
        self, options: Dict = None, **kwargs: Any
    ) -> Optional[Response]:
        """Navigate to the next page in history.

        Available options are same as :meth:`goto` method.
        """
        options = Helper.merge_dict(options, kwargs)
        return await self._go(+1, options)

    async def bringToFront(self) -> None:
        """Bring page to front (activate tab)."""
        await self._client.send("Page.bringToFront")

    async def emulate(self, options: Dict = None, **kwargs: Any) -> None:
        """Emulate viewport and user agent."""
        options = Helper.merge_dict(options, kwargs)
        await self.setViewport(options.get("viewport", {}))
        await self.setUserAgent(options.get("userAgent", ""))

    async def emulateMedia(self, mediaType: Optional[str] = None) -> None:
        """Emulate css media type of the page."""
        if mediaType not in ["screen", "print", None, ""]:
            raise ValueError(f"Unsupported media type: {mediaType}")
        await self._client.send(
            "Emulation.setEmulatedMedia", {"media": mediaType or ""}
        )

    async def evaluateOnNewDocument(
        self, pageFunction: str, *args: str, raw: bool = False
    ) -> Dict[str, int]:
        """Add a JavaScript function to the document.

        This function would be invoked in one of the following scenarios:

        * whenever the page is navigated
        * whenever the child frame is attached or navigated. Inthis case, the
          function is invoked in the context of the newly attached frame.
        """
        if raw:
            source = pageFunction
        else:
            source = Helper.evaluationString(pageFunction, *args)
        return await self._client.send(
            "Page.addScriptToEvaluateOnNewDocument", {"source": source}
        )

    async def removeScriptToEvaluateOnNewDocument(
        self, identifier: Union[int, Dict[str, int]]
    ) -> None:
        """Removes given script from the list."""
        if not isinstance(identifier, dict):
            identifier = {"identifier": identifier}
        await self._client.send("Page.removeScriptToEvaluateOnNewDocument", identifier)

    async def raw_screenshot(self, options: Dict = None, **kwargs: Any) -> bytes:
        options = Helper.merge_dict(options, kwargs)
        screenshotType = None
        if "type" in options:
            screenshotType = options["type"]
            if screenshotType not in ["png", "jpeg"]:
                raise ValueError(f"Unknown type value: {screenshotType}")
        elif "path" in options:
            mimeType, _ = mimetypes.guess_type(options["path"])
            if mimeType == "image/png":
                screenshotType = "png"
            elif mimeType == "image/jpeg":
                screenshotType = "jpeg"
            else:
                raise ValueError("Unsupported screenshot " f"mime type: {mimeType}")
        if not screenshotType:
            screenshotType = "png"
        return await self._rawScreenshotTask(screenshotType, options)

    async def screenshot(self, options: Dict = None, **kwargs: Any) -> bytes:
        """Take a screen shot.

        The following options are available:

        * ``path`` (str): The file path to save the image to. The screenshot
          type will be inferred from the file extension.
        * ``type`` (str): Specify screenshot type, can be either ``jpeg`` or
          ``png``. Defaults to ``png``.
        * ``quality`` (int): The quality of the image, between 0-100. Not
          applicable to ``png`` image.
        * ``fullPage`` (bool): When true, take a screenshot of the full
          scrollable page. Defaults to ``False``.
        * ``clip`` (dict): An object which specifies clipping region of the
          page. This option should have the following fields:

          * ``x`` (int): x-coordinate of top-left corner of clip area.
          * ``y`` (int): y-coordinate of top-left corner of clip area.
          * ``width`` (int): width of clipping area.
          * ``height`` (int): height of clipping area.

        * ``omitBackground`` (bool): Hide default white background and allow
          capturing screenshot with transparency.
        """
        options = Helper.merge_dict(options, kwargs)
        screenshotType = None
        if "type" in options:
            screenshotType = options["type"]
            if screenshotType not in ["png", "jpeg"]:
                raise ValueError(f"Unknown type value: {screenshotType}")
        elif "path" in options:
            mimeType, _ = mimetypes.guess_type(options["path"])
            if mimeType == "image/png":
                screenshotType = "png"
            elif mimeType == "image/jpeg":
                screenshotType = "jpeg"
            else:
                raise ValueError("Unsupported screenshot " f"mime type: {mimeType}")
        if screenshotType is None:
            screenshotType = "png"
        if options.get("quality"):
            if screenshotType != "jpeg":
                raise ValueError(
                    f"options.quality is unsupported for the {screenshotType} screenshots"
                )
            quality = options.get("quality")
            if not isinstance(quality, (int, float)):
                raise ValueError(
                    f"Expected options.quality to be a int or float but found {type(quality)}"
                )
            if not (0 <= quality <= 100):
                raise ValueError(
                    f"Expected options.quality to be between 0 and 100 (inclusive), got {quality}"
                )
        if not options.get("clip") or not options.get("fullPage"):
            raise ValueError("options.clip and options.fullPage are exclusive")
        if options.get("clip"):
            clip = options.get("clip")
            if not isinstance(clip.get("x"), (int, float)):
                raise ValueError(
                    f"Expected clip.x to be a int or float but found {type(clip.get('x'))}"
                )
            if not isinstance(clip.get("y"), (int, float)):
                raise ValueError(
                    f"Expected clip.y to be a int or float but found {type(clip.get('y'))}"
                )
            if not isinstance(clip.get("width"), (int, float)):
                raise ValueError(
                    f"Expected clip.width to be a int or float but found {type(clip.get('width'))}"
                )
            if not isinstance(clip.get("height"), (int, float)):
                raise ValueError(
                    f"Expected clip.height to be a int or float but found {type(clip.get('height'))}"
                )
        return await self._screenshotTask(screenshotType, options)

    async def pdf(self, options: Dict = None, **kwargs: Any) -> bytes:
        """Generate a pdf of the page.

        Options:

        * ``path`` (str): The file path to save the PDF.
        * ``scale`` (float): Scale of the webpage rendering, defaults to ``1``.
        * ``displayHeaderFooter`` (bool): Display header and footer.
          Defaults to ``False``.
        * ``headerTemplate`` (str): HTML template for the print header. Should
          be valid HTML markup with following classes.

          * ``data``: formatted print date
          * ``title``: document title
          * ``url``: document location
          * ``pageNumber``: current page number
          * ``totalPages``: total pages in the document

        * ``footerTemplate`` (str): HTML template for the print footer. Should
          use the same template as ``headerTemplate``.
        * ``printBackground`` (bool): Print background graphics. Defaults to
          ``False``.
        * ``landscape`` (bool): Paper orientation. Defaults to ``False``.
        * ``pageRanges`` (string): Paper ranges to print, e.g., '1-5,8,11-13'.
          Defaults to empty string, which means all pages.
        * ``foramt`` (str): Paper format. If set, takes prioprity over
          ``width`` or ``height``. Defaults to ``Letter``.
        * ``width`` (str): Paper width, accepts values labeled with units.
        * ``height`` (str): Paper height, accepts values labeled with units.
        * ``margin`` (dict): Paper margins, defaults to ``None``.

          * ``top`` (str): Top margin, accepts values labeled with units.
          * ``right`` (str): Right margin, accepts values labeled with units.
          * ``bottom`` (str): Bottom margin, accepts values labeled with units.
          * ``left`` (str): Left margin, accepts values labeled with units.

        :return bytes: Return generated PDF ``bytes`` object.
        """
        options = Helper.merge_dict(options, kwargs)
        scale = options.get("scale", 1)
        displayHeaderFooter = bool(options.get("displayHeaderFooter"))
        headerTemplate = options.get("headerTemplate", "")
        footerTemplate = options.get("footerTemplate", "")
        printBackground = bool(options.get("printBackground"))
        landscape = bool(options.get("landscape"))
        pageRanges = options.get("pageRanges", "")

        paperWidth = 8.5
        paperHeight = 11.0
        if "format" in options:
            fmt = Page.PaperFormats.get(options["format"].lower())
            if not fmt:
                raise ValueError("Unknown paper format: " + options["format"])
            paperWidth = fmt["width"]
            paperHeight = fmt["height"]
        else:
            paperWidth = (
                convertPrintParameterToInches(options.get("width")) or paperWidth
            )  # noqa: E501
            paperHeight = (
                convertPrintParameterToInches(options.get("height")) or paperHeight
            )  # noqa: E501

        marginOptions = options.get("margin", {})
        marginTop = (
            convertPrintParameterToInches(marginOptions.get("top")) or 0
        )  # noqa: E501
        marginLeft = (
            convertPrintParameterToInches(marginOptions.get("left")) or 0
        )  # noqa: E501
        marginBottom = (
            convertPrintParameterToInches(marginOptions.get("bottom")) or 0
        )  # noqa: E501
        marginRight = (
            convertPrintParameterToInches(marginOptions.get("right")) or 0
        )  # noqa: E501

        preferCSSPageSize = options.get("preferCSSPageSize", False)

        result = await self._client.send(
            "Page.printToPDF",
            {
                "landscape": landscape,
                "displayHeaderFooter": displayHeaderFooter,
                "headerTemplate": headerTemplate,
                "footerTemplate": footerTemplate,
                "printBackground": printBackground,
                "scale": scale,
                "paperWidth": paperWidth,
                "paperHeight": paperHeight,
                "marginTop": marginTop,
                "marginBottom": marginBottom,
                "marginLeft": marginLeft,
                "marginRight": marginRight,
                "pageRanges": pageRanges,
                "preferCSSPageSize": preferCSSPageSize,
            },
        )
        buffer = base64.b64decode(result.get("data", b""))
        if "path" in options:
            async with aiofiles.open(options["path"], "wb") as f:
                await f.write(buffer)
        return buffer

    def evaluate(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> Awaitable[Any]:
        frame = self.mainFrame
        if frame is None:
            raise Exception("No main frame.")
        return frame.evaluate(pageFunction, *args, withCliAPI=withCliAPI)

    async def evaluate_expression(
        self, expression: str, withCliAPI: bool = False
    ) -> Any:
        """Evaluates the js expression in the main frame returning the results by value.

        :param str expression: The js expression to be evaluated in the main frame.
        :param bool withCliAPI:  Determines whether Command Line API should be available during the evaluation.
        """
        frame = self.mainFrame
        if frame is None:
            raise PageError("No main frame.")
        return await frame.evaluate_expression(expression, withCliAPI=withCliAPI)

    async def close(self) -> None:
        """Close connection."""
        conn = Connection.from_session(self._client)

        if conn is None:
            raise PageError(
                "Protocol Error: Connectoin Closed. "
                "Most likely the page has been closed."
            )
        await conn.send("Target.closeTarget", {"targetId": self._target._targetId})

    async def _go(self, delta: int, options: Dict) -> Optional[Response]:
        history = await self._client.send("Page.getNavigationHistory")
        _count = history.get("currentIndex", 0) + delta
        entries = history.get("entries", [])
        if len(entries) <= _count:
            return None
        entry = entries[_count]
        response = (
            await asyncio.gather(
                self.waitForNavigation(options),
                self._client.send(
                    "Page.navigateToHistoryEntry", {"entryId": entry.get("id")}
                ),
                loop=self._loop,
            )
        )[0]
        return response

    async def _screenshotTask(
        self, format_: str, options: Dict
    ) -> bytes:  # noqa: C901,E501
        await self._client.send(
            "Target.activateTarget", {"targetId": self._target._targetId}
        )
        clip = options.get("clip")
        if clip:
            clip["scale"] = 1

        if options.get("fullPage", False):
            metrics = await self._client.send("Page.getLayoutMetrics")
            width = math.ceil(metrics["contentSize"]["width"])
            height = math.ceil(metrics["contentSize"]["height"])

            # Overwrite clip for full page at all times.
            clip = {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}
            mobile = self._viewport.get("isMobile", False)
            deviceScaleFactor = self._viewport.get("deviceScaleFactor", 1)
            landscape = self._viewport.get("isLandscape", False)
            if landscape:
                screenOrientation = {"angle": 90, "type": "landscapePrimary"}
            else:
                screenOrientation = {"angle": 0, "type": "portraitPrimary"}
            await self._client.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "mobile": mobile,
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": deviceScaleFactor,
                    "screenOrientation": screenOrientation,
                },
            )
        shouldSetDefaultBackground = options.get("omitBackground") and format_ == "png"
        if shouldSetDefaultBackground:
            await self._client.send(
                "Emulation.setDefaultBackgroundColorOverride",
                {"color": {"r": 0, "g": 0, "b": 0, "a": 0}},
            )
        opt = {"format": format_}
        if clip:
            opt["clip"] = clip
        if options.get("quality"):
            opt["quality"] = options.get("quality")
        result = await self._client.send("Page.captureScreenshot", opt)

        if shouldSetDefaultBackground:
            await self._client.send("Emulation.setDefaultBackgroundColorOverride")

        if options.get("fullPage"):
            await self.setViewport(self._viewport)
        if result.get("encoding") == "base64":
            buffer = base64.b64decode(result.get("data", b""))
        else:
            buffer = result.get("data")
        if "path" in options:
            async with aiofiles.open(options["path"], "wb") as f:
                await f.write(buffer)
        return buffer

    async def _rawScreenshotTask(
        self, format_: str, options: Dict
    ) -> bytes:  # noqa: C901,E501
        await self._client.send(
            "Target.activateTarget", {"targetId": self._target._targetId}
        )
        clip = options.get("clip")
        if clip:
            clip["scale"] = 1

        if options.get("fullPage"):
            metrics = await self._client.send("Page.getLayoutMetrics")
            width = math.ceil(metrics["contentSize"]["width"])
            height = math.ceil(metrics["contentSize"]["height"])

            # Overwrite clip for full page at all times.
            clip = {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}
            mobile = self._viewport.get("isMobile", False)
            deviceScaleFactor = self._viewport.get("deviceScaleFactor", 1)
            landscape = self._viewport.get("isLandscape", False)
            if landscape:
                screenOrientation = {"angle": 90, "type": "landscapePrimary"}
            else:
                screenOrientation = {"angle": 0, "type": "portraitPrimary"}
            await self._client.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "mobile": mobile,
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": deviceScaleFactor,
                    "screenOrientation": screenOrientation,
                },
            )

        if options.get("omitBackground"):
            await self._client.send(
                "Emulation.setDefaultBackgroundColorOverride",
                {"color": {"r": 0, "g": 0, "b": 0, "a": 0}},
            )
        opt = {"format": format_}
        if clip:
            opt["clip"] = clip
        result: Dict[str, bytes] = await self._client.send(
            "Page.captureScreenshot", opt
        )

        if options.get("omitBackground"):
            await self._client.send("Emulation.setDefaultBackgroundColorOverride")

        if options.get("fullPage"):
            await self.setViewport(self._viewport)
        return result.get("data", b"")

    def _onTargetCrashed(self, *args: Any, **kwargs: Any) -> None:
        self.emit(Events.Page.Crashed, PageError("Page crashed!"))

    def _check_worker(self, event: CDPEvent) -> None:
        tinfo = event.get("targetInfo")
        if tinfo is not None:
            type_ = tinfo["type"]
            if type_ != "worker":
                self._loop.create_task(
                    self._client.send(
                        "Target.detachFromTarget", {"sessionId": event.get("sessionId")}
                    )
                )

    def _onLogEntryAdded(self, entry: LogEntry) -> None:
        self.emit(Events.Page.LogEntry, entry)

    def _on_lifecycle(self, le: Callable) -> None:
        self.emit(Events.Page.LifecycleEvent, le)

    def _emitMetrics(self, event: CDPEvent) -> None:
        self.emit(
            Events.Page.Metrics,
            {
                "title": event["title"],
                "metrics": self._buildMetricsObject(event["metrics"]),
            },
        )

    def _buildMetricsObject(self, metrics: List) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for metric in metrics or []:
            if metric["name"] in supportedMetrics:
                result[metric["name"]] = metric["value"]
        return result

    def _handleException(self, exceptionDetails: Dict) -> None:
        message = Helper.getExceptionMessage(exceptionDetails)
        self.emit(Events.Page.PageError, PageError(message))

    def _onConsoleAPI(self, event: CDPEvent) -> None:
        context = self._frameManager.executionContextById(
            event.get("executionContextId")
        )
        if not self.listeners(Events.Page.Console):
            create_task = self._loop.create_task
            for arg in event.get("args", []):
                create_task(createJSHandle(context, arg).dispose())
            return
        self.emit(Events.Page.Console, ConsoleMessage(event, context=context))

    def _onDialog(self, event: CDPEvent) -> None:
        self.emit(Events.Page.Dialog, Dialog(self._client, event))

    def _onDomContentEventFired(self, event: CDPEvent) -> None:
        self.emit(Events.Page.DOMContentLoaded)

    def _onLoadEventFired(self, event: CDPEvent) -> None:
        self.emit(Events.Page.Load)

    def _onExceptionThrown(self, event: CDPEvent) -> None:
        self._handleException(event.get("exceptionDetails"))

    #: alias to :meth:`querySelector`
    J = querySelector
    #: alias to :meth:`querySelectorEval`
    Jeval = querySelectorEval
    #: alias to :meth:`querySelectorAll`
    JJ = querySelectorAll
    #: alias to :meth:`querySelectorAllEval`
    JJeval = querySelectorAllEval
    #: alias to :meth:`xpath`
    Jx = xpath


supportedMetrics = (
    "Timestamp",
    "Documents",
    "Frames",
    "JSEventListeners",
    "Nodes",
    "LayoutCount",
    "RecalcStyleCount",
    "LayoutDuration",
    "RecalcStyleDuration",
    "ScriptDuration",
    "TaskDuration",
    "JSHeapUsedSize",
    "JSHeapTotalSize",
)


unitToPixels = {"px": 1, "in": 96, "cm": 37.8, "mm": 3.78}


def convertPrintParameterToInches(
    parameter: Optional[Union[Number, str]]
) -> Optional[float]:
    """Convert print parameter to inches."""
    if parameter is None:
        return None
    if isinstance(parameter, (int, float)):
        pixels = parameter
    elif isinstance(parameter, str):
        text = parameter
        unit = text[-2:].lower()
        if unit in unitToPixels:
            valueText = text[:-2]
        else:
            unit = "px"
            valueText = text
        try:
            value = float(valueText)
        except ValueError:
            raise ValueError("Failed to parse parameter value: " + text)
        pixels = value * unitToPixels[unit]
    else:
        raise TypeError(
            "page.pdf() Cannot handle parameter type: " + str(type(parameter))
        )
    return pixels / 96
