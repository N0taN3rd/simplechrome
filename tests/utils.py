from typing import List, Callable, Tuple

import attr
from pyee import EventEmitter

from simplechrome.helper import EEListener

__all__ = ["EEHandler"]


@attr.dataclass(slots=True)
class EEHandler(object):
    listeners: List[EEListener] = attr.ib(factory=list)

    def addEventListener(
        self, emitter: EventEmitter, eventName: str, handler: Callable
    ) -> None:
        emitter.on(eventName, handler)
        self.listeners.append(
            dict(emitter=emitter, eventName=eventName, handler=handler)
        )

    def addEventListeners(
        self, emitter: EventEmitter, eventsHandlers: List[Tuple[str, Callable]]
    ) -> None:
        for eventName, handler in eventsHandlers:
            self.addEventListener(emitter, eventName, handler)

    def clean_up(self) -> None:
        for listener in self.listeners:
            emitter = listener["emitter"]
            eventName = listener["eventName"]
            handler = listener["handler"]
            emitter.remove_listener(eventName, handler)
        self.listeners.clear()
