"""The simple chrome package"""
from .browser_fetcher import BrowserFetcher, RevisionInfo
from .chrome import Chrome, BrowserContext
from .connection import Connection, CDPSession, ClientType
from .dialog import Dialog
from .emulation_manager import EmulationManager
from .errors import (
    LauncherError,
    NavigationTimeoutError,
    BrowserError,
    BrowserFetcherError,
    ElementHandleError,
    EvaluationError,
    InputError,
    NavigationError,
    PageError,
    WaitSetupError,
    WaitTimeoutError,
    NetworkError,
)
from .events import Events
from .execution_context import ExecutionContext
from .jsHandle import ElementHandle, JSHandle
from .frame_manager import FrameManager, Frame
from .input import Keyboard, Mouse, Touchscreen
from .launcher import Launcher, launch, connect
from .lifecycle_watcher import LifecycleWatcher
from .network_manager import NetworkManager, Request, Response, SecurityDetails
from .page import Page, ConsoleMessage
from .target import Target
from .us_keyboard_layout import keyDefinitions

__version__ = "1.4.0"

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
    "NavigationTimeoutError",
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
