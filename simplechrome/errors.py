from typing import Any, Optional, TYPE_CHECKING

from cripy.errors import NetworkError, ProtocolError

if TYPE_CHECKING:
    from .request_response import Response  # noqa: F401

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

    def __init__(
        self,
        *args: Any,
        response: Optional["Response"] = None,
        timeout: bool = False,
        failed: bool = False,
        disconnected: bool = False,
    ) -> None:
        super().__init__(*args)
        self.response: Optional["Response"] = response
        self.timeout: bool = timeout
        self.failed: bool = failed
        self.disconnected: bool = disconnected

    @classmethod
    def TimedOut(
        cls, msg: str, response: Optional["Response"] = None
    ) -> "NavigationError":
        return cls(msg, response=response, timeout=True)

    @classmethod
    def Failed(
        cls, msg: str, response: Optional["Response"] = None, tb: Any = None
    ) -> "NavigationError":
        ne: NavigationError = cls(msg, response=response, failed=True)
        if tb is not None:
            ne.with_traceback(tb)
        return ne

    @classmethod
    def Disconnected(
        cls, msg: str, response: Optional["Response"] = None
    ) -> "NavigationError":
        return cls(msg, response=response, disconnected=True)


class EvaluationError(Exception):
    """For evaluation errors"""


class WaitSetupError(Exception):
    """Indicates a precondition for Frame wait functions was not met"""
