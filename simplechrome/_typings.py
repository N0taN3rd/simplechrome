from asyncio import AbstractEventLoop, Future, Task
from typing import Any, Awaitable, ClassVar, Coroutine, Dict, List, Optional, Union

__all__ = [
    "AsyncAny",
    "CDPEvent",
    "CoAny",
    "Device",
    "EventType",
    "FutureOrTask",
    "HTTPHeaders",
    "Loop",
    "Number",
    "NumberOrStr",
    "OptionalFuture",
    "OptionalLoop",
    "OptionalNumber",
    "OptionalStr",
    "OptionalTask",
    "OptionalViewport",
    "SlotsT",
    "TargetInfo",
    "Viewport",
]


Number = Union[float, int]
NumberOrStr = Union[str, Number]
Loop = AbstractEventLoop
FutureOrTask = Union[Future, Task]
SlotsT = List[str]
AsyncAny = Awaitable[Any]
CoAny = Coroutine[Any, Any, Any]
Device = Dict[str, Union[str, Dict[str, Union[Number, bool]]]]

OptionalNumber = Optional[Number]
OptionalStr = Optional[str]
OptionalLoop = Optional[Loop]
OptionalTask = Optional[Task]
OptionalFuture = Optional[Future]

HTTPHeaders = Dict[str, str]
EventType = ClassVar[str]
CDPEvent = Dict[str, Any]
Viewport = Dict[str, int]
OptionalViewport = Optional[Viewport]
TargetInfo = Dict[str, str]
