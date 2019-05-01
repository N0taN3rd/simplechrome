"""The simple chrome package"""
from .browser_fetcher import BrowserFetcher, RevisionInfo
from .chrome import BrowserContext, Chrome
from .connection import CDPSession, ClientType, Connection
from .console_message import ConsoleMessage
from .dialog import Dialog
from .emulation_manager import EmulationManager
from .errors import (
    BrowserError,
    BrowserFetcherError,
    ElementHandleError,
    EvaluationError,
    InputError,
    LauncherError,
    NavigationError,
    NetworkError,
    PageError,
    WaitSetupError,
    WaitTimeoutError,
)
from .events import Events
from .execution_context import ExecutionContext
from .frame_manager import Frame, FrameManager
from .input import Keyboard, Mouse, Touchscreen
from .jsHandle import ElementHandle, JSHandle
from .launcher import Launcher, connect, launch
from .lifecycle_watcher import LifecycleWatcher
from .log import Log, LogEntry
from .network import (
    NetworkIdleMonitor,
    NetworkManager,
    Request,
    Response,
    SecurityDetails,
)
from .page import Page
from .target import Target
from .us_keyboard_layout import keyDefinitions

__version__ = "1.5.0"

__all__ = [
    "BrowserContext",
    "BrowserError",
    "BrowserFetcher",
    "BrowserFetcherError",
    "CDPSession",
    "Chrome",
    "ClientType",
    "connect",
    "Connection",
    "ConsoleMessage",
    "Dialog",
    "ElementHandle",
    "ElementHandleError",
    "EmulationManager",
    "EvaluationError",
    "ExecutionContext",
    "Events",
    "Frame",
    "FrameManager",
    "InputError",
    "JSHandle",
    "Keyboard",
    "keyDefinitions",
    "launch",
    "Launcher",
    "LauncherError",
    "LifecycleWatcher",
    "Mouse",
    "NavigationError",
    "NetworkError",
    "NetworkManager",
    "Page",
    "PageError",
    "Request",
    "Response",
    "RevisionInfo",
    "SecurityDetails",
    "Target",
    "Touchscreen",
    "WaitSetupError",
    "WaitTimeoutError",
]
