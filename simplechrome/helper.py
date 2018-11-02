# -*- coding: utf-8 -*-
"""Helper functions."""
import asyncio
import json
from typing import Any, Callable, Dict, List, Union, Awaitable, Optional

import math
from async_timeout import timeout as aiotimeout
from asyncio import AbstractEventLoop
from .util import ensure_loop

from .connection import Client, TargetSession
from .errors import ElementHandleError
from pyee import EventEmitter


__all__ = ["Helper", "unserializableValueMap", "EEListener"]

unserializableValueMap = {
    "-0": -0,
    "NaN": None,
    None: None,
    "Infinity": math.inf,
    "-Infinity": -math.inf,
}

EEListener = Dict[str, Union[str, EventEmitter, Callable]]


class Helper(object):
    @staticmethod
    def evaluationString(fun: str, *args: Any) -> str:
        """Convert function and arguments to str."""
        _args = ", ".join(
            [json.dumps("undefined" if arg is None else arg) for arg in args]
        )
        expr = f"({fun})({_args})"
        return expr

    @staticmethod
    def getExceptionMessage(exceptionDetails: dict) -> str:
        """Get exception message from `exceptionDetails` object."""
        exception = exceptionDetails.get("exception")
        if exception is not None:
            return exception.get(
                "description", exception.get("value", "")
            )  # type: ignore
        message = exceptionDetails.get("text", "")
        stackTrace = exceptionDetails.get("stackTrace")
        if stackTrace is not None:
            for callframe in stackTrace.get("callFrames"):
                location = (
                    str(callframe.get("url", ""))
                    + ":"
                    + str(callframe.get("lineNumber", ""))
                    + ":"
                    + str(callframe.get("columnNumber"))
                )
                functionName = callframe.get("functionName", "<anonymous>")
                message = message + f"\n    at {functionName} ({location})"
        return message

    @staticmethod
    def addEventListener(
        emitter: EventEmitter, eventName: str, handler: Callable
    ) -> EEListener:
        """Add handler to the emitter and return emitter/handler."""
        emitter.on(eventName, handler)
        return {"emitter": emitter, "eventName": eventName, "handler": handler}

    @staticmethod
    def removeEventListeners(listeners: List[EEListener]) -> None:
        """Remove listeners from emitter."""
        for listener in listeners:
            emitter = listener["emitter"]
            eventName = listener["eventName"]
            handler = listener["handler"]
            emitter.remove_listener(eventName, handler)
        listeners.clear()

    @staticmethod
    def valueFromRemoteObject(remoteObject: Dict) -> Any:
        """Serialize value of remote object."""
        if remoteObject.get("objectId"):
            raise ElementHandleError("Cannot extract value when objectId is given")
        value = remoteObject.get("unserializableValue")
        if value:
            if value == "-0":
                return -0
            elif value == "NaN":
                return None
            elif value == "Infinity":
                return math.inf
            elif value == "-Infinity":
                return -math.inf
            else:
                raise ElementHandleError(
                    "Unsupported unserializable value: {}".format(value)
                )
        return remoteObject.get("value")

    @staticmethod
    async def releaseObject(
        client: Union[Client, TargetSession], remoteObject: dict
    ) -> None:
        """Release remote object."""
        objectId = remoteObject.get("objectId")
        if not objectId:
            return
        try:
            await client.send("Runtime.releaseObject", {"objectId": objectId})
        except Exception:
            # Exceptions might happen in case of a page been navigated or closed.
            # Swallow these since they are harmless and we don't leak anything in this case.  # noqa
            pass

    @staticmethod
    def get_positive_int(obj: dict, name: str) -> int:
        """Get and check the value of name in obj is positive integer."""
        value = obj[name]
        if not isinstance(value, int):
            raise TypeError(f"{name} must be integer: {type(value)}")
        elif value < 0:
            raise ValueError(f"{name} must be positive integer: {value}")
        return value

    @staticmethod
    def is_jsfunc(func: str) -> bool:  # not in puppeteer
        """Huristically check function or expression."""
        func = func.strip()
        if func.startswith("function") or func.startswith("async "):
            return True
        elif "=>" in func:
            return True
        return False

    @staticmethod
    async def timed_wait(
        awaitable: Awaitable[Any],
        to: Union[int, float],
        loop: Optional[AbstractEventLoop] = None,
    ) -> None:
        try:
            async with aiotimeout(to, loop=ensure_loop(loop)):
                await awaitable
        except asyncio.TimeoutError:
            pass
