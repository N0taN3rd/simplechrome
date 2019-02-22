from asyncio import AbstractEventLoop, Future, Task, TimeoutError as AIOTimeoutError
from typing import Any, Dict, Iterable, List, Optional, TYPE_CHECKING, Union

import attr
from async_timeout import timeout as aio_timeout

from .errors import NavigationError, NavigationTimeoutError
from .events import Events
from .helper import EEListener, Helper

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


@attr.dataclass(slots=True, cmp=False, hash=False)
class LifecycleWatcher:
    _frameManager: "FrameManager" = attr.ib(repr=False)
    _frame: "Frame" = attr.ib()
    _waitUntil: Union[Iterable[str], str] = attr.ib(default=None)
    _timeout: Optional[Union[int, float]] = attr.ib(default=None)
    _all_frames: bool = attr.ib(default=True)
    _loop: Optional[AbstractEventLoop] = attr.ib(
        default=None, repr=False, converter=Helper.ensure_loop
    )
    _networkManager: Optional["NetworkManager"] = attr.ib(
        init=False, repr=False, default=None
    )
    _initialLoaderId: str = attr.ib(init=False, default=None)
    _expectedLifecycle: List[str] = attr.ib(init=False, factory=list)
    _hasSameDocumentNavigation: bool = attr.ib(init=False, default=False)
    _eventListeners: List[EEListener] = attr.ib(init=False, repr=False, default=None)
    _navigationRequest: Optional["Request"] = attr.ib(
        init=False, repr=False, default=None
    )
    _sameDocumentNavigationPromise: Future = attr.ib(
        init=False, repr=False, default=None
    )
    _lifecyclePromise: Future = attr.ib(init=False, repr=False, default=None)
    _newDocumentNavigationPromise: Future = attr.ib(
        init=False, repr=False, default=None
    )
    _timeoutPromise: Future = attr.ib(init=False, repr=False, default=None)
    _terminationPromise: Future = attr.ib(init=False, repr=False, default=None)

    @property
    def timeoutPromise(self) -> Future:
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
        if self._all_frames:
            for child in frame.childFrames:
                if not self._checkLifecycle(child, expectedLifecycle):
                    return False
        return True

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
        timeoutPromise = self._loop.create_future()
        if self._timeout is not None:
            return self._loop.create_task(self._timeout_func(timeoutPromise))
        return timeoutPromise

    async def _timeout_func(
        self, timeoutPromise: Future
    ) -> Optional[NavigationTimeoutError]:
        try:
            async with aio_timeout(self._timeout, loop=self._loop):
                await timeoutPromise
        except AIOTimeoutError:
            return NavigationTimeoutError(
                f"Navigation Timeout Exceeded: {self._timeout} seconds exceeded.",
                response=self.navigationResponse
            )
        return None

    def _build_expected_lifecyle(self) -> None:
        waitUntil = self._waitUntil
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

    def __attrs_post_init__(self) -> None:
        self._build_expected_lifecyle()
        self._networkManager = self._frameManager._networkManager
        self._initialLoaderId = self._frame._loaderId
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
                Events.FrameManager.LifecycleEvent,
                self._checkLifecycleComplete,
            ),
            Helper.addEventListener(
                self._frameManager,
                Events.FrameManager.FrameDetached,
                self._onFrameDetached,
            ),
            Helper.addEventListener(
                self._frameManager,
                Events.FrameManager.FrameNavigatedWithinDocument,
                self._navigatedWithinDocument,
            ),
        ]
        if self._networkManager is not None:
            self._eventListeners.append(
                Helper.addEventListener(
                    self._networkManager, Events.NetworkManager.Request, self._onRequest
                )
            )

        self._sameDocumentNavigationPromise = self._loop.create_future()
        self._lifecyclePromise = self._loop.create_future()
        self._newDocumentNavigationPromise = self._loop.create_future()
        self._timeoutPromise = self._createTimeoutPromise()
        self._terminationPromise = self._loop.create_future()
        self._checkLifecycleComplete()
