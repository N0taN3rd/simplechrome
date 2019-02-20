"""Helper functions."""
import math
from asyncio import (
    AbstractEventLoop,
    Future,
    Task,
    TimeoutError as AIOTimeoutError,
    get_event_loop as aio_get_event_loop,
)
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Type, Union
from ujson import dumps as ujson_dumps

from aiohttp import AsyncResolver, ClientSession, TCPConnector
from async_timeout import timeout as aiotimeout
from pyee2 import EventEmitter

from .connection import ClientType
from .errors import ElementHandleError, WaitTimeoutError

__all__ = ["Helper", "unserializableValueMap", "EEListener"]

unserializableValueMap = {
    "-0": -0,
    "NaN": None,
    None: None,
    "Infinity": math.inf,
    "-Infinity": -math.inf,
}

EEListener = Dict[str, Union[str, EventEmitter, Callable]]

MAYBE_NUMBER_CHECK_TUPLE: Tuple[Type[int], Type[float]] = (int, float)


class Helper:
    @staticmethod
    def evaluationString(fun: str, *args: Any) -> str:
        """Convert function and arguments to str."""
        _args = ", ".join(
            ["undefined" if arg is None else ujson_dumps(arg) for arg in args]
        )
        return f"({fun})({_args})"

    @staticmethod
    def getExceptionMessage(exceptionDetails: dict) -> str:
        """Get exception message from `exceptionDetails` object."""
        exception = exceptionDetails.get("exception")
        if exception is not None:
            return exception.get("description", exception.get("value", ""))
        message = [exceptionDetails.get("text", "")]
        stackTrace = exceptionDetails.get("stackTrace")
        if stackTrace is not None:
            for callframe in stackTrace.get("callFrames"):
                location = "".join(
                    [
                        str(callframe.get("url", "")),
                        ":",
                        str(callframe.get("lineNumber", "")),
                        ":",
                        str(callframe.get("columnNumber")),
                    ]
                )
                functionName = callframe.get("functionName", "<anonymous>")
                message.append(f"\n    at {functionName} ({location})")
        return "".join(message)

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
            emitter: EventEmitter = listener["emitter"]
            eventName: str = listener["eventName"]
            handler: Callable = listener["handler"]
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
    async def releaseObject(client: ClientType, remoteObject: Dict) -> None:
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
    def get_positive_int(obj: Dict, name: str) -> int:
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
    async def waitWithTimeout(
        awaitable: Awaitable[Any],
        to: Union[int, float],
        taskName: Optional[str] = "",
        loop: Optional[AbstractEventLoop] = None,
        raise_exception: bool = True
    ) -> None:
        try:
            async with aiotimeout(to, loop=Helper.ensure_loop(loop)):
                await awaitable
        except AIOTimeoutError:
            if raise_exception:
                raise WaitTimeoutError(
                    f"Timeout of {to} seconds exceeded while waiting for {taskName}"
                )

    @staticmethod
    def cleanup_futures(*args: Future) -> None:
        for future in args:
            if future and not (future.cancelled() or future.done()):
                future.cancel()

    @staticmethod
    def waitForEvent(
        emitter: EventEmitter,
        eventName: str,
        predicate: Callable[[Any], bool],
        timeout: Optional[Union[int, float]] = None,
    ) -> Union[Future, Task]:
        loop = Helper.ensure_loop(emitter._loop)

        promise = loop.create_future()

        def listener(event: Any = None) -> None:
            if predicate(event) and not promise.done():
                promise.set_result(None)

        emitter.on(eventName, listener)

        def clean_up(*args: Any, **kwargs: Any) -> None:
            emitter.remove_listener(eventName, listener)

        if timeout is not None:

            async def timed_promise() -> None:
                try:
                    async with aiotimeout(timeout):
                        await promise
                except AIOTimeoutError:
                    raise WaitTimeoutError("Timeout exceeded while waiting for event")
                finally:
                    clean_up()

            return loop.create_task(timed_promise())
        promise.add_done_callback(clean_up)
        return promise

    @staticmethod
    def is_number(maybe_number: Any) -> bool:
        return isinstance(maybe_number, MAYBE_NUMBER_CHECK_TUPLE)

    @staticmethod
    def is_string(maybe_string: Any) -> bool:
        return isinstance(maybe_string, str)

    @staticmethod
    def noop(*args: Any, **kwargs: Any) -> Any:
        return None

    @staticmethod
    def merge_dict(dict1: Optional[Dict], dict2: Optional[Dict]) -> Dict[Any, Any]:
        new_dict = {}
        if dict1:
            new_dict.update(dict1)
        if dict2:
            new_dict.update(dict2)
        return new_dict

    @staticmethod
    def loop_factory() -> AbstractEventLoop:
        return aio_get_event_loop()

    @staticmethod
    def ensure_loop(loop: Optional[AbstractEventLoop] = None) -> AbstractEventLoop:
        """Helper method for checking if the loop is none and if so use asyncio.get_event_loop
        to retrieve it otherwise the loop is passed through
        """
        if loop is not None:
            return loop
        return aio_get_event_loop()

    @staticmethod
    def make_aiohttp_session(loop: Optional[AbstractEventLoop] = None) -> ClientSession:
        """Creates and returns a new aiohttp.ClientSession that uses AsyncResolver

        :param loop: Optional asyncio event loop to use. Defaults to asyncio.get_event_loop()
        :return: An instance of aiohttp.ClientSession
        """
        if loop is None:
            loop = aio_get_event_loop()
        return ClientSession(
            connector=TCPConnector(resolver=AsyncResolver(loop=loop), loop=loop),
            loop=loop,
            json_serialize=ujson_dumps,
        )
