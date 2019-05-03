from asyncio import CancelledError, Future, Task, TimeoutError, sleep
from typing import Any, Dict, List, Optional, Set

from async_timeout import timeout
from pyee2 import EventEmitterS

from simplechrome._typings import OptionalLoop, SlotsT
from simplechrome.connection import ClientType
from simplechrome.helper import EEListener, Helper

__all__ = ["NetworkIdleMonitor"]


class NetworkIdleMonitor(EventEmitterS):
    """Monitors the network requests of the remote browser to determine when
    network idle happens"""

    __slots__: SlotsT = [
        "__weakref__",
        "_client",
        "_global_wait",
        "_idle_future",
        "_idle_time",
        "_listeners",
        "_num_inflight",
        "_requestIds",
        "_safety_task",
        "_to",
    ]

    def __init__(
        self,
        client: ClientType,
        num_inflight: int = 2,
        idle_time: int = 2,
        global_wait: int = 60,
        loop: OptionalLoop = None,
    ) -> None:
        super().__init__(loop=Helper.ensure_loop(loop))
        self._client: ClientType = client
        self._requestIds: Set[str] = set()
        self._num_inflight: int = num_inflight
        self._idle_time: int = idle_time
        self._global_wait: int = global_wait
        self._to: Optional[Task] = None
        self._safety_task: Optional[Task] = None
        self._idle_future: Optional[Future] = None
        self._listeners: Optional[List[EEListener]] = None

    @classmethod
    def monitor(
        cls,
        client: ClientType,
        num_inflight: int = 2,
        idle_time: int = 2,
        global_wait: int = 60,
        loop: OptionalLoop = None,
    ) -> Task:
        niw = cls(
            client=client,
            num_inflight=num_inflight,
            idle_time=idle_time,
            global_wait=global_wait,
            loop=loop,
        )
        return niw.create_idle_future()

    def create_idle_future(self) -> Task:
        """Creates and returns the global wait future that resolves once
        newtwork idle has been emitted or the global wait time has been
        reached

        :return: A future
        """
        self._idle_future = self._loop.create_future()
        self.once("idle", self.idle_cb)
        return self._loop.create_task(self._global_to_wait())

    def idle_cb(self) -> None:
        """Sets the idle future results to done"""
        if not self._idle_future.done():
            self._idle_future.set_result(True)

    def clean_up(self, *args: Any, **kwargs: Any) -> None:
        """Cleans up after ourselves"""
        if self._listeners is not None:
            Helper.removeEventListeners(self._listeners)
        if self._safety_task is not None and not self._safety_task.done():
            self._safety_task.cancel()
        if self._to is not None and not self._to.done():
            self._to.cancel()

    async def _global_to_wait(self) -> None:
        """Coroutine that waits for the idle future to resolve or
        global wait time to be hit
        """
        self._idle_future.add_done_callback(self.clean_up)
        self._listeners = [
            Helper.addEventListener(
                self._client, "Network.requestWillBeSent", self.req_started
            ),
            Helper.addEventListener(
                self._client, "Network.loadingFinished", self.req_finished
            ),
            Helper.addEventListener(
                self._client, "Network.loadingFailed", self.req_finished
            ),
        ]

        try:
            self._safety_task = self._loop.create_task(self.safety())
            async with timeout(self._global_wait, loop=self._loop):
                await self._idle_future
        except TimeoutError:
            self.emit("idle")

        self._requestIds.clear()
        if self._to is not None and not self._to.done():
            self._to.cancel()
            try:
                async with timeout(10, loop=self._loop):
                    await self._to
            except (TimeoutError, CancelledError):
                pass
            self._to = None

    async def safety(self) -> None:
        """Guards against waiting the full global wait time if the network was idle and stays idle"""
        await sleep(5, loop=self._loop)
        if self._idle_future and not self._idle_future.done():
            self._idle_future.set_result(True)

    async def _start_timeout(self) -> None:
        """Starts the idle time wait and if this Coroutine is not canceled
        and the idle time elapses the idle event is emitted signifying
        network idle has been reached
        """
        await sleep(self._idle_time, loop=self._loop)
        self.emit("idle")

    def req_started(self, info: Dict) -> None:
        """Listener for the Network.requestWillBeSent events

        :param info: The request info supplied by the CDP
        """
        self._requestIds.add(info["requestId"])
        if len(self._requestIds) > self._num_inflight and self._to:
            self._to.cancel()
            self._to = None
        if self._safety_task is not None:
            self._safety_task.cancel()
            self._safety_task = None

    def req_finished(self, info: Dict) -> None:
        """Listener for the Network.loadingFinished and
        Network.loadingFailed events

        :param info: The request info supplied by the CDP
        """
        rid = info["requestId"]
        if rid in self._requestIds:
            self._requestIds.remove(rid)
        if len(self._requestIds) <= self._num_inflight and self._to is None:
            self._to = self._loop.create_task(self._start_timeout())
