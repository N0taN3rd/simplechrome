"""Helper functions."""
from asyncio import FIRST_COMPLETED, Future, TimeoutError, get_event_loop, wait
from typing import (
    Any,
    Awaitable,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
)

import math
from aiohttp import AsyncResolver, ClientSession, TCPConnector
from async_timeout import timeout
from pyee2 import EventEmitter, EventEmitterS
from ujson import dumps

from ._typings import FutureOrTask, Loop, Number, OptionalLoop, OptionalNumber
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

EEType = Union[EventEmitter, EventEmitterS]
EEListener = Dict[str, Union[str, EEType, Callable]]

MAYBE_NUMBER_CHECK_TUPLE: Tuple[Type[int], Type[float]] = (int, float)


class Helper:
    @staticmethod
    def is_number(maybe_number: Any) -> bool:
        return isinstance(maybe_number, MAYBE_NUMBER_CHECK_TUPLE)

    @staticmethod
    def is_boolean(maybe_boolean: Any) -> bool:
        return isinstance(maybe_boolean, bool)

    @staticmethod
    def is_string(maybe_string: Any) -> bool:
        return isinstance(maybe_string, str)

    @staticmethod
    def is_jsfunc(func: str) -> bool:  # not in puppeteer
        """Heuristically check function or expression."""
        func = func.strip()
        if func.startswith("function") or func.startswith("async "):
            return True
        elif "=>" in func:
            return True
        return False

    @staticmethod
    def evaluationString(fun: str, *args: Any) -> str:
        """Convert function and arguments to str."""
        _args = ", ".join(["undefined" if arg is None else dumps(arg) for arg in args])
        return f"({fun})({_args})"

    @staticmethod
    def getExceptionMessage(exceptionDetails: Dict) -> str:
        """Get exception message from `exceptionDetails` object."""
        exception = exceptionDetails.get("exception")
        if exception is not None:
            return exception.get("description", exception.get("value", ""))
        message = [exceptionDetails.get("text", "")]
        stackTrace = exceptionDetails.get("stackTrace")
        if stackTrace is not None:
            for callframe in stackTrace.get("callFrames"):
                location = f'{callframe.get("url", "")}:{callframe.get("lineNumber", "")}:{callframe.get("columnNumber")}'
                functionName = callframe.get("functionName", "<anonymous>")
                message.append(f"\n    at {functionName} ({location})")
        return "".join(message)

    @staticmethod
    def addEventListener(
        emitter: EEType, eventName: str, handler: Callable
    ) -> EEListener:
        """Add handler to the emitter and return emitter/handler."""
        emitter.on(eventName, handler)
        return {"emitter": emitter, "eventName": eventName, "handler": handler}

    @staticmethod
    def removeEventListeners(listeners: List[EEListener]) -> None:
        """Remove listeners from emitter."""
        for listener in listeners:
            emitter: EEType = listener["emitter"]
            eventName: str = listener["eventName"]  # type: ignore
            handler: Callable = listener["handler"]  # type: ignore
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
    def cleanup_futures(*args: Future) -> None:
        for future in args:
            if future and not (future.cancelled() or future.done()):
                future.cancel()

    @staticmethod
    def remove_dict_keys(dictionary: Dict, *args: str) -> None:
        for key in args:
            dictionary.pop(key, None)

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
    def make_aiohttp_session(loop: OptionalLoop = None) -> ClientSession:
        """Creates and returns a new aiohttp.ClientSession that uses AsyncResolver

        :param loop: Optional asyncio event loop to use. Defaults to asyncio.get_event_loop()
        :return: An instance of aiohttp.ClientSession
        """
        eloop = Helper.ensure_loop(loop)
        return ClientSession(
            connector=TCPConnector(resolver=AsyncResolver(loop=eloop), loop=eloop),
            loop=eloop,
            json_serialize=dumps,
        )

    @staticmethod
    def ensure_loop(loop: OptionalLoop = None) -> Loop:
        """Helper method for checking if the loop is none and if so use asyncio.get_event_loop
        to retrieve it otherwise the loop is passed through
        """
        if loop is not None:
            return loop
        return get_event_loop()

    @staticmethod
    async def waitWithTimeout(
        awaitable: Awaitable[Any],
        to: Number,
        taskName: Optional[str] = "",
        loop: OptionalLoop = None,
        raise_exception: bool = True,
        cb: Optional[Callable] = None,
    ) -> None:
        try:
            async with timeout(to, loop=Helper.ensure_loop(loop)):
                await awaitable
        except TimeoutError:
            if raise_exception:
                raise WaitTimeoutError(
                    f"Timeout of {to} seconds exceeded while waiting for {taskName}"
                )
        finally:
            if cb is not None:
                try:
                    cb()
                except Exception:
                    pass

    @staticmethod
    def waitForEvent(
        emitter: EEType,
        eventName: str,
        predicate: Callable[[Any], bool],
        to: OptionalNumber = None,
    ) -> FutureOrTask:
        loop = Helper.ensure_loop(emitter._loop)
        done_promise = loop.create_future()

        def listener(event: Any = None) -> None:
            if predicate(event) and not done_promise.done():
                done_promise.set_result(None)

        emitter.on(eventName, listener)

        promise = (
            done_promise
            if to is None
            else loop.create_task(
                Helper.waitWithTimeout(done_promise, to, eventName, loop=loop)
            )
        )
        promise.add_done_callback(
            lambda _: emitter.remove_listener(eventName, listener)
        )
        return done_promise

    @staticmethod
    def wait_for_first_done(
        *args: Union[Coroutine, FutureOrTask], loop: OptionalLoop = None
    ) -> Awaitable[Tuple[Set[Future], Set[Future]]]:
        return wait(args, return_when=FIRST_COMPLETED, loop=loop)
