"""Frame Manager module."""

import logging
from asyncio import Future, gather, sleep
from collections import OrderedDict
from sys import exc_info as sys_exc_info
from typing import Any, Awaitable, Dict, List, Optional, Set, TYPE_CHECKING, Union

from pyee2 import EventEmitterS

from ._typings import (
    AsyncAny,
    CDPEvent,
    Loop,
    Number,
    OptionalLoop,
    OptionalNumber,
    SlotsT,
)
from .connection import ClientType
from .domWorld import DOMWorld
from .errors import NavigationError, WaitSetupError
from .events import Events
from .execution_context import EVALUATION_SCRIPT_URL, ExecutionContext
from .helper import Helper
from .jsHandle import ElementHandle, JSHandle
from .lifecycle_watcher import LifecycleWatcher
from .timeoutSettings import TimeoutSettings

if TYPE_CHECKING:
    from .page import Page  # noqa: F401
    from .network import NetworkManager, Response  # noqa: F401

__all__ = ["FrameManager", "Frame"]

logger = logging.getLogger(__name__)

UTILITY_WORLD_NAME: str = "__simplechrome_utility_world__"


class FrameManager(EventEmitterS):
    """FrameManager class."""

    __slots__: SlotsT = [
        "__weakref__",
        "_client",
        "_contextIdToContext",
        "_emits_life",
        "_frames",
        "_isolatedWorlds",
        "_isolateWorlds",
        "_mainFrame",
        "_networkManager",
        "_networkManager",
        "_page",
        "_timeoutSettings",
    ]

    def __init__(
        self,
        client: ClientType,
        timeoutSettings: Optional[TimeoutSettings] = None,
        page: Optional["Page"] = None,
        networkManager: Optional["NetworkManager"] = None,
        isolateWorlds: bool = True,
        loop: OptionalLoop = None,
        frameTree: Optional[Dict] = None,
    ) -> None:
        """Make new frame manager."""
        super().__init__(loop=Helper.ensure_loop(loop))
        self._client: ClientType = client
        self._page: Optional["Page"] = page
        self._networkManager: Optional["NetworkManager"] = networkManager
        self._timeoutSettings: TimeoutSettings = timeoutSettings if timeoutSettings is not None else TimeoutSettings()

        self._frames: OrderedDict[str, Frame] = OrderedDict()
        self._contextIdToContext: Dict[Union[str, int], ExecutionContext] = {}

        self._isolateWorlds: bool = isolateWorlds
        self._isolatedWorlds: Set[str] = set()

        self._mainFrame: Optional[Frame] = None
        self._emits_life: bool = False

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
        if frameTree is not None:
            self._handleFrameTree(frameTree, True)

    @property
    def isolatingWorlds(self) -> bool:
        return self._isolateWorlds

    @property
    def mainFrame(self) -> "Frame":
        return self._mainFrame

    @property
    def page(self) -> Optional["Page"]:
        return self._page

    def network_idle_promise(
        self, num_inflight: int = 2, idle_time: int = 2, global_wait: int = 60
    ) -> Awaitable[None]:
        return self._networkManager.network_idle_promise(
            num_inflight=num_inflight, idle_time=idle_time, global_wait=global_wait
        )

    def setDefaultNavigationTimeout(self, timeout: Number) -> None:
        self._timeoutSettings.setDefaultNavigationTimeout(timeout)

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

    async def initialize(self) -> None:
        _, frameTree = await gather(
            self._client.send("Page.enable", {}),
            self._client.send("Page.getFrameTree", {}),
        )
        self._handleFrameTree(frameTree["frameTree"], is_first=True)
        await gather(
            self._client.send("Page.setLifecycleEventsEnabled", {"enabled": True}),
            self._client.send("Runtime.enable", {}),
        )
        if self._isolateWorlds:
            await self._ensureIsolatedWorld(UTILITY_WORLD_NAME)

    async def captureSnapshot(self, format_: str = "mhtml") -> str:
        result = await self._client.send("Page.captureSnapshot", {"format": format_})
        return result.get("data")

    async def navigateFrame(
        self, frame: "Frame", url: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> Optional["Response"]:
        opts = Helper.merge_dict(options, kwargs)
        timeout = opts.get("timeout", self._timeoutSettings.navigationTimeout)
        waitUnitl = opts.get("waitUntil", ["load"])
        all_frames = opts.get("all_frames", True)
        nav_args = {"url": url, "frameId": frame.id}

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

        ensureNewDocumentNavigation = {"ensure": False}

        # asyncio.wait does not work like Promise.race
        # if we were to use watcher.timeoutOrTerminationPromise and there was an error
        # done would be a task with a result that is a tuple (Task-That-Failed, future still pending)
        # requiring two result calls :(
        done, pending = await Helper.wait_for_first_done(
            self.__navigate(ensureNewDocumentNavigation, nav_args, url, watcher),
            watcher.timeoutPromise,
            watcher.terminationPromise,
            loop=self._loop,
        )
        error = done.pop().result()
        if error is None:
            if ensureNewDocumentNavigation["ensure"]:
                final_prom = watcher.newDocumentNavigationPromise
            else:
                final_prom = watcher.sameDocumentNavigationPromise

            done, pending = await Helper.wait_for_first_done(
                watcher.timeoutPromise,
                watcher.terminationPromise,
                final_prom,
                loop=self._loop,
            )
            error = done.pop().result()
        watcher.dispose()
        if error is not None:
            raise error
        return watcher.navigationResponse

    async def __navigate(
        self, ensureNewDocumentNavigation: Dict[str, bool], nav_args, url, watcher
    ) -> Optional[NavigationError]:
        try:
            response = await self._client.send("Page.navigate", nav_args)
            # if we navigated within document i.e history modification then loaderId is None
            ensureNewDocumentNavigation["ensure"] = bool(response.get("loaderId"))
            errorText = response.get("errorText")
            if errorText:
                return NavigationError.Failed(
                    f"Navigation to {url} failed: {errorText}",
                    response=watcher.navigationResponse,
                )
        except Exception as e:
            return NavigationError.Failed(
                f"Navigation to {url} failed: {e.args[0]}",
                response=watcher.navigationResponse,
                tb=sys_exc_info()[2],
            )
        return None

    async def waitForFrameNavigation(
        self, frame: "Frame", options: Optional[Dict] = None, **kwargs: Any
    ) -> Optional["Response"]:
        opts = Helper.merge_dict(options, kwargs)
        timeout = opts.get("timeout", self._timeoutSettings.navigationTimeout)
        waitUnitl = opts.get("waitUntil", ["load"])
        all_frames = opts.get("all_frames", True)
        watcher = LifecycleWatcher(
            self, frame, waitUnitl, timeout, all_frames, self._loop
        )
        done, pending = await Helper.wait_for_first_done(
            watcher.timeoutPromise,
            watcher.terminationPromise,
            watcher.sameDocumentNavigationPromise,
            watcher.newDocumentNavigationPromise,
            loop=self._loop,
        )
        watcher.dispose()
        error = done.pop().result()
        if error is not None:
            raise error
        return watcher.navigationResponse

    async def ensureSecondaryDOMWorld(self) -> None:
        await self._ensureIsolatedWorld(UTILITY_WORLD_NAME)

    def _onLifecycleEvent(self, event: CDPEvent) -> None:
        frame = self._frames.get(event["frameId"])
        if frame is None:
            return
        frame._onLifecycleEvent(event["loaderId"], event["name"])
        self.emit(Events.FrameManager.LifecycleEvent, frame)

    def _handleFrameTree(self, frameTree: Dict, is_first: bool = False) -> None:
        self._frames.clear()
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
        handleFrameTree = self._handleFrameTree
        for child in frameTree["childFrames"]:
            handleFrameTree(child)

    def _onFrameAttached(self, eventOrFrame: Dict) -> None:
        frameId: str = eventOrFrame.get("frameId", "")
        parentFrameId: str = eventOrFrame.get("parentFrameId", "")
        if frameId in self._frames:
            return
        parentFrame = self._frames.get(parentFrameId)
        frame = Frame(self, self._client, parentFrame, frameId, loop=self._loop)
        self._frames[frameId] = frame
        self.emit(Events.FrameManager.FrameAttached, frame)

    def _onFrameNavigated(self, eventOrFrame: Dict) -> None:
        framePayload: Dict = eventOrFrame.get("frame", eventOrFrame)
        isMainFrame = framePayload.get("parentId", None) is None

        if isMainFrame:
            frame = self._mainFrame
        else:
            frame = self._frames.get(framePayload.get("id", ""))

        if not (isMainFrame or frame):
            raise Exception(
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
        frame._navigated(framePayload)
        self.emit(Events.FrameManager.FrameNavigated, frame)

    def _onFrameDetached(self, event: CDPEvent) -> None:
        frameId: str = event.get("frameId")
        frame = self._frames.get(frameId)
        if frame:
            self._removeFramesRecursively(frame)

    def _onFrameStoppedLoading(self, event: CDPEvent) -> None:
        frameId: str = event.get("frameId")
        frame = self._frames.get(frameId)
        if frame is None:
            return
        frame._onLoadingStopped()
        self.emit(Events.FrameManager.LifecycleEvent, frame)

    def _onFrameNavigatedWithinDocument(self, event: CDPEvent) -> None:
        frameId: str = event.get("frameId")
        url: str = event.get("url")
        frame = self._frames.get(frameId, None)
        if frame is None:
            return
        frame._navigatedWithinDocument(url)
        self.emit(Events.FrameManager.FrameNavigatedWithinDocument, frame)
        self.emit(Events.FrameManager.FrameNavigated, frame)

    def _onExecutionContextCreated(self, event: CDPEvent) -> None:
        contextPayload = event.get("context")
        auxData = contextPayload.get("auxData")
        if auxData:
            frameId = auxData["frameId"]
        else:
            frameId = None
        frame: Optional[Frame] = self._frames.get(frameId) if frameId else None
        world: Optional[DOMWorld] = None
        if frame:
            if auxData and auxData.get("isDefault", False):
                world = frame._mainWorld
            elif (
                contextPayload.get("name") == UTILITY_WORLD_NAME
                and not frame._secondaryWorld._hasContext()
            ):
                world = frame._secondaryWorld

        if auxData and auxData.get("type") == "isolated":
            self._isolatedWorlds.add(contextPayload.get("name"))

        context = ExecutionContext(self._client, contextPayload, world)
        if world:
            world._setContext(context)
        self._contextIdToContext[contextPayload.get("id")] = context

    def _onExecutionContextDestroyed(self, event: CDPEvent) -> None:
        executionContextId: str = event.get("executionContextId")
        context = self._contextIdToContext.get(executionContextId)
        if not context:
            return
        del self._contextIdToContext[executionContextId]
        if context._world:
            context._world._setContext(None)

    def _onExecutionContextsCleared(self, *args: Any) -> None:
        for context in self._contextIdToContext.values():
            if context._world:
                context._world._setContext(None)
        self._contextIdToContext.clear()

    def _removeFramesRecursively(self, frame: "Frame") -> None:
        removeFramesRecursively = self._removeFramesRecursively
        for child in frame.childFrames:
            removeFramesRecursively(child)
        frame._detach()
        self._frames.pop(frame.id, None)
        self.emit(Events.FrameManager.FrameDetached, frame)

    async def _ensureIsolatedWorld(self, name: str) -> None:
        self._isolatedWorlds.add(name)
        await self._client.send(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": f"//# sourceURL=${EVALUATION_SCRIPT_URL}", "worldName": name},
        )
        coroutines: List = []
        coroutines_append = coroutines.append
        client_send = self._client.send
        for frame in self.frames():
            coroutines_append(
                client_send(
                    "Page.createIsolatedWorld",
                    {
                        "frameId": frame.id,
                        "grantUniveralAccess": True,
                        "woldName": name,
                    },
                )
            )
        await gather(*coroutines, return_exceptions=True, loop=self._loop)


class Frame(EventEmitterS):
    """Frame class.

    Frame objects can be obtained via :attr:`simplechrome.page.Page.mainFrame`.
    """

    __slots__: SlotsT = [
        "__weakref__",
        "_at_lifecycle",
        "_childFrames",
        "_client",
        "_detached",
        "_emits_life",
        "_frameManager",
        "_id",
        "_lifecycleEvents",
        "_loaderId",
        "_mainWorld",
        "_name",
        "_parentFrame",
        "_secondaryWorld",
        "_url",
    ]

    @classmethod
    def from_cdp_frame(
        cls,
        frameManager: FrameManager,
        client: ClientType,
        parentFrame: Optional["Frame"],
        cdp_frame: Dict[str, str],
        loop: OptionalLoop = None,
    ) -> "Frame":
        frame = cls(frameManager, client, parentFrame, cdp_frame["id"], loop=loop)
        frame._loaderId = cdp_frame.get("loaderId", "")
        frame._url = cdp_frame.get("url", "")
        return frame

    def __init__(
        self,
        frameManager: FrameManager,
        client: ClientType,
        parentFrame: Optional["Frame"],
        frameId: str,
        loop: OptionalLoop = None,
    ) -> None:
        super().__init__(loop=Helper.ensure_loop(loop))
        self._client: ClientType = client
        self._frameManager: FrameManager = frameManager
        self._parentFrame: Optional[Frame] = parentFrame
        self._id: str = frameId
        self._url: str = ""
        self._name: str = ""
        self._loaderId: str = ""
        self._detached: bool = False
        self._emits_life: bool = False
        self._mainWorld: DOMWorld = DOMWorld(
            frameManager, self, frameManager._timeoutSettings, self._loop
        )
        self._secondaryWorld: DOMWorld = DOMWorld(
            frameManager, self, frameManager._timeoutSettings, self._loop
        )
        self._lifecycleEvents: Set[str] = set()
        self._childFrames: Set[Frame] = set()  # maybe list
        self._at_lifecycle: Optional[str] = None
        if self._parentFrame:
            self._parentFrame._childFrames.add(self)

    @property
    def domWorld(self) -> DOMWorld:
        if self._frameManager._isolateWorlds:
            return self._secondaryWorld
        return self._mainWorld

    @property
    def mainDOMWorld(self) -> DOMWorld:
        return self._mainWorld

    @property
    def secondaryDOMWorld(self) -> DOMWorld:
        return self._secondaryWorld

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

    def enable_lifecycle_emitting(self) -> None:
        self._emits_life = True

    def disable_lifecycle_emitting(self) -> None:
        self._emits_life = False

    def isDetached(self) -> bool:
        """Return ``True`` if this frame is detached.

        Otherwise return ``False``.
        """
        return self._detached

    def goto(
        self, url: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> Awaitable[Optional["Response"]]:
        return self._frameManager.navigateFrame(self, url, options, **kwargs)

    def waitForNavigation(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> Awaitable[Optional["Response"]]:
        return self._frameManager.waitForFrameNavigation(self, options, **kwargs)

    def executionContext(self) -> Awaitable[ExecutionContext]:
        return self._mainWorld.executionContext()

    def evaluateHandle(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> AsyncAny:
        return self._mainWorld.evaluateHandle(
            pageFunction, *args, withCliAPI=withCliAPI
        )

    def evaluate(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> AsyncAny:
        return self._mainWorld.evaluate(pageFunction, *args, withCliAPI=withCliAPI)

    def evaluate_expression(
        self, expression: str, withCliAPI: bool = False
    ) -> AsyncAny:
        """Evaluates the js expression in the frame returning the results by value.

        :param str expression: The js expression to be evaluated in the main frame.
        :param bool withCliAPI:  Determines whether Command Line API should be available during the evaluation.
        """
        return self._mainWorld.evaluate_expression(expression, withCliAPI=withCliAPI)

    def querySelector(self, selector: str) -> Awaitable[Optional[ElementHandle]]:
        """Get element which matches `selector` string.

        Details see :meth:`simplechrome.page.Page.querySelector`.
        """
        return self._mainWorld.querySelector(selector)

    def querySelectorEval(
        self, selector: str, pageFunction: str, *args: Any
    ) -> AsyncAny:
        """Execute function on element which matches selector.

        Details see :meth:`simplechrome.page.Page.querySelectorEval`.
        """
        return self._mainWorld.querySelectorEval(selector, pageFunction, *args)

    def querySelectorAll(self, selector: str) -> Awaitable[List[ElementHandle]]:
        """Get all elelments which matches `selector`.

        Details see :meth:`simplechrome.page.Page.querySelectorAll`.
        """
        return self._mainWorld.querySelectorAll(selector)

    def querySelectorAllEval(
        self, selector: str, pageFunction: str, *args: Any
    ) -> Awaitable[List[Any]]:
        """Execute function on all elements which matches selector.

        Details see :meth:`simplechrome.page.Page.querySelectorAllEval`.
        """
        return self._mainWorld.querySelectorAllEval(selector, pageFunction, *args)

    def xpath(self, expression: str) -> Awaitable[List[ElementHandle]]:
        """Evaluate XPath expression.

        If there is no such element in this frame, return None.

        :arg str expression: XPath string to be evaluated.
        """
        return self._mainWorld.xpath(expression)

    def content(self) -> Awaitable[str]:
        """Get the whole HTML contents of the page."""
        return self.domWorld.content()

    def setContent(
        self, html: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> Awaitable[None]:
        """Set content to this page."""
        return self.domWorld.setContent(html, options, **kwargs)

    def addScriptTag(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> Awaitable[ElementHandle]:
        """Add script tag to this frame.

        Details see :meth:`simplechrome.page.Page.addScriptTag`.
        """
        return self._mainWorld.addScriptTag(options, **kwargs)

    def addStyleTag(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> Awaitable[ElementHandle]:
        """Add style tag to this frame.

        Details see :meth:`simplechrome.page.Page.addStyleTag`.
        """
        return self._mainWorld.addStyleTag(options, **kwargs)

    def click(
        self, selector: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> AsyncAny:
        """Click element which matches ``selector``.

        Details see :meth:`simplechrome.page.Page.click`.
        """
        return self.domWorld.click(selector, options, **kwargs)

    def focus(self, selector: str) -> Awaitable[None]:
        """Fucus element which matches ``selector``.

        Details see :meth:`simplechrome.page.Page.focus`.
        """
        return self.domWorld.focus(selector)

    def hover(self, selector: str) -> Awaitable[None]:
        """Mouse hover the element which matches ``selector``.

        Details see :meth:`simplechrome.page.Page.hover`.
        """
        return self.domWorld.hover(selector)

    def select(self, selector: str, *values: str) -> Awaitable[List[str]]:
        """Select options and return selected values.

        Details see :meth:`simplechrome.page.Page.select`.
        """
        return self.domWorld.select(selector, *values)

    async def tap(self, selector: str) -> None:
        """Tap the element which matches the ``selector``.

        Details see :meth:`simplechrome.page.Page.tap`.
        """
        await self.domWorld.tap(selector)

    async def type(
        self, selector: str, text: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> None:
        """Type ``text`` on the element which matches ``selector``.

        Details see :meth:`simplechrome.page.Page.type`.
        """
        await self._mainWorld.type(selector, text, options, **kwargs)

    def waitFor(
        self,
        selectorOrFunctionOrTimeout: Union[str, Number],
        options: Optional[Dict] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[Optional[JSHandle]]:
        """Wait until `selectorOrFunctionOrTimeout`.

        Details see :meth:`simplechrome.page.Page.waitFor`.
        """
        if not (
            Helper.is_number(selectorOrFunctionOrTimeout)
            or Helper.is_string(selectorOrFunctionOrTimeout)
        ):
            fut = self._loop.create_future()
            fut.set_exception(
                TypeError(
                    f"Unsupported target type: {type(selectorOrFunctionOrTimeout)}"
                )
            )
            return fut

        if Helper.is_number(selectorOrFunctionOrTimeout):
            fut = self._loop.create_task(
                sleep(selectorOrFunctionOrTimeout, loop=self._loop)
            )
            return fut
        if args or Helper.is_jsfunc(selectorOrFunctionOrTimeout):
            return self.waitForFunction(
                selectorOrFunctionOrTimeout, options, *args, **kwargs
            )
        if selectorOrFunctionOrTimeout.startswith("//"):
            return self.waitForXPath(selectorOrFunctionOrTimeout, options, **kwargs)
        return self.waitForSelector(selectorOrFunctionOrTimeout, options, **kwargs)

    def waitForFunction(
        self,
        pageFunction: str,
        options: Optional[Dict] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[Optional[JSHandle]]:
        """Wait until the function completes.

        Details see :meth:`simplechrome.page.Page.waitForFunction`.
        """
        return self._mainWorld.waitForFunction(pageFunction, options, *args, **kwargs)

    def title(self) -> Awaitable[str]:
        """Get title of the frame."""
        if self._frameManager._isolateWorlds:
            return self._secondaryWorld.title()
        return self._mainWorld.title()

    async def waitForSelector(
        self, selector: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> Optional[ElementHandle]:
        """Wait until element which matches ``selector`` appears on page.

        Details see :meth:`simplechrome.page.Page.waitForSelector`.
        """
        if self._frameManager._isolateWorlds:
            handle = await self._secondaryWorld.waitForSelector(
                selector, options, **kwargs
            )
        else:
            handle = await self._mainWorld.waitForSelector(selector, options, **kwargs)
        if handle is None:
            return None
        if self._frameManager._isolateWorlds:
            mainExecutionContext = await self._mainWorld.executionContext()
            result = await mainExecutionContext._adoptElementHandle(handle)
            await handle.dispose()
            return result
        return handle

    async def waitForXPath(
        self, xpath: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> Optional[ElementHandle]:
        """Wait until element which matches ``xpath`` appears on page.

        Details see :meth:`simplechrome.page.Page.waitForXPath`.
        """
        handle = await self.domWorld.waitForXPath(xpath, options, **kwargs)
        if handle is None:
            return None
        if self._frameManager._isolateWorlds:
            mainExecutionContext = await self._mainWorld.executionContext()
            result = await mainExecutionContext._adoptElementHandle(handle)
            await handle.dispose()
            return result
        return handle

    def navigation_waiter(
        self, loop: OptionalLoop = None, timeout: Optional[Number] = None
    ) -> Future:
        if not self._emits_life:
            raise WaitSetupError("Must enable life cycle emitting")
        eloop = Helper.ensure_loop(loop)
        fut = eloop.create_future()

        def set_true() -> None:
            if not fut.done():
                fut.set_result(True)

        listeners = [Helper.addEventListener(self, Events.Frame.Navigated, set_true)]

        fut.add_done_callback(lambda f: Helper.removeEventListeners(listeners))
        if timeout is not None:
            return self._loop.create_task(
                Helper.waitWithTimeout(
                    fut, timeout, "Frame.navigation_waiter", loop=eloop
                )
            )
        return fut

    async def _wait_for_life_cycle(
        self, cycle: str, loop: Loop, timeout: OptionalNumber = None
    ) -> None:
        fut: Future = loop.create_future()

        def on_life_cycle(lc: str) -> None:
            if lc == cycle and not fut.done():
                fut.set_result(True)

        listeners = [
            Helper.addEventListener(self, Events.Frame.LifeCycleEvent, on_life_cycle)
        ]

        fut.add_done_callback(lambda f: Helper.removeEventListeners(listeners))

        if timeout is not None:
            await Helper.waitWithTimeout(
                fut,
                timeout,
                taskName=f"Frame {self.url} waiting for {cycle}",
                loop=loop,
                raise_exception=False,
            )
        else:
            await fut

    def loaded_waiter(
        self, loop: OptionalLoop = None, timeout: OptionalNumber = None
    ) -> Future:
        if not self._emits_life:
            raise WaitSetupError("Must enable life cycle emitting")
        return self._loop.create_task(
            self._wait_for_life_cycle("loaded", Helper.ensure_loop(loop), timeout)
        )

    def network_idle_waiter(
        self, loop: OptionalLoop = None, timeout: OptionalNumber = None
    ) -> Future:
        if not self._emits_life:
            raise WaitSetupError("Must enable life cycle emitting")
        return self._loop.create_task(
            self._wait_for_life_cycle("networkidle", Helper.ensure_loop(loop), timeout)
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

    def _navigated(self, framePayload: Dict) -> None:
        self._name = framePayload.get("name", "")
        self._url = framePayload.get("url", "")
        if self._emits_life:
            self.emit(Events.Frame.Navigated)

    def _navigatedWithinDocument(self, url: str) -> None:
        self._url = url

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
            self.emit(Events.Frame.LifeCycleEvent, name)

    def _detach(self) -> None:
        self._detached = True
        self._secondaryWorld._detach()
        self._mainWorld._detach()
        if self._emits_life:
            self.emit(Events.Frame.Detached)
        self.remove_all_listeners()
        if self._parentFrame:
            self._parentFrame._childFrames.remove(self)
        self._parentFrame = None

    def __str__(self) -> str:
        return f"Frame(url={self._url}, name={self._name}, detached={self._detached}, id={self._id})"

    def __repr__(self) -> str:
        return self.__str__()
