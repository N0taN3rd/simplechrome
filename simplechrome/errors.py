from typing import Any, Optional, TYPE_CHECKING

from cripy.errors import NetworkError, ProtocolError

if TYPE_CHECKING:
    from .network_manager import Response

__all__ = [
    "BrowserError",
    "BrowserFetcherError",
    "ElementHandleError",
    "NetworkError",
    "PageError",
    "ProtocolError",
    "WaitTimeoutError",
    "LauncherError",
    "InputError",
    "NavigationError",
    "EvaluationError",
    "NavigationTimeoutError",
    "WaitSetupError",
]


class BrowserError(Exception):
    """Exception raised from browser."""


class BrowserFetcherError(Exception):
    """Exception raised if there is a issue with downloading / querying about chromium revisions"""


class ElementHandleError(Exception):
    """ElementHandle related exception."""


class PageError(Exception):
    """Page/Frame related exception."""


class WaitTimeoutError(Exception):
    """Timeout Error class."""


class LauncherError(Exception):
    """Launching Chrome related exception"""


class InputError(Exception):
    """Input related exception"""


class NavigationError(Exception):
    """For navigation errors"""


class NavigationTimeoutError(Exception):
    """For navigation timeout errors"""

    def __init__(self, *args: Any, response: Optional["Response"] = None) -> None:
        super().__init__(*args)
        self.response: Optional["Response"] = response


class EvaluationError(Exception):
    """For evaluation errors"""


class WaitSetupError(Exception):
    """Indicates a precondition for Frame wait functions was not met"""
