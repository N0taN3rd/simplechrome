from asyncio import Future
from typing import Any, Awaitable, Callable, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import urlparse

from pyee2 import EventEmitterS

from ._typings import CDPEvent, Number, OptionalLoop, SlotsT
from .connection import ClientType
from .console_message import ConsoleMessage
from .events import ServiceWorkerEvents, WorkerEvents
from .execution_context import ExecutionContext
from .helper import Helper
from .jsHandle import JSHandle

if TYPE_CHECKING:
    from .worker_manager import WorkerManager

__all__ = ["Worker", "ServiceWorker"]


class Worker(EventEmitterS):
    __slots__: SlotsT = [
        "_client",
        "_url",
        "_type",
        "_executionContextPromise",
        "_jsHandleFactory",
    ]

    def __init__(
        self,
        client: ClientType,
        url: Optional[str] = None,
        type_: str = "worker",
        loop: OptionalLoop = None,
    ) -> None:
        super().__init__(loop=Helper.ensure_loop(loop))
        self._client: ClientType = client
        self._url: Optional[str] = url
        self._type: str = type_
        self._executionContextPromise: Future = self._loop.create_future()
        self._jsHandleFactory: Optional[Callable[[Dict], JSHandle]] = None
        self._client.once(
            "Runtime.executionContextCreated", self._once_execution_context_created
        )
        self._client.on("Runtime.consoleAPICalled", self._on_console_api)
        self._client.on("Runtime.exceptionThrown", self._on_exception)
        self._loop.create_task(self._client.send("Runtime.enable", {}))

    @property
    def url(self) -> Optional[str]:
        return self._url

    @property
    def type(self) -> str:
        return self._type

    @property
    def executionContext(self) -> Awaitable[ExecutionContext]:
        return self._executionContextPromise

    async def evaluate(self, pageFunction: str, *args: Any) -> Any:
        context = await self._executionContextPromise
        result = await context.evaluate(pageFunction, *args)
        return result

    async def evaluateHandle(self, pageFunction: str, *args: Any) -> Any:
        context = await self._executionContextPromise
        result = await context.evaluateHandle(pageFunction, *args)
        return result

    def _on_console_api(self, event: CDPEvent) -> None:
        self.emit(
            WorkerEvents.Console,
            ConsoleMessage(event, jsHandleFactory=self._jsHandleFactory),
        )

    def _on_exception(self, event: CDPEvent) -> None:
        self.emit(WorkerEvents.Error, event)

    def _once_execution_context_created(self, event: CDPEvent) -> None:
        context = event.get("context")
        execution_context = ExecutionContext(self._client, context)
        self._executionContextPromise.set_result(execution_context)
        self._jsHandleFactory = lambda remoteObject: JSHandle(
            execution_context, self._client, remoteObject
        )


class ServiceWorker(EventEmitterS):
    __slots__: SlotsT = ["_manager", "_info", "_origin"]

    def __init__(self, manager: "WorkerManager") -> None:
        super().__init__(Helper.ensure_loop(manager._loop))
        self._manager: "WorkerManager" = manager
        self._info: Dict = {}
        self._origin: str = ""

    @property
    def as_dict(self) -> Dict:
        return self._info

    @property
    def origin(self) -> str:
        return self._origin

    @property
    def versionId(self) -> str:
        return self._info.get("versionId")

    @property
    def registrationId(self) -> str:
        return self._info.get("registrationId")

    @property
    def scopeURL(self) -> str:
        return self._info.get("scopeURL")

    @property
    def isDeleted(self) -> bool:
        return self._info.get("isDeleted")

    @property
    def runningStatus(self) -> bool:
        return self._info.get("runningStatus")

    @property
    def status(self) -> bool:
        return self._info.get("status")

    @property
    def scriptLastModified(self) -> Optional[Number]:
        return self._info.get("scriptLastModified")

    @property
    def scriptResponseTime(self) -> Optional[Number]:
        return self._info.get("scriptResponseTime")

    @property
    def targetId(self) -> bool:
        return self._info.get("targetId")

    @property
    def controlledClients(self) -> Optional[List[str]]:
        return self._info.get("controlledClients")

    async def updateRegistration(self) -> None:
        await self._manager.swUpdateRegistration(self.scopeURL)

    async def deliverPushMessage(self, data: str) -> None:
        """Delivers a push message to the service worker

        :param data: The message's data
        """
        await self._manager.swDeliverPushMessage(self.origin, self.registrationId, data)

    async def dispatchSyncEvent(self, tag: str, lastChance: bool = False) -> None:
        """Delivers a sync event to the supplied origin from the ServiceWorker who's registrationId is the one supplied

        :param tag:
        :param lastChance:
        """
        await self._manager.swDispatchSyncEvent(
            self.origin, self.registrationId, tag, lastChance
        )

    async def swSkipWaiting(self) -> None:
        await self._manager.swSkipWaiting(self.scopeURL)

    async def startWorker(self) -> None:
        await self._manager.swStartWorker(self.scopeURL)

    async def stopWorker(self) -> None:
        await self._manager.swStopWorker(self.versionId)

    async def unregister(self) -> None:
        await self._manager.swStopWorker(self.versionId)
        self._manager._remove_service_worker(self.registrationId)

    def _bookKeeping(self, update_how: Dict, is_version: bool) -> None:
        prev_id = self.registrationId
        if is_version:
            self._info.update(update_how)
            self.emit(ServiceWorkerEvents.VersionUpdated)
            if self.isDeleted:
                self._manager._remove_service_worker(self.registrationId)
                self.emit(ServiceWorkerEvents.Deleted)
        else:
            new_scope = update_how.get("scopeURL")
            if new_scope is not None and self.scopeURL != new_scope:
                purl = urlparse(new_scope)
                self._origin = f"{purl.scheme}://{purl.netloc}"
            self._info.update(update_how)
            self.emit(ServiceWorkerEvents.RegistrationUpdated)
        if prev_id is not None and prev_id != self.registrationId:
            self._manager._ensure_serviceWorker_swapped(self, prev_id)

    def _error_reported(self, error: Dict) -> None:
        self.emit(ServiceWorkerEvents.Error, error)

    def _destroyed(self) -> None:
        self.emit(ServiceWorkerEvents.Closed)

    def __str__(self) -> str:
        return f"ServiceWorker({self._info})"

    def __repr__(self) -> str:
        return self.__str__()
