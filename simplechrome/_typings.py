from asyncio import AbstractEventLoop, Future, Task
from typing import (
    Any,
    Awaitable,
    ClassVar,
    Dict,
    List,
    Optional,
    Union,
)

__all__ = [
    "AsyncAny",
    "CDPEvent",
    "Device",
    "EventType",
    "FutureOrTask",
    "HTTPHeaders",
    "Loop",
    "Number",
    "OptionalFuture",
    "OptionalLoop",
    "OptionalNumber",
    "OptionalTask",
    "OptionalViewport",
    "SlotsT",
    "TargetInfo",
    "Viewport",
]


Number = Union[float, int]
Loop = AbstractEventLoop
FutureOrTask = Union[Future, Task]
SlotsT = List[str]
AsyncAny = Awaitable[Any]
Device = Dict[str, Union[str, Dict[str, Union[Number, bool]]]]

OptionalNumber = Optional[Number]
OptionalLoop = Optional[Loop]
OptionalTask = Optional[Task]
OptionalFuture = Optional[Future]

HTTPHeaders = Dict[str, str]
EventType = ClassVar[str]
CDPEvent = Dict
Viewport = Dict[str, int]
OptionalViewport = Optional[Viewport]
TargetInfo = Dict[str, str]
