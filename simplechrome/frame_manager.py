"""Frame Manager module."""

import asyncio
import logging
from asyncio import Future, AbstractEventLoop
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Union, Set, TYPE_CHECKING, ClassVar

import attr
from async_timeout import timeout as aiotimeout
import aiofiles
from pyee import EventEmitter

from .connection import ClientType
from .errors import ElementHandleError, PageError, WaitSetupError
from .errors import NavigationError
from .execution_context import ElementHandle
from .execution_context import ExecutionContext, JSHandle
from .helper import Helper
from .waitTask import WaitTask
from .lifecycle_watcher import LifecycleWatcher
from .util import merge_dict, ensure_loop

if TYPE_CHECKING:
    from .page import Page  # noqa: F401
    from .network_manager import NetworkManager, Response  # noqa: F401

__all__ = ["FrameManager", "Frame"]

logger = logging.getLogger(__name__)


@attr.dataclass(slots=True, frozen=True)
class FrameManagerEvents(object):
    FrameAttached: str = attr.ib(default="frameattached", init=False)
    FrameNavigated: str = attr.ib(default="framenavigated", init=False)
    FrameDetached: str = attr.ib(default="framedetached", init=False)
    LifecycleEvent: str = attr.ib(default="lifecycleevent", init=False)
    FrameNavigatedWithinDocument: str = attr.ib(
        default="framenavigatedwithindocument", init=False
    )
    ExecutionContextCreated: str = attr.ib(
        default="executioncontextcreated", init=False
    )
    ExecutionContextDestroyed: str = attr.ib(
        default="executioncontextdestroyed", init=False
    )


class FrameManager(EventEmitter):
    """FrameManager class."""

    Events: ClassVar[FrameManagerEvents] = FrameManagerEvents()

    def __init__(
        self,
        client: ClientType,
        frameTree: Dict,
        page: Optional["Page"] = None,
        networkManager: Optional["NetworkManager"] = None,
        loop: Optional[AbstractEventLoop] = None,
    ) -> None:
        """Make new frame manager."""
        super().__init__(loop=ensure_loop(loop))
        self._client: ClientType = client
        self._frames: OrderedDict[str, Frame] = OrderedDict()
        self._mainFrame: Frame = None
        self._contextIdToContext: Dict[Union[str, int], ExecutionContext] = dict()
        self._emits_life: bool = False
        self._defaultNavigationTimeout: Union[int, float] = 30
        self._page: Optional["Page"] = page
        self._networkManager: Optional["NetworkManager"] = networkManager
        self._client.on("Page.frameAttached", self._onFrameAttached)
        self._client.on("Page.frameNavigated", self._onFrameNavigated)
        self._client.on(
            "Page.navigatedWithinDocument", self._onFrameNavigatedWithinDocument
        )
        self._client.on("Page.frameDetached", self._onFrameDetached)
        self._client.on("Page.frameStoppedLoading", self._onFrameStoppedLoading)
        self._client.on(
            "Runtime.executionContextCreated", self._onExecutionContextCreated
        )
        self._client.on(
            "Runtime.executionContextDestroyed", self._onExecutionContextDestroyed
        )
        self._client.on(
            "Runtime.executionContextsCleared", self._onExecutionContextsCleared
        )
        self._client.on("Page.lifecycleEvent", self._onLifecycleEvent)

        self._handleFrameTree(frameTree, is_first=True)

    @property
    def mainFrame(self) -> "Frame":
        return self._mainFrame

    @property
    def page(self) -> "Page":
        return self._page

    async def navigateFrame(
        self, frame: "Frame", url: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> Optional["Response"]:
        opts = merge_dict(options, kwargs)
        timeout = opts.get("timeout", self._defaultNavigationTimeout)
        waitUnitl = opts.get("waitUntil", ["load"])
        all_frames = opts.get("all_frames", True)
        nav_args = dict(url=url, frameId=frame.id)

        if "transition" in opts:
            nav_args["transitionType"] = opts.get("transition")

        supplied_referrer: bool = "referrer" in opts
        if supplied_referrer:
            nav_args["referrer"] = opts.get("referrer")

        if not supplied_referrer and self._networkManager is not None:
            referer = self._networkManager.extraHTTPHeaders().get("referrer")
            if referer:
                nav_args["referrer"] = referer

        watcher = LifecycleWatcher(
            self, frame, waitUnitl, timeout, all_frames, self._loop
        )

        ensureNewDocumentNavigation = False

        async def navigate() -> Optional[NavigationError]:
            nonlocal ensureNewDocumentNavigation
            try:
                response = await self._client.send("Page.navigate", nav_args)
                # if we navigated within document i.e history modification then loaderId is None
                ensureNewDocumentNavigation = bool(response.get("loaderId"))
                errorText = response.get("errorText")
                if errorText:
                    return NavigationError(f"Navigation to {url} failed: {errorText}")
            except Exception as e:
                return NavigationError(f"Navigation to {url} failed: {e.args[0]}")
            return None

        # asyncio.wait does not work like Promise.race
        # if we were to use watcher.timeoutOrTerminationPromise and there was an error
        # done would be a task with a result that is a tuple (Task-That-Failed, future still pending)
        # requiring two result calls :(
        done, pending = await asyncio.wait(
            {
                self._loop.create_task(navigate()),
                watcher.timeoutPromise,
                watcher.terminationPromise,
            },
            return_when=asyncio.FIRST_COMPLETED,
            loop=self._loop,
        )
        error = done.pop().result()
        if error is None:
            if ensureNewDocumentNavigation:
                final_prom = watcher.newDocumentNavigationPromise
            else:
                final_prom = watcher.sameDocumentNavigationPromise
            done, pending = await asyncio.wait(
                {watcher.timeoutPromise, watcher.terminationPromise, final_prom},
                return_when=asyncio.FIRST_COMPLETED,
                loop=self._loop,
            )
            error = done.pop().result()
        watcher.dispose()
        if error is not None:
            raise error
        return watcher.navigationResponse

    async def waitForFrameNavigation(
        self, frame: "Frame", options: Optional[Dict] = None, **kwargs: Any
    ) -> Optional["Response"]:
        opts = merge_dict(options, kwargs)
        timeout = opts.get("timeout", self._defaultNavigationTimeout)
        waitUnitl = opts.get("waitUntil", ["load"])
        all_frames = opts.get("all_frames", True)
        watcher = LifecycleWatcher(
            self, frame, waitUnitl, timeout, all_frames, self._loop
        )
        done, pending = await asyncio.wait(
            {
                watcher.timeoutPromise,
                watcher.terminationPromise,
                watcher.sameDocumentNavigationPromise,
                watcher.newDocumentNavigationPromise,
            },
            return_when=asyncio.FIRST_COMPLETED,
            loop=self._loop,
        )
        watcher.dispose()
        error = done.pop().result()
        if error is not None:
            raise error
        return watcher.navigationResponse

    def setDefaultNavigationTimeout(self, timeout: Union[int, float]) -> None:
        self._defaultNavigationTimeout = timeout

    def enable_lifecycle_emitting(self) -> None:
        self._emits_life = True

    def disable_lifecycle_emitting(self) -> None:
        self._emits_life = False

    def executionContextById(
        self, contextId: Union[str, int]
    ) -> Optional[ExecutionContext]:
        return self._contextIdToContext.get(contextId)

    def frames(self) -> List["Frame"]:
        """Retrun all frames."""
        return list(self._frames.values())

    def frame(self, frameId: str) -> Optional["Frame"]:
        """Return :class:`Frame` of ``frameId``."""
        return self._frames.get(frameId)

    def _onLifecycleEvent(self, event: Dict) -> None:
        frame = self._frames.get(event["frameId"])
        if frame is None:
            return
        frame._onLifecycleEvent(event["loaderId"], event["name"])
        self.emit(FrameManager.Events.LifecycleEvent, frame)

    def _handleFrameTree(self, frameTree: Dict, is_first: bool = False) -> None:
        ft_frame = frameTree["frame"]
        frameId: str = ft_frame.get("id", "")
        parent_id = ft_frame.get("parentId", None)
        self._frames[frameId] = Frame.from_cdp_frame(
            self,
            self._client,
            self._frames.get(parent_id, None),
            ft_frame,
            loop=self._loop,
        )
        if is_first and parent_id is None:
            self._mainFrame = self._frames[frameId]
        if "childFrames" not in frameTree:
            return
        for child in frameTree["childFrames"]:
            self._handleFrameTree(child)

    def _onFrameAttached(self, eventOrFrame: Dict) -> None:
        frameId: str = eventOrFrame.get("frameId", "")
        parentFrameId: str = eventOrFrame.get("parentFrameId", "")
        if frameId in self._frames:
            return
        parentFrame = self._frames.get(parentFrameId)
        frame = Frame(self, self._client, parentFrame, frameId, loop=self._loop)
        self._frames[frameId] = frame
        self.emit(self.Events.FrameAttached, frame)

    def _onFrameNavigated(self, eventOrFrame: Dict) -> None:
        framePayload: Dict = eventOrFrame.get("frame", eventOrFrame)
        isMainFrame = framePayload.get("parentId", None) is None

        if isMainFrame:
            frame = self._mainFrame
        else:
            frame = self._frames.get(framePayload.get("id", ""))

        if not (isMainFrame or frame):
            raise PageError(
                "We either navigate top level or have old version "
                "of the navigated frame"
            )

        # Detach all child frames first.
        if frame:
            for child in frame.childFrames:
                self._removeFramesRecursively(child)

        # Update or create main frame.
        _id = framePayload.get("id", "")
        if isMainFrame:
            if frame:
                # Update frame id to retain frame identity on cross-process navigation.  # noqa: E501
                self._frames.pop(frame._id, None)
                frame._id = _id
            else:
                # Initial main frame navigation.
                frame = Frame(self, self._client, None, _id, loop=self._loop)
            self._frames[_id] = frame
            self._mainFrame = frame

        # Update frame payload.
        frame.navigated(framePayload)
        self.emit(FrameManager.Events.FrameNavigated, frame)

    def _onFrameDetached(self, event: Dict) -> None:
        frameId: str = event.get("frameId")
        frame = self._frames.get(frameId)
        if frame:
            self._removeFramesRecursively(frame)

    def _onFrameStoppedLoading(self, event: Dict) -> None:
        frameId: str = event.get("frameId")
        frame = self._frames.get(frameId)
        if frame is None:
            return
        frame._onLoadingStopped()
        self.emit(FrameManager.Events.LifecycleEvent, frame)

    def _onFrameNavigatedWithinDocument(self, event: Dict) -> None:
        frameId: str = event.get("frameId")
        url: str = event.get("url")
        frame = self._frames.get(frameId, None)
        if frame is None:
            return
        frame.navigatedWithinDocument(url)
        self.emit(FrameManager.Events.FrameNavigatedWithinDocument, frame)
        self.emit(FrameManager.Events.FrameNavigated, frame)

    def _onExecutionContextCreated(self, event: Dict) -> None:
        contextPayload = event.get("context")
        if contextPayload.get("auxData"):
            frameId = contextPayload["auxData"]["frameId"]
        else:
            frameId = None

        frame: Optional[Frame] = self._frames.get(frameId) if frameId else None
        contextID = contextPayload["id"]
        context = ExecutionContext(self._client, contextPayload, frame)
        self._contextIdToContext[contextID] = context
        if frame is not None:
            frame._addExecutionContext(context)

    def _onExecutionContextDestroyed(self, event: Dict) -> None:
        executionContextId: str = event.get("executionContextId")
        context = self._contextIdToContext.get(executionContextId)
        if not context:
            return
        del self._contextIdToContext[executionContextId]
        frame = context.frame
        if frame is not None:
            frame._removeExecutionContext(context)

    def _onExecutionContextsCleared(self, *args: Any) -> None:
        for context in self._contextIdToContext.values():
            frame = context.frame
            if frame:
                frame._removeExecutionContext(context)
        self._contextIdToContext.clear()

    def _removeFramesRecursively(self, frame: "Frame") -> None:
        for child in list(frame.childFrames):
            self._removeFramesRecursively(child)
        frame._detach()
        self._frames.pop(frame.id)
        self.emit(FrameManager.Events.FrameDetached, frame)


@attr.dataclass(slots=True, frozen=True)
class FrameEvents(object):
    LifeCycleEvent: str = attr.ib(default="lifecycleevent", init=False)
    Detached: str = attr.ib(default="detached", init=False)
    Navigated: str = attr.ib(default="navigated", init=False)


class Frame(EventEmitter):
    """Frame class.

    Frame objects can be obtained via :attr:`simplechrome.page.Page.mainFrame`.
    """

    Events: ClassVar[FrameEvents] = FrameEvents()

    def __init__(
        self,
        frameManager: FrameManager,
        client: ClientType,
        parentFrame: Optional["Frame"],
        frameId: str,
        loop: Optional[AbstractEventLoop] = None,
    ) -> None:
        super().__init__(loop=ensure_loop(loop))
        self._client: ClientType = client
        self._frameManager = frameManager
        self._parentFrame = parentFrame
        self._url: str = ""
        self._name: str = ""
        self._id: str = frameId
        self._detached: bool = False
        self._emits_life: bool = False

        self._documentPromise: Optional[ElementHandle] = None
        self._contextPromise: Optional[Future] = None
        self._executionContext: Optional[ExecutionContext] = None
        self._setDefaultContext(None)
        self._at_lifecycle: Optional[str] = None
        self._waitTasks: Set[WaitTask] = set()  # maybe list
        self._loaderId: str = ""
        self._lifecycleEvents: Set[str] = set()
        self._childFrames: Set[Frame] = set()  # maybe list
        if self._parentFrame:
            self._parentFrame._childFrames.add(self)

    @property
    def emits_lifecycle(self) -> bool:
        return self._emits_life

    @property
    def life_cycle(self) -> Set[str]:
        return self._lifecycleEvents

    @property
    def did_load(self) -> bool:
        return "load" in self._lifecycleEvents

    @property
    def dom_loaded(self) -> bool:
        return "DOMContentLoaded" in self._lifecycleEvents

    @property
    def name(self) -> str:
        """Get frame name."""
        return self._name

    @property
    def url(self) -> str:
        """Get url of the frame."""
        return self._url

    @property
    def id(self) -> str:
        return self._id

    @property
    def parentFrame(self) -> Optional["Frame"]:
        """Get parent frame.

        If this frame is main frame or detached frame, return ``None``.
        """
        return self._parentFrame

    @property
    def childFrames(self) -> List["Frame"]:
        """Get child frames."""
        return list(self._childFrames)

    @classmethod
    def from_cdp_frame(
        cls,
        frameManager: FrameManager,
        client: ClientType,
        parentFrame: Optional["Frame"],
        cdp_frame: Dict[str, str],
        loop: Optional[AbstractEventLoop] = None,
    ) -> "Frame":
        frame = cls(frameManager, client, parentFrame, cdp_frame["id"], loop=loop)
        frame._loaderId = cdp_frame.get("loaderId", "")
        frame._url = cdp_frame.get("url", "")
        return frame

    async def goto(
        self, url: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> Optional["Response"]:
        return await self._frameManager.navigateFrame(self, url, options, **kwargs)

    async def waitForNavigation(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> Optional["Response"]:
        return await self._frameManager.waitForFrameNavigation(self, options, **kwargs)

    def isDetached(self) -> bool:
        """Return ``True`` if this frame is detached.

        Otherwise return ``False``.
        """
        return self._detached

    def navigatedWithinDocument(self, url: str) -> None:
        self._url = url

    def navigated(self, framePayload: dict) -> None:
        self._name = framePayload.get("name", "")
        self._url = framePayload.get("url", "")
        if self._emits_life:
            self.emit(Frame.Events.Navigated)

    def enable_lifecycle_emitting(self) -> None:
        self._emits_life = True

    def disable_lifecycle_emitting(self) -> None:
        self._emits_life = False

    async def executionContext(self) -> Optional[ExecutionContext]:
        """Return execution context of this frame.

        Return :class:`~simplechrome.execution_context.ExecutionContext`
        associated to this frame.
        """
        return await self._contextPromise

    async def evaluateHandle(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> JSHandle:
        """Evaluates the js-function or js-expression in the current frame retrieving the results
        as a JSHandle.

        :param str pageFunction: String of js-function/expression to be executed
                               in the browser.
        :param bool withCliAPI:  Determines whether Command Line API should be available during the evaluation.
        If this keyword argument is true args are ignored
        """
        context = await self.executionContext()
        if context is None:
            raise PageError("this frame has no context.")
        return await context.evaluateHandle(pageFunction, *args, withCliAPI=withCliAPI)

    async def evaluate(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> Any:
        """Evaluates the js-function or js-expression in the current frame retrieving the results
        of the evaluation.

        :param str pageFunction: String of js-function/expression to be executed
                               in the browser.
        :param bool withCliAPI:  Determines whether Command Line API should be available during the evaluation.
        If this keyword argument is true args are ignored
        """
        context = await self.executionContext()
        if context is None:
            raise ElementHandleError("ExecutionContext is None.")
        return await context.evaluate(pageFunction, *args, withCliAPI=withCliAPI)

    async def evaluate_expression(
        self, expression: str, withCliAPI: bool = False
    ) -> Any:
        """Evaluates the js expression in the frame returning the results by value.

        :param str expression: The js expression to be evaluated in the main frame.
        :param bool withCliAPI:  Determines whether Command Line API should be available during the evaluation.
        """
        context = await self.executionContext()
        if context is None:
            raise ElementHandleError("ExecutionContext is None.")
        return await context.evaluate_expression(expression, withCliAPI=withCliAPI)

    async def querySelector(self, selector: str) -> Optional[ElementHandle]:
        """Get element which matches `selector` string.

        Details see :meth:`simplechrome.page.Page.querySelector`.
        """
        document = await self._document()
        value = await document.querySelector(selector)
        return value

    async def _document(self) -> ElementHandle:
        if self._documentPromise:
            return self._documentPromise
        context = await self.executionContext()
        if context is None:
            raise PageError("No context exists.")
        document = (await context.evaluateHandle("document")).asElement()
        self._documentPromise = document
        if document is None:
            raise PageError("Could not find `document`.")
        return document

    async def xpath(self, expression: str) -> List[ElementHandle]:
        """Evaluate XPath expression.

        If there is no such element in this frame, return None.

        :arg str expression: XPath string to be evaluated.
        """
        document = await self._document()
        value = await document.xpath(expression)
        return value

    async def querySelectorEval(
        self, selector: str, pageFunction: str, *args: Any
    ) -> Optional[Any]:
        """Execute function on element which matches selector.

        Details see :meth:`simplechrome.page.Page.querySelectorEval`.
        """
        elementHandle = await self.querySelector(selector)
        if elementHandle is None:
            raise PageError(
                f'Error: failed to find element matching selector "{selector}"'
            )
        result = await self.evaluate(pageFunction, elementHandle, *args)
        await elementHandle.dispose()
        return result

    async def querySelectorAllEval(
        self, selector: str, pageFunction: str, *args: Any
    ) -> Optional[Dict]:
        """Execute function on all elements which matches selector.

        Details see :meth:`simplechrome.page.Page.querySelectorAllEval`.
        """
        context = await self.executionContext()
        if context is None:
            raise ElementHandleError("ExecutionContext is None.")
        arrayHandle = await context.evaluateHandle(
            "selector => Array.from(document.querySelectorAll(selector))", selector
        )
        result = await self.evaluate(pageFunction, arrayHandle, *args)
        await arrayHandle.dispose()
        return result

    async def querySelectorAll(self, selector: str) -> List[ElementHandle]:
        """Get all elelments which matches `selector`.

        Details see :meth:`simplechrome.page.Page.querySelectorAll`.
        """
        document = await self._document()
        value = await document.querySelectorAll(selector)
        return value

    async def content(self) -> str:
        """Get the whole HTML contents of the page."""
        return await self.evaluate(
            """() => {
          let retVal = '';
          if (document.doctype)
            retVal = new XMLSerializer().serializeToString(document.doctype);
          if (document.documentElement)
            retVal += document.documentElement.outerHTML;
          return retVal;
        }
        """.strip()
        )

    async def setContent(
        self, html: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> None:
        """Set content to this page."""
        func = """function(html) {
          document.open();
          document.write(html);
          document.close();
        }
        """
        opts = merge_dict(options, kwargs)
        timeout = opts.get("timeout", 30000)
        waitUnitl = opts.get("waitUntil", ["load"])
        all_frames = opts.get("all_frames", True)
        await self.evaluate(func, html)
        watcher = LifecycleWatcher(
            self._frameManager, self, waitUnitl, timeout, all_frames, self._loop
        )
        done, pending = await asyncio.wait(
            {
                watcher.timeoutPromise,
                watcher.terminationPromise,
                watcher.lifecyclePromise,
            },
            return_when=asyncio.FIRST_COMPLETED,
            loop=self._loop,
        )
        watcher.dispose()
        error = done.pop().result()
        if error is not None:
            raise error

    async def injectFile(self, filePath: str) -> str:
        """[Deprecated] Inject file to the frame."""
        logger.warning(
            "`injectFile` method is deprecated." " Use `addScriptTag` method instead."
        )
        async with aiofiles.open(filePath, "r") as f:
            contents = await f.read()
        contents += "/* # sourceURL= {} */".format(filePath.replace("\n", ""))
        return await self.evaluate(contents)

    async def addScriptTag(self, options: Dict) -> ElementHandle:
        """Add script tag to this frame.

        Details see :meth:`simplechrome.page.Page.addScriptTag`.
        """
        context = await self.executionContext()
        if context is None:
            raise ElementHandleError("ExecutionContext is None.")

        addScriptUrl = """async function addScriptUrl(url, type) {
            const script = document.createElement('script');
            script.src = url;
            if (type) {
              script.type = type;
            }
            const promise = new Promise((res, rej) => {
                script.onload = res;
                script.onerror = rej;
            });
            document.head.appendChild(script);
            await promise;
            return script;
        }"""

        addScriptContent = """function addScriptContent(content, type = 'text/javascript') {
            const script = document.createElement('script');
            script.type = type;
            script.text = content;
            let error = null;
            script.onerror = e => error = e;
            document.head.appendChild(script);
            if (error) {
              throw error;
            }
            return script;
        }"""

        if isinstance(options.get("url"), str):
            url = options["url"]
            try:
                return (await context.evaluateHandle(addScriptUrl, url)).asElement()
            except ElementHandleError as e:
                raise PageError(f"Loading script from {url} failed") from e

        if isinstance(options.get("path"), str):
            async with aiofiles.open(options["path"], "r") as f:
                contents = await f.read()
            contents = contents + "//# sourceURL={}".format(
                options["path"].replace("\n", "")
            )
            if options.get("type") is not None:
                result = await context.evaluateHandle(
                    addScriptContent, contents, options.get("type")
                )
            else:
                result = await context.evaluateHandle(addScriptContent, contents)
            return result.asElement()

        if isinstance(options.get("content"), str):
            if options.get("type") is not None:
                result = await context.evaluateHandle(
                    addScriptContent, options["content"], options.get("type")
                )
            else:
                result = await context.evaluateHandle(
                    addScriptContent, options["content"]
                )
            return result.asElement()

        raise ValueError("Provide an object with a `url`, `path` or `content` property")

    async def addStyleTag(self, options: Dict) -> ElementHandle:
        """Add style tag to this frame.

        Details see :meth:`simplechrome.page.Page.addStyleTag`.
        """
        context = await self.executionContext()
        if context is None:
            raise ElementHandleError("ExecutionContext is None.")

        addStyleUrl = """async function (url) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = url;
            document.head.appendChild(link);
            await new Promise((res, rej) => {
                link.onload = res;
                link.onerror = rej;
            });
            return link;
        }"""

        addStyleContent = """function (content) {
            const style = document.createElement('style');
            style.type = 'text/css';
            style.appendChild(document.createTextNode(content));
            document.head.appendChild(style);
            return style;
        }"""

        if isinstance(options.get("url"), str):
            url = options["url"]
            try:
                return (await context.evaluateHandle(addStyleUrl, url)).asElement()
            except ElementHandleError as e:
                raise PageError(f"Loading style from {url} failed") from e

        if isinstance(options.get("path"), str):
            with open(options["path"]) as f:
                contents = f.read()
            contents = contents + "/*# sourceURL={}*/".format(
                options["path"].replace("\n", "")
            )
            return (await context.evaluateHandle(addStyleContent, contents)).asElement()

        if isinstance(options.get("content"), str):
            return (
                await context.evaluateHandle(addStyleContent, options["content"])
            ).asElement()

        raise ValueError("Provide an object with a `url`, `path` or `content` property")

    async def click(self, selector: str, options: dict = None, **kwargs: Any) -> None:
        """Click element which matches ``selector``.

        Details see :meth:`simplechrome.page.Page.click`.
        """
        options = merge_dict(options, kwargs)
        handle = await self.J(selector)
        if not handle:
            raise PageError("No node found for selector: " + selector)
        await handle.click(options)
        await handle.dispose()

    async def focus(self, selector: str) -> None:
        """Fucus element which matches ``selector``.

        Details see :meth:`simplechrome.page.Page.focus`.
        """
        handle = await self.J(selector)
        if not handle:
            raise PageError("No node found for selector: " + selector)
        await self.evaluate("element => element.focus()", handle)
        await handle.dispose()

    async def hover(self, selector: str) -> None:
        """Mouse hover the element which matches ``selector``.

        Details see :meth:`simplechrome.page.Page.hover`.
        """
        handle = await self.J(selector)
        if not handle:
            raise PageError("No node found for selector: " + selector)
        await handle.hover()
        await handle.dispose()

    async def select(self, selector: str, *values: str) -> List[str]:
        """Select options and return selected values.

        Details see :meth:`simplechrome.page.Page.select`.
        """
        for value in values:
            if not isinstance(value, str):
                raise TypeError(
                    "Values must be string. " f"Found {value} of type {type(value)}"
                )
        return await self.querySelectorEval(
            selector,
            """(element, values) => {
    if (element.nodeName.toLowerCase() !== 'select')
        throw new Error('Element is not a <select> element.');

    const options = Array.from(element.options);
    element.value = undefined;
    for (const option of options) {
        option.selected = values.includes(option.value);
        if (option.selected && !element.multiple)
            break;
    }

    element.dispatchEvent(new Event('input', { 'bubbles': true }));
    element.dispatchEvent(new Event('change', { 'bubbles': true }));
    return options.filter(option => option.selected).map(options => options.value)
}
        """,
            values,
        )  # noqa: E501

    async def tap(self, selector: str) -> None:
        """Tap the element which matches the ``selector``.

        Details see :meth:`simplechrome.page.Page.tap`.
        """
        handle = await self.J(selector)
        if not handle:
            raise PageError("No node found for selector: " + selector)
        await handle.tap()
        await handle.dispose()

    async def type(
        self, selector: str, text: str, options: dict = None, **kwargs: Any
    ) -> None:
        """Type ``text`` on the element which matches ``selector``.

        Details see :meth:`simplechrome.page.Page.type`.
        """
        options = merge_dict(options, kwargs)
        handle = await self.querySelector(selector)
        if handle is None:
            raise PageError("Cannot find {} on this page".format(selector))
        await handle.type(text, options)
        await handle.dispose()

    def waitFor(
        self,
        selectorOrFunctionOrTimeout: Union[str, int, float],
        options: dict = None,
        *args: Any,
        **kwargs: Any,
    ) -> Union[Future, "WaitTask"]:
        """Wait until `selectorOrFunctionOrTimeout`.

        Details see :meth:`simplechrome.page.Page.waitFor`.
        """
        options = merge_dict(options, kwargs)
        if isinstance(selectorOrFunctionOrTimeout, (int, float)):
            fut = self._loop.create_task(
                asyncio.sleep(selectorOrFunctionOrTimeout / 1000)
            )
            return fut
        if not isinstance(selectorOrFunctionOrTimeout, str):
            fut = self._loop.create_future()
            fut.set_exception(
                TypeError(
                    "Unsupported target type: " + str(type(selectorOrFunctionOrTimeout))
                )
            )
            return fut

        if args or Helper.is_jsfunc(selectorOrFunctionOrTimeout):
            return self.waitForFunction(selectorOrFunctionOrTimeout, options, *args)
        if selectorOrFunctionOrTimeout.startswith("//"):
            return self.waitForXPath(selectorOrFunctionOrTimeout, options)
        return self.waitForSelector(selectorOrFunctionOrTimeout, options)

    def waitForSelector(
        self, selector: str, options: dict = None, **kwargs: Any
    ) -> "WaitTask":
        """Wait until element which matches ``selector`` appears on page.

        Details see :meth:`simplechrome.page.Page.waitForSelector`.
        """
        options = merge_dict(options, kwargs)
        return self._waitForSelectorOrXPath(selector, False, options)

    def waitForXPath(
        self, xpath: str, options: dict = None, **kwargs: Any
    ) -> "WaitTask":
        """Wait until element which matches ``xpath`` appears on page.

        Details see :meth:`simplechrome.page.Page.waitForXPath`.
        """
        options = merge_dict(options, kwargs)
        return self._waitForSelectorOrXPath(xpath, True, options)

    def waitForFunction(
        self, pageFunction: str, options: dict = None, *args: Any, **kwargs: Any
    ) -> "WaitTask":
        """Wait until the function completes.

        Details see :meth:`simplechrome.page.Page.waitForFunction`.
        """
        options = merge_dict(options, kwargs)
        timeout = options.get("timeout", 30000)  # msec
        polling = options.get("polling", "raf")
        return WaitTask(self, pageFunction, polling, timeout, *args)

    def _waitForSelectorOrXPath(
        self, selectorOrXPath: str, isXPath: bool, options: dict = None, **kwargs: Any
    ) -> "WaitTask":
        options = merge_dict(options, kwargs)
        timeout = options.get("timeout", 30000)
        waitForVisible = bool(options.get("visible"))
        waitForHidden = bool(options.get("hidden"))
        polling = "raf" if waitForHidden or waitForVisible else "mutation"
        predicate = """
(selectorOrXPath, isXPath, waitForVisible, waitForHidden) => {
    const node = isXPath
        ? document.evaluate(selectorOrXPath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue
        : document.querySelector(selectorOrXPath);
    if (!node)
        return waitForHidden;
    if (!waitForVisible && !waitForHidden)
        return node;
    const element = /** @type {Element} */ (node.nodeType === Node.TEXT_NODE ? node.parentElement : node);

    const style = window.getComputedStyle(element);
    const isVisible = style && style.visibility !== 'hidden' && hasVisibleBoundingBox();
    const success = (waitForVisible === isVisible || waitForHidden === !isVisible)
    return success ? node : null

    function hasVisibleBoundingBox() {
        const rect = element.getBoundingClientRect();
        return !!(rect.top || rect.bottom || rect.width || rect.height);
    }
}
        """  # noqa: E501
        return self.waitForFunction(
            predicate,
            {"timeout": timeout, "polling": polling},
            selectorOrXPath,
            isXPath,
            waitForVisible,
            waitForHidden,
        )

    async def title(self) -> str:
        """Get title of the frame."""
        return await self.evaluate("() => document.title")

    def navigation_waiter(
        self,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        timeout: Optional[Union[int, float]] = None,
    ) -> Future:
        if not self._emits_life:
            raise WaitSetupError("Must enable life cycle emitting")
        if loop is None:
            loop = asyncio.get_event_loop()
        fut = loop.create_future()

        def set_true() -> None:
            if not fut.done():
                fut.set_result(True)

        listeners = [Helper.addEventListener(self, Frame.Events.Navigated, set_true)]

        fut.add_done_callback(lambda f: Helper.removeEventListeners(listeners))
        if timeout is not None:
            return self._loop.create_task(Helper.timed_wait(fut, timeout, loop))
        return fut

    async def _wait_for_life_cycle(
        self,
        cycle: str,
        loop: AbstractEventLoop,
        timeout: Optional[Union[int, float]] = None,
    ) -> None:
        fut: Future = loop.create_future()

        def on_life_cycle(lc: str) -> None:
            if lc == cycle and not fut.done():
                fut.set_result(True)

        listeners = [
            Helper.addEventListener(self, Frame.Events.LifeCycleEvent, on_life_cycle)
        ]

        fut.add_done_callback(lambda f: Helper.removeEventListeners(listeners))

        if timeout is not None:
            try:
                async with aiotimeout(timeout, loop=loop):
                    await fut
            except asyncio.TimeoutError:
                pass
        else:
            await fut

    def loaded_waiter(
        self,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        timeout: Optional[int] = None,
    ) -> Future:
        if not self._emits_life:
            raise WaitSetupError("Must enable life cycle emitting")
        return self._loop.create_task(
            self._wait_for_life_cycle("load", ensure_loop(loop), timeout)
        )

    def network_idle_waiter(
        self,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        timeout: Optional[int] = None,
    ) -> Future:
        if not self._emits_life:
            raise WaitSetupError("Must enable life cycle emitting")
        return self._loop.create_task(
            self._wait_for_life_cycle("networkIdle", ensure_loop(loop), timeout)
        )

    #: Alias to :meth:`querySelector`
    J = querySelector
    #: Alias to :meth:`xpath`
    Jx = xpath
    #: Alias to :meth:`querySelectorEval`
    Jeval = querySelectorEval
    #: Alias to :meth:`querySelectorAll`
    JJ = querySelectorAll
    #: Alias to :meth:`querySelectorAllEval`
    JJeval = querySelectorAllEval

    def _onLoadingStopped(self) -> None:
        self._lifecycleEvents.add("DOMContentLoaded")
        self._lifecycleEvents.add("load")

    def _onLifecycleEvent(self, loaderId: str, name: str) -> None:
        if name == "init":
            self._loaderId = loaderId
            self._lifecycleEvents.clear()
            self._at_lifecycle = "init"
        else:
            self._lifecycleEvents.add(name)
            self._at_lifecycle = name
        if self._emits_life:
            self.emit(Frame.Events.LifeCycleEvent, name)

    def _detach(self) -> None:
        if self._emits_life:
            self.emit(Frame.Events.Detached)
        self.remove_all_listeners(Frame.Events.Detached)
        for waitTask in list(self._waitTasks):
            waitTask.terminate(PageError("waitForFunction failed: frame got detached."))
        self._detached = True
        if self._parentFrame:
            self._parentFrame._childFrames.remove(self)
        self._parentFrame = None
        self.remove_all_listeners(Frame.Events.LifeCycleEvent)

    def _setDefaultContext(self, context: Optional[ExecutionContext] = None) -> None:
        if context:
            self._contextResolveCallback(context)
            for waitTask in self._waitTasks:
                self._loop.create_task(waitTask.rerun())
        else:
            self._documentPromise = None
            self._executionContext = None
            self._contextPromise = self._loop.create_future()

    def _contextResolveCallback(self, context: ExecutionContext) -> None:
        if self._contextPromise.done():
            self._contextPromise = self._loop.create_future()
        self._contextPromise.set_result(context)
        self._executionContext = context

    def _addExecutionContext(self, context: ExecutionContext) -> None:
        if context.default:
            self._setDefaultContext(context)

    def _removeExecutionContext(self, context: ExecutionContext) -> None:
        if context.default:
            self._setDefaultContext(None)

    def __str__(self) -> str:
        return f"Frame(url={self._url}, name={self._name}, detached={self._detached}, id={self._id})"

    def __repr__(self) -> str:
        return self.__str__()
