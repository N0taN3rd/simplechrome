from cripy.errors import NetworkError, ProtocolError

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


class EvaluationError(Exception):
    """For evaluation errors"""


class WaitSetupError(Exception):
    """Indicates a precondition for Frame wait functions was not met"""
