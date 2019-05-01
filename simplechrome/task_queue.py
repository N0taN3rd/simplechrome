from asyncio import Task
from typing import Any, Coroutine

from ._typings import Loop, OptionalLoop, SlotsT
from .helper import Helper

__all__ = ["TaskQueue"]


class TaskQueue:
    __slots__: SlotsT = ["loop"]

    def __init__(self, loop: OptionalLoop = None) -> None:
        self.loop: Loop = Helper.ensure_loop(loop)

    def post_task(self, task: Coroutine[Any, Any, Any]) -> Task:
        return self.loop.create_task(task)
