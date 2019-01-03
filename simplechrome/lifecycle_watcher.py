import asyncio
from asyncio import AbstractEventLoop, Future, Task
from typing import Dict, Optional, Union, Any, List, Iterable, TYPE_CHECKING

from async_timeout import timeout as aio_timeout

from .errors import NavigationError, NavigationTimeoutError
from .helper import Helper
from .util import ensure_loop

if TYPE_CHECKING:
    from .frame_manager import FrameManager, Frame  # noqa: F401
    from .network_manager import NetworkManager, Request, Response  # noqa: F401


__all__ = ["LifecycleWatcher"]

WaitToProtocolLifecycle: Dict[str, str] = {
    "load": "load",
    "documentloaded": "DOMContentLoaded",
    "networkidle0": "networkIdle",
    "networkidle2": "networkAlmostIdle",
}


class LifecycleWatcher(object):
    def __init__(
        self,
        frameManager: "FrameManager",
        frame: "Frame",
        waitUntil: Union[str, Iterable[str]],
        timeout: Optional[Union[int, float]] = None,
        all_frames: bool = True,
        loop: Optional[AbstractEventLoop] = None,
    ) -> None:
        self._frameManager: "FrameManager" = frameManager
        self._frame: "Frame" = frame
        self._networkManager: Optional["NetworkManager"] = frameManager._networkManager
        self._initialLoaderId: str = frame._loaderId
        self._navigationRequest: Optional["Request"] = None
        self._timeout: Optional[Union[int, float]] = timeout
        self._expectedLifecycle: List[str] = []
        self._hasSameDocumentNavigation: bool = False
        self.all_frames: bool = all_frames
        self.loop: AbstractEventLoop = ensure_loop(loop)
        self._build_expected_lifecyle(waitUntil)
        self._eventListeners = [
            Helper.addEventListener(
                self._frameManager._client,
                self._frameManager._client.Events.Disconnected,
                lambda: self._terminate(
                    NavigationError(
                        "Navigation failed because browser has disconnected!"
                    )
                ),
            ),
            Helper.addEventListener(
                self._frameManager,
                self._frameManager.Events.LifecycleEvent,
                self._checkLifecycleComplete,
            ),
            Helper.addEventListener(
                self._frameManager,
                self._frameManager.Events.FrameDetached,
                self._onFrameDetached,
            ),
            Helper.addEventListener(
                self._frameManager,
                self._frameManager.Events.FrameNavigatedWithinDocument,
                self._navigatedWithinDocument,
            ),
        ]
        if self._networkManager is not None:
            self._eventListeners.append(
                Helper.addEventListener(
                    self._networkManager,
                    self._networkManager.Events.Request,
                    self._onRequest,
                )
            )

        self._sameDocumentNavigationPromise: Future = self.loop.create_future()
        self._lifecyclePromise: Future = self.loop.create_future()
        self._newDocumentNavigationPromise: Future = self.loop.create_future()
        self._timeoutPromise: Union[Future, Task] = self._createTimeoutPromise()
        self._terminationPromise: Future = self.loop.create_future()
        self._checkLifecycleComplete()

    @property
    def timeoutPromise(self) -> Union[Future, Task]:
        return self._timeoutPromise

    @property
    def terminationPromise(self) -> Future:
        return self._terminationPromise

    @property
    def newDocumentNavigationPromise(self) -> Future:
        return self._newDocumentNavigationPromise

    @property
    def sameDocumentNavigationPromise(self) -> Future:
        return self._sameDocumentNavigationPromise

    @property
    def lifecyclePromise(self) -> Future:
        return self._lifecyclePromise

    @property
    def navigationResponse(self) -> Optional["Response"]:
        if self._navigationRequest:
            return self._navigationRequest.response
        return None

    def dispose(self) -> None:
        Helper.removeEventListeners(self._eventListeners)
        Helper.cleanup_futures(
            self._terminationPromise,
            self._timeoutPromise,
            self._lifecyclePromise,
            self._sameDocumentNavigationPromise,
            self._newDocumentNavigationPromise,
        )

    def _terminate(self, error: Exception) -> None:
        if not self._terminationPromise.done():
            self._terminationPromise.set_result(error)

    def _onFrameDetached(self, frame: "Frame") -> None:
        if frame is self._frame:
            self._terminate(NavigationError("Navigating frame was detached"))
            return
        self._checkLifecycleComplete()

    def _navigatedWithinDocument(self, frame: "Frame") -> None:
        if frame is not self._frame:
            return
        self._hasSameDocumentNavigation = True
        self._checkLifecycleComplete()

    def _onRequest(self, request: "Request") -> None:
        if request.frame is not self._frame or not request.isNavigationRequest:
            return
        self._navigationRequest = request

    def _createTimeoutPromise(self) -> Union[Future, Task]:
        timeoutPromise = self.loop.create_future()
        if self._timeout is not None:
            return self.loop.create_task(self._timeout_func(timeoutPromise))
        return timeoutPromise

    async def _timeout_func(
        self, timeoutPromise: Future
    ) -> Optional[NavigationTimeoutError]:
        try:
            async with aio_timeout(self._timeout, loop=self.loop):
                await timeoutPromise
        except asyncio.TimeoutError:
            return NavigationTimeoutError(
                f"Navigation Timeout Exceeded: {self._timeout} seconds exceeded."
            )
        return None

    def _checkLifecycleComplete(self, *args: Any, **kwargs: Any) -> None:
        if not self._checkLifecycle(self._frame, self._expectedLifecycle):
            return
        if not self._lifecyclePromise.done():
            self._lifecyclePromise.set_result(None)
        if (
            self._frame._loaderId == self._initialLoaderId
            and not self._hasSameDocumentNavigation
        ):
            return
        if (
            self._hasSameDocumentNavigation
            and not self._sameDocumentNavigationPromise.done()
        ):
            self._sameDocumentNavigationPromise.set_result(None)
        if (
            self._frame._loaderId != self._initialLoaderId
            and not self._newDocumentNavigationPromise.done()
        ):
            self._newDocumentNavigationPromise.set_result(None)

    def _checkLifecycle(self, frame: "Frame", expectedLifecycle: List[str]) -> bool:
        for event in expectedLifecycle:
            if event not in frame._lifecycleEvents:
                return False
        if self.all_frames:
            for child in frame.childFrames:
                if not self._checkLifecycle(child, expectedLifecycle):
                    return False
        return True

    def _build_expected_lifecyle(
        self, waitUntil: Optional[Union[Iterable[str], str]] = None
    ) -> None:
        if isinstance(waitUntil, list):
            waitUntil = waitUntil
        elif isinstance(waitUntil, str):
            waitUntil = [waitUntil]
        else:
            waitUntil = ["load"]
        for value in waitUntil:
            protocolEvent = WaitToProtocolLifecycle.get(value)
            if protocolEvent is None:
                raise ValueError(f"Unknown value for options.waitUntil: {value}")
            self._expectedLifecycle.append(protocolEvent)
