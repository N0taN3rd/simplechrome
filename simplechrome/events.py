import attr
from cripy import (
    ConnectionEvents,
    SessionEvents,
    Connection as Connection_,
    CDPSession as CDPSession_,
)

__all__ = [
    "BrowserContextEvents",
    "ChromeEvents",
    "Events",
    "Events_",
    "FrameEvents",
    "FrameManagerEvents",
    "NetworkManagerEvents",
    "PageEvents",
]


@attr.dataclass(slots=True, frozen=True)
class BrowserContextEvents:
    TargetCreated: str = attr.ib(init=False, default="BrowserContext.targetcreated")
    TargetChanged: str = attr.ib(init=False, default="BrowserContext.targetchanged")
    TargetDestroyed: str = attr.ib(init=False, default="BrowserContext.targetdestroyed")


@attr.dataclass(slots=True, frozen=True)
class ChromeEvents:
    Disconnected: str = attr.ib(init=False, default="Chrome.disconnected")
    TargetCreated: str = attr.ib(init=False, default="Chrome.targetcreated")
    TargetDestroyed: str = attr.ib(init=False, default="Chrome.targetdestroyed")
    TargetChanged: str = attr.ib(init=False, default="Chrome.targetchanged")


@attr.dataclass(slots=True, frozen=True)
class FrameEvents:
    LifeCycleEvent: str = attr.ib(default="Frame.lifecycleevent", init=False)
    Detached: str = attr.ib(default="Frame.detached", init=False)
    Navigated: str = attr.ib(default="Frame.navigated", init=False)


@attr.dataclass(slots=True, frozen=True)
class FrameManagerEvents:
    FrameAttached: str = attr.ib(default="FrameManager.frameattached", init=False)
    FrameNavigated: str = attr.ib(default="FrameManager.framenavigated", init=False)
    FrameDetached: str = attr.ib(default="FrameManager.framedetached", init=False)
    LifecycleEvent: str = attr.ib(default="FrameManager.lifecycleevent", init=False)
    FrameNavigatedWithinDocument: str = attr.ib(
        default="FrameManager.framenavigatedwithindocument", init=False
    )
    ExecutionContextCreated: str = attr.ib(
        default="FrameManager.executioncontextcreated", init=False
    )
    ExecutionContextDestroyed: str = attr.ib(
        default="FrameManager.executioncontextdestroyed", init=False
    )


@attr.dataclass(slots=True, frozen=True)
class NetworkManagerEvents(object):
    Request: str = attr.ib(default="NetworkManager.Request")
    Response: str = attr.ib(default="NetworkManager.Response")
    RequestFailed: str = attr.ib(default="NetworkManager.Requestfailed")
    RequestFinished: str = attr.ib(default="NetworkManager.Requestfinished")


@attr.dataclass(slots=True, frozen=True)
class PageEvents:
    Close: str = attr.ib(init=False, default="Page.close")
    Console: str = attr.ib(init=False, default="Page.console")
    Crashed: str = attr.ib(init=False, default="Page.crashed")
    DOMContentLoaded: str = attr.ib(init=False, default="Page.domcontentloaded")
    Dialog: str = attr.ib(init=False, default="Page.dialog")
    Error: str = attr.ib(init=False, default="Page.error")
    FrameAttached: str = attr.ib(init=False, default="Page.frameattached")
    FrameDetached: str = attr.ib(init=False, default="Page.framedetached")
    FrameNavigated: str = attr.ib(init=False, default="Page.framenavigated")
    FrameNavigatedWithinDocument: str = attr.ib(
        init=False, default="Page.framenavigatedwithindocument"
    )
    LifecycleEvent: str = attr.ib(init=False, default="Page.lifecycleevent")
    Load: str = attr.ib(init=False, default="Page.load")
    LogEntry: str = attr.ib(init=False, default="Page.logentry")
    Metrics: str = attr.ib(init=False, default="Page.metrics")
    NavigatedWithinDoc: str = attr.ib(init=False, default="Page.navigatedwithindoc")
    PageError: str = attr.ib(init=False, default="Page.pageerror")
    Popup: str = attr.ib(init=False, default="Page.popup")
    Request: str = attr.ib(init=False, default="Page.request")
    RequestFailed: str = attr.ib(init=False, default="Page.requestfailed")
    RequestFinished: str = attr.ib(init=False, default="Page.requestfinished")
    Response: str = attr.ib(init=False, default="Page.response")
    WorkerCreated: str = attr.ib(init=False, default="Page.workercreated")
    WorkerDestroyed: str = attr.ib(init=False, default="Page.workerdestroyed")


@attr.dataclass(slots=True, frozen=True)
class Events_:
    BrowserContext: BrowserContextEvents = attr.ib(
        init=False, factory=BrowserContextEvents
    )
    CDPSession: SessionEvents = attr.ib(init=False, default=CDPSession_.Events)
    Chrome: ChromeEvents = attr.ib(init=False, factory=ChromeEvents)
    Connection: ConnectionEvents = attr.ib(init=False, default=Connection_.Events)
    Frame: FrameEvents = attr.ib(init=False, factory=FrameEvents)
    FrameManager: FrameManagerEvents = attr.ib(init=False, factory=FrameManagerEvents)
    NetworkManager: NetworkManagerEvents = attr.ib(
        init=False, factory=NetworkManagerEvents
    )
    Page: PageEvents = attr.ib(init=False, factory=PageEvents)


Events = Events_()
