# -*- coding: utf-8 -*-
"""Navigator Watcher module."""

import asyncio
from asyncio import AbstractEventLoop, get_event_loop, Future
from typing import Dict, Optional, Union, Any, List

from async_timeout import timeout as aiotimeout

from .connection import Client, TargetSession
from .errors import WaitTimeoutError
from .frame_manager import FrameManager, Frame
from .helper import Helper
from .network_manager import NetworkManager, Request, Response
from .util import merge_dict

__all__ = ["NavigatorWatcher", "FrameNavWatcher"]

WaitToProtocolLifecycle = {
    "load": "load",
    "documentloaded": "DOMContentLoaded",
    "networkidle0": "networkIdle",
    "networkidle2": "networkAlmostIdle",
}


class FrameNavWatcher(object):
    def __init__(
        self,
        client: Union[Client, TargetSession],
        frameManager: FrameManager,
        frame: Frame,
        timeout: Optional[Union[int, float]] = None,
        options: Optional[Dict] = None,
        **kwargs: Any,
    ) -> None:
        self._initialLoaderId: str = frame._loaderId
        self._timeout: Optional[Union[int, float]] = timeout
        self._frameManager: FrameManager = frameManager
        self._frame: Frame = frame
        self._hasSameDocumentNavigation: bool = False
        self._expectedLifecycle: List[str] = []
        self.all_frames: bool = False
        self._validate_options(merge_dict(options, kwargs))
        self.loop: AbstractEventLoop = get_event_loop()
        self._terminationPromise: Future = self.loop.create_future()
        self._timeoutPromise: Future = None
        self._maximumTimer: Optional[Future] = None
        self._eventListeners = [
            Helper.addEventListener(
                client._connection if isinstance(client, TargetSession) else client,
                Client.Events.Disconnected,
                lambda: self._terminate(
                    Exception("Navigation failed because browser has disconnected!")
                ),
            ),
            Helper.addEventListener(
                self._frameManager,
                FrameManager.Events.LifecycleEvent,
                self._checkLifecycleComplete,
            ),
            Helper.addEventListener(
                self._frameManager,
                FrameManager.Events.FrameDetached,
                self._onFrameDetached,
            ),
            Helper.addEventListener(
                self._frameManager,
                FrameManager.Events.FrameNavigatedWithinDocument,
                self._navigatedWithinDocument,
            ),
        ]

        self._sameDocumentNavigationPromise: Future = self.loop.create_future()
        self._newDocumentNavigationPromise: Future = self.loop.create_future()
        self._terminationPromise: Future = self.loop.create_future()
        self._maximumTimer: Future = self.loop.create_future()
        self._timeoutPromise: Future = self._createTimeoutPromise()

    def timeoutOrTerminationPromise(self) -> Future:
        return asyncio.ensure_future(
            asyncio.wait(
                [self._timeoutPromise, self._terminationPromise],
                return_when=asyncio.FIRST_COMPLETED,
            )
        )

    def newDocumentNavigationPromise(self):
        return self._sameDocumentNavigationPromise

    def sameDocumentNavigationPromise(self):
        return self._sameDocumentNavigationPromise

    def dispose(self) -> None:
        Helper.removeEventListeners(self._eventListeners)
        if self._maximumTimer:
            self._maximumTimer.cancel()
        if self._terminationPromise:
            self._terminationPromise.cancel()
        if self._timeoutPromise:
            self._timeoutPromise.cancel()
        self._sameDocumentNavigationPromise.cancel()
        self._newDocumentNavigationPromise.cancel()

    def _createTimeoutPromise(self) -> Future:
        timeoutPromise = self.loop.create_future()
        if self._timeout is not None:
            errorMessage = (
                f"Navigation Timeout Exceeded: {self._timeout} ms exceeded."
            )  # noqa: E501

            async def _timeout_func() -> None:
                try:
                    async with aiotimeout(self._timeout):
                        await timeoutPromise
                except asyncio.TimeoutError:
                    raise WaitTimeoutError(errorMessage)

            return asyncio.ensure_future(_timeout_func())
        return timeoutPromise

    def _terminate(self, error) -> None:
        if not self._terminationPromise.done():
            self._terminationPromise.set_result(error)

    def _onFrameDetached(self, frame: Frame) -> None:
        if frame is self._frame:
            return
        self._checkLifecycleComplete()

    def _navigatedWithinDocument(self, frame: Frame) -> None:
        if frame is not self._frame:
            return
        self._hasSameDocumentNavigation = True
        self._checkLifecycleComplete()

    def _checkLifecycleComplete(self, *args: Any, **kwargs: Any) -> None:
        if (
            self._frame._loaderId == self._initialLoaderId
            and not self._hasSameDocumentNavigation
        ):
            return
        if not self._checkLifecycle(self._frame, self._expectedLifecycle):
            return
        if self._hasSameDocumentNavigation:
            self._sameDocumentNavigationPromise.set_result(None)
        if self._frame._loaderId != self._initialLoaderId:
            self._newDocumentNavigationPromise.set_result(None)

    def _checkLifecycle(self, frame: Frame, expectedLifecycle: List[str]) -> bool:
        for event in expectedLifecycle:
            if event not in frame._lifecycleEvents:
                return False
        if self.all_frames:
            for child in frame.childFrames:
                if not self._checkLifecycle(child, expectedLifecycle):
                    return False
        return True

    def _validate_options(self, options: Dict) -> None:  # noqa: C901
        if "networkIdleTimeout" in options:
            raise ValueError("`networkIdleTimeout` option is no longer supported.")
        if "networkIdleInflight" in options:
            raise ValueError("`networkIdleInflight` option is no longer supported.")
        if options.get("waitUntil") == "networkidle":
            raise ValueError(
                "`networkidle` option is no logner supported."
                "Use `networkidle2` instead."
            )
        _waitUntil = options.get("waitUntil", "load")
        if isinstance(_waitUntil, list):
            waitUntil = _waitUntil
        elif isinstance(_waitUntil, str):
            waitUntil = [_waitUntil]
        else:
            waitUntil = ["load"]
        for value in waitUntil:
            protocolEvent = WaitToProtocolLifecycle.get(value)
            if protocolEvent is None:
                raise ValueError(f"Unknown value for options.waitUntil: {value}")
            self._expectedLifecycle.append(protocolEvent)
        self.all_frames = options.get("all_frames", True)


class NavigatorWatcher(FrameNavWatcher):
    def __init__(
        self,
        client: Union[Client, TargetSession],
        frameManager: FrameManager,
        networkManager: NetworkManager,
        frame: Frame,
        timeout: Optional[Union[int, float]] = None,
        options: Optional[Dict] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(client, frameManager, frame, timeout, options, **kwargs)
        self._navigationRequest: Optional[Request] = None
        self._eventListeners.append(Helper.addEventListener(
            networkManager,
            NetworkManager.Events.Request,
            self._onRequest
        ))

    @property
    def navigationResponse(self) -> Optional[Response]:
        if self._navigationRequest:
            return self._navigationRequest.response
        return None

    def _onRequest(self, request: Request) -> None:
        if request.frame is not self._frame or not request.isNavigationRequest:
                return
        self._navigationRequest = request


