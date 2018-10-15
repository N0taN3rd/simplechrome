# -*- coding: utf-8 -*-
import asyncio

from cripy.client import NetworkError

__all__ = [
    "BrowserError",
    "ElementHandleError",
    "NetworkError",
    "PageError",
    "WaitTimeoutError",
    "LauncherError",
    "InputError",
]


class BrowserError(Exception):  # noqa: D204
    """Exception raised from browser."""

    pass


class ElementHandleError(Exception):  # noqa: D204
    """ElementHandle related exception."""

    pass



class PageError(Exception):  # noqa: D204
    """Page/Frame related exception."""

    pass


class WaitTimeoutError(asyncio.TimeoutError):  # noqa: D204
    """Timeout Error class."""

    pass


class LauncherError(Exception):
    """Launching Chrome related exception"""

    pass


class InputError(Exception):
    """Input related exception"""

    pass
