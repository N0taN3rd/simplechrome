from typing import Callable, ClassVar, Dict, Union

from .jsHandle import JSHandle

__all__ = [
    "CDPEvent",
    "EventType",
    "JHandleFact",
    "Number"
]


Number = Union[float, int]
JHandleFact = Callable[[Dict], JSHandle]

EventType = ClassVar[str]
CDPEvent = Dict
