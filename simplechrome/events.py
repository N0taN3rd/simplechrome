from typing import ClassVar, Type

from cripy import ConnectionEvents, SessionEvents

from ._typings import EventType

__all__ = [
    "BrowserContextEvents",
    "ChromeEvents",
    "Events",
    "FrameEvents",
    "FrameManagerEvents",
    "NetworkManagerEvents",
    "PageEvents",
    "WorkerEvents",
    "WorkerManagerEvents",
    "ServiceWorkerEvents",
]


class BrowserContextEvents:
    TargetCreated: EventType = "BrowserContext.targetcreated"
    TargetChanged: EventType = "BrowserContext.targetchanged"
    TargetDestroyed: EventType = "BrowserContext.targetdestroyed"


class ChromeEvents:
    Disconnected: EventType = "Chrome.disconnected"
    TargetCreated: EventType = "Chrome.targetcreated"
    TargetDestroyed: EventType = "Chrome.targetdestroyed"
    TargetChanged: EventType = "Chrome.targetchanged"


class FrameEvents:
    LifeCycleEvent: EventType = "Frame.lifecycleevent"
    Detached: EventType = "Frame.detached"
    Navigated: EventType = "Frame.navigated"


class FrameManagerEvents:
    FrameAttached: EventType = "FrameManager.frameattached"
    FrameNavigated: EventType = "FrameManager.framenavigated"
    FrameDetached: EventType = "FrameManager.framedetached"
    LifecycleEvent: EventType = "FrameManager.lifecycleevent"
    FrameNavigatedWithinDocument: EventType = "FrameManager.framenavigatedwithindocument"
    ExecutionContextCreated: EventType = "FrameManager.executioncontextcreated"
    ExecutionContextDestroyed: EventType = "FrameManager.executioncontextdestroyed"


class NetworkManagerEvents:
    Request: EventType = "NetworkManager.Request"
    Response: EventType = "NetworkManager.Response"
    RequestFailed: EventType = "NetworkManager.Requestfailed"
    RequestFinished: EventType = "NetworkManager.Requestfinished"


class PageEvents:
    Close: EventType = "Page.close"
    Console: EventType = "Page.console"
    Crashed: EventType = "Page.crashed"
    DOMContentLoaded: EventType = "Page.domcontentloaded"
    Dialog: EventType = "Page.dialog"
    Error: EventType = "Page.error"
    FrameAttached: EventType = "Page.frameattached"
    FrameDetached: EventType = "Page.framedetached"
    FrameNavigated: EventType = "Page.framenavigated"
    FrameNavigatedWithinDocument: EventType = "Page.framenavigatedwithindocument"

    LifecycleEvent: EventType = "Page.lifecycleevent"
    Load: EventType = "Page.load"
    LogEntry: EventType = "Page.logentry"
    Metrics: EventType = "Page.metrics"
    NavigatedWithinDoc: EventType = "Page.navigatedwithindoc"
    PageError: EventType = "Page.pageerror"
    Popup: EventType = "Page.popup"
    Request: EventType = "Page.request"
    RequestFailed: EventType = "Page.requestfailed"
    RequestFinished: EventType = "Page.requestfinished"
    Response: EventType = "Page.response"
    WorkerCreated: EventType = "Page.workercreated"
    WorkerDestroyed: EventType = "Page.workerdestroyed"
    ServiceWorkerAdded: EventType = "Page.serviceWorkerAdded"
    ServiceWorkerDeleted: EventType = "Page.serviceWorkerDeleted"


class LogEvents:
    EntryAdded: EventType = "Log.entryAdded"


class WorkerEvents:
    Console: EventType = "Worker.ConsoleMessage"
    Destroyed: EventType = "Worker.Destroyed"
    Error: EventType = "Worker.Error"


class WorkerManagerEvents:
    ServiceWorkerAdded: EventType = "WorkerManager.serviceWorkerAdded"
    ServiceWorkerDeleted: EventType = "WorkerManager.serviceWorkerDeleted"
    Console: EventType = "WorkerManager.console"
    Error: EventType = "WorkerManager.error"
    WorkerCreated: EventType = "WorkerManager.workerCreated"
    WorkerDestroyed: EventType = "WorkerManager.workerDestroyed"


class ServiceWorkerEvents:
    Error: EventType = "ServiceWorker.workerErrorReported"
    RegistrationUpdated: EventType = "ServiceWorker.workerRegistrationUpdated"
    VersionUpdated: EventType = "ServiceWorker.workerVersionUpdated"
    Deleted: EventType = "ServiceWorker.deleted"
    Closed: EventType = "ServiceWorker.closed"


class Events:
    BrowserContext: ClassVar[Type[BrowserContextEvents]] = BrowserContextEvents
    CDPSession: ClassVar[Type[SessionEvents]] = SessionEvents
    Chrome: ClassVar[Type[ChromeEvents]] = ChromeEvents
    Connection: ClassVar[Type[ConnectionEvents]] = ConnectionEvents
    Frame: ClassVar[Type[FrameEvents]] = FrameEvents
    FrameManager: ClassVar[Type[FrameManagerEvents]] = FrameManagerEvents
    NetworkManager: ClassVar[Type[NetworkManagerEvents]] = NetworkManagerEvents
    Page: ClassVar[Type[PageEvents]] = PageEvents
    Log: ClassVar[Type[LogEvents]] = LogEvents
    Worker: ClassVar[Type[WorkerEvents]] = WorkerEvents
    WorkerManager: ClassVar[Type[WorkerManagerEvents]] = WorkerManagerEvents
    ServiceWorker: ClassVar[Type[ServiceWorkerEvents]] = ServiceWorkerEvents
