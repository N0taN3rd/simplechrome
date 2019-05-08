from typing import Dict, List, Optional, Set

from pyee2 import EventEmitterS

from ._typings import CDPEvent, OptionalLoop
from .connection import ClientType, Connection
from .events import WorkerEvents, WorkerManagerEvents
from .helper import Helper
from .workers import ServiceWorker, Worker

__all__ = ["WorkerManager"]

WorkerTargets: Set[str] = {"worker", "shared_worker"}


class WorkerManager(EventEmitterS):
    __slots__ = [
        "_client",
        "_workers",
        "_serviceWorkers",
        "_serviceWorkersContexts",
        "_serviceWorkersEnabled",
        "_workersEnabled",
        "_autoAttachEnabled",
    ]

    def __init__(self, client: ClientType, loop: OptionalLoop = None) -> None:
        super().__init__(Helper.ensure_loop(loop))
        self._client: ClientType = client
        self._workers: Dict[str, Worker] = {}
        self._serviceWorkers: Dict[str, ServiceWorker] = {}
        self._serviceWorkersContexts: Dict[str, Dict] = {}
        self._serviceWorkersEnabled: bool = False
        self._workersEnabled: bool = False
        self._autoAttachEnabled: bool = False

        self._client.on(
            "ServiceWorker.workerErrorReported", self._onWorkerErrorReported
        )

        self._client.on(
            "ServiceWorker.workerRegistrationUpdated", self._onWorkerRegistrationUpdated
        )

        self._client.on(
            "ServiceWorker.workerVersionUpdated", self._onWorkerVersionUpdated
        )

        self._client.on("Target.attachedToTarget", self._onAttachedToTarget)
        self._client.on("Target.detachedFromTarget", self._onDetachedFromTarget)

    @property
    def serviceWorkers(self) -> List[ServiceWorker]:
        return [sw for sw in self._serviceWorkers.values()]

    @property
    def workers(self) -> List[Worker]:
        return [w for w in self._workers.values()]

    def serviceWorker(self, registration_id: str) -> Optional[ServiceWorker]:
        return self._serviceWorkers.get(registration_id)

    async def initialize(
        self, workers: bool = False, serviceWorkers: bool = False
    ) -> None:
        if workers:
            await self.enableWorkerMonitoring()
        if serviceWorkers:
            await self.enableServiceWorkerMonitoring()

    async def enableServiceWorkerMonitoring(self) -> None:
        if self._serviceWorkersEnabled:
            return
        self._serviceWorkersEnabled = True
        await self._enable_auto_attach()
        await self._client.send("ServiceWorker.enable", {})

    async def disableServiceWorkerMonitoring(self) -> None:
        if not self._serviceWorkersEnabled:
            return
        self._serviceWorkersEnabled = False
        await self._disable_auto_attach()
        await self._client.send("ServiceWorker.disable", {})

    async def enableWorkerMonitoring(self) -> None:
        if self._workersEnabled:
            return
        self._workersEnabled = True
        await self._enable_auto_attach()

    async def disableWorkerMonitoring(self) -> None:
        if not self._workersEnabled:
            return
        self._workersEnabled = False
        await self._disable_auto_attach()

    async def swUpdateRegistration(self, scopeURL: str) -> None:
        """
        :param scopeURL: The scopeURL
        """
        if not self._serviceWorkersEnabled:
            return
        await self._client.send(
            "ServiceWorker.updateRegistration", {"scopeURL": scopeURL}
        )

    async def swSetForceUpdateOnPageLoad(self, forceUpdateOnPageLoad: bool) -> None:
        """
        :param forceUpdateOnPageLoad: Force update T/F
        """
        if not self._serviceWorkersEnabled:
            return
        await self._client.send(
            "ServiceWorker.setForceUpdateOnPageLoad",
            {"forceUpdateOnPageLoad": forceUpdateOnPageLoad},
        )

    async def swDeliverPushMessage(
        self, origin: str, registrationId: str, data: str
    ) -> None:
        """Delivers a push message to the supplied origin from the ServiceWorker who's registrationId is the one supplied

        :param origin: The origin of the service worker
        :param registrationId: The service workers registration id
        :param data: The message's data
        """
        if not self._serviceWorkersEnabled:
            return
        await self._client.send(
            "ServiceWorker.deliverPushMessage",
            {"origin": origin, "registrationId": registrationId, "data": data},
        )

    async def swDispatchSyncEvent(
        self, origin: str, registrationId: str, tag: str, lastChance: bool = False
    ) -> None:
        """Delivers a sync event to the supplied origin from the ServiceWorker who's registrationId is the one supplied

        :param origin: The origin of the service worker
        :param registrationId: The service workers registration id
        :param tag:
        :param lastChance:
        """
        if not self._serviceWorkersEnabled:
            return
        await self._client.send(
            "ServiceWorker.dispatchSyncEvent",
            {
                "origin": origin,
                "registrationId": registrationId,
                "tag": tag,
                "lastChance": lastChance,
            },
        )

    async def swSkipWaiting(self, scopeURL: str) -> None:
        """
        :param scopeURL: The scopeURL
        """
        if not self._serviceWorkersEnabled:
            return
        await self._client.send("ServiceWorker.skipWaiting", {"scopeURL": scopeURL})

    async def swStartWorker(self, scopeURL: str) -> None:
        """
        :param scopeURL: The scopeURL
        """
        if not self._serviceWorkersEnabled:
            return
        await self._client.send("ServiceWorker.startWorker", {"scopeURL": scopeURL})

    async def swStopAllWorkers(self) -> None:
        """Stops all service workers"""
        if not self._serviceWorkersEnabled:
            return
        await self._client.send("ServiceWorker.stopAllWorkers", {})

    async def swStopWorker(self, versionId: str) -> None:
        """
        :param versionId: The versionId
        """
        if not self._serviceWorkersEnabled:
            return
        await self._client.send("ServiceWorker.stopWorker", {"versionId": versionId})

    async def swUnregister(self, versionId: str) -> None:
        """
        :param versionId: The versionId
        """
        if not self._serviceWorkersEnabled:
            return
        await self._client.send("ServiceWorker.unregister", {"versionId": versionId})

    def _onAttachedToTarget(self, event: CDPEvent) -> None:
        sessionId = event.get("sessionId")
        targetInfo = event.get("targetInfo")
        if targetInfo is not None:
            type_ = targetInfo.get("type")
            if type_ in WorkerTargets:
                if self._workersEnabled:
                    session = Connection.from_session(self._client).session(sessionId)
                    worker = Worker(
                        session, url=targetInfo.get("url"), type_=type_, loop=self._loop
                    )
                    self._workers[sessionId] = worker
                    self.emit(WorkerManagerEvents.WorkerCreated, worker)
                    return
        self._loop.create_task(
            self._client.send("Target.detachFromTarget", {"sessionId": sessionId})
        )

    def _onDetachedFromTarget(self, event: CDPEvent) -> None:
        sessionId = event.get("sessionId")
        worker = self._workers.pop(sessionId, None)
        if worker is None:
            return
        worker.emit(WorkerEvents.Destroyed)
        self.emit(WorkerManagerEvents.WorkerDestroyed, worker)

    def _onWorkerErrorReported(self, event: CDPEvent) -> None:
        errorMessage = event.get("errorMessage")
        if not errorMessage:
            return
        sw = self._serviceWorkers.get(errorMessage.get("registrationId", ""))
        if sw is not None:
            sw._error_reported(errorMessage)

    def _onWorkerRegistrationUpdated(self, event: CDPEvent) -> None:
        registrations = event.get("registrations")
        if registrations is not None:
            update_sw = self._update_sw
            for reg in registrations:
                update_sw(reg)

    def _onWorkerVersionUpdated(self, event: CDPEvent) -> None:
        versions = event.get("versions")
        if versions is not None:
            update_sw = self._update_sw
            for version in versions:
                update_sw(version, True)

    def _update_sw(self, update_how: Dict, is_version: bool = False) -> None:
        reg_id = update_how.get("registrationId")
        sw = self._serviceWorkers.get(reg_id)
        is_add = sw is None
        if is_add:
            sw = ServiceWorker(self)
            self._serviceWorkers[reg_id] = sw
        sw._bookKeeping(update_how, is_version)
        if is_add:
            self.emit(WorkerManagerEvents.ServiceWorkerAdded, sw)

    def _remove_service_worker(self, reg_id: str) -> None:
        sw = self._serviceWorkers.pop(reg_id, None)
        if sw is not None:
            self.emit(WorkerManagerEvents.ServiceWorkerDeleted, sw)

    def _ensure_serviceWorker_swapped(self, sw: ServiceWorker, prev_id: str) -> None:
        maybe_swapped = self._serviceWorkers.get(prev_id)
        if maybe_swapped is not None and maybe_swapped is not sw:
            rid = sw.registrationId
            if rid not in self._serviceWorkers:
                self._serviceWorkers[rid] = sw
            self._remove_service_worker(prev_id)

    def _clear_workers(self) -> None:
        for sw in self._serviceWorkers.values():
            sw._destroyed()
        self._serviceWorkers.clear()
        self._workers.clear()

    async def _enable_auto_attach(self) -> None:
        if (
            not self._autoAttachEnabled
            and not self._workersEnabled
            and not self._serviceWorkersEnabled
        ):
            return
        await self._client.send(
            "Target.setAutoAttach",
            {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True},
        )
        self._autoAttachEnabled = True

    async def _disable_auto_attach(self) -> None:
        if self._autoAttachEnabled and (
            (self._workersEnabled and not self._serviceWorkersEnabled)
            or (not self._workersEnabled and self._serviceWorkers)
        ):
            return
        await self._client.send(
            "Target.setAutoAttach",
            {"autoAttach": False, "waitForDebuggerOnStart": False, "flatten": True},
        )
        self._autoAttachEnabled = False
