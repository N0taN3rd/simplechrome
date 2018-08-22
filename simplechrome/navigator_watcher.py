# -*- coding: utf-8 -*-
"""Navigator Watcher module."""

import asyncio
import concurrent.futures
from typing import Any, Awaitable, Dict, List

from .helper import Helper
from .errors import WaitTimeoutError
from .frame_manager import FrameManager, Frame
from .util import merge_dict

__all__ = ["NavigatorWatcher"]


class NavigatorWatcher:
    """NavigatorWatcher class."""

    def __init__(
        self,
        frameManager: FrameManager,
        frame: Frame,
        timeout: int,
        options: Dict = None,
        **kwargs: Any,
    ) -> None:
        """Make new navigator watcher."""
        options = merge_dict(options, kwargs)
        self._validate_options(options)
        self._frameManager = frameManager
        self._frame = frame
        self._initialLoaderId = frame._loaderId
        self._timeout = timeout
        self._hasSameDocumentNavigation = False
        self.all_frames = options.get("all_frames", True)
        self._eventListeners = [
            Helper.addEventListener(
                self._frameManager,
                FrameManager.Events.LifecycleEvent,
                self._checkLifecycleComplete,
            ),
            Helper.addEventListener(
                self._frameManager,
                FrameManager.Events.FrameDetached,
                self._checkLifecycleComplete,
            ),
            Helper.addEventListener(
                self._frameManager,
                FrameManager.Events.FrameNavigatedWithinDocument,
                self._navigatedWithinDocument,
            ),
        ]
        loop = asyncio.get_event_loop()
        self._lifecycleCompletePromise = loop.create_future()
        self._navigationPromise = asyncio.ensure_future(
            asyncio.wait(
                [self._lifecycleCompletePromise, self._createTimeoutPromise()],
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
        )
        self._navigationPromise.add_done_callback(lambda fut: self._cleanup())

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
        self._expectedLifecycle: List[str] = []
        for value in waitUntil:
            protocolEvent = WaitToProtocolLifecycle.get(value)
            if protocolEvent is None:
                raise ValueError(f"Unknown value for options.waitUntil: {value}")
            self._expectedLifecycle.append(protocolEvent)

    def _navigatedWithinDocument(self, frame):
        if frame != self._frame:
            return
        self._hasSameDocumentNavigation = True
        self._checkLifecycleComplete()

    def _createTimeoutPromise(self) -> Awaitable[None]:
        self._maximumTimer = asyncio.get_event_loop().create_future()
        if self._timeout:
            errorMessage = (
                f"Navigation Timeout Exceeded: {self._timeout} ms exceeded."
            )  # noqa: E501

            async def _timeout_func() -> None:
                await asyncio.sleep(self._timeout / 1000)
                self._maximumTimer.set_exception(WaitTimeoutError(errorMessage))

            self._timeout_timer = asyncio.ensure_future(_timeout_func())
        else:
            self._timeout_timer = asyncio.get_event_loop().create_future()
        return self._maximumTimer

    def navigationPromise(self) -> Any:
        """Return navigation promise."""
        return self._navigationPromise

    def _checkLifecycleComplete(self, frame: Frame = None) -> None:
        if (
            self._frame._loaderId == self._initialLoaderId
            and not self._hasSameDocumentNavigation
        ):
            return
        if not self._checkLifecycle(self._frame, self._expectedLifecycle):
            return

        if not self._lifecycleCompletePromise.done():
            self._lifecycleCompletePromise.set_result(None)

    def _checkLifecycle(self, frame: Frame, expectedLifecycle: List[str]) -> bool:
        for event in expectedLifecycle:
            if event not in frame._lifecycleEvents:
                return False
        if self.all_frames:
            for child in frame.childFrames:
                if not self._checkLifecycle(child, expectedLifecycle):
                    return False
        return True

    def cancel(self) -> None:
        """Cancel navigation."""
        self._cleanup()

    def _cleanup(self) -> None:
        Helper.removeEventListeners(self._eventListeners)
        self._lifecycleCompletePromise.cancel()
        self._maximumTimer.cancel()
        self._timeout_timer.cancel()


WaitToProtocolLifecycle = {
    "load": "load",
    "documentloaded": "DOMContentLoaded",
    "networkidle0": "networkIdle",
    "networkidle2": "networkAlmostIdle",
}
