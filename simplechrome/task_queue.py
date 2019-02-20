from asyncio import AbstractEventLoop, Task
from typing import Any, Coroutine

import attr

__all__ = ["TaskQueue"]


@attr.dataclass(slots=True)
class TaskQueue:
    loop: AbstractEventLoop = attr.ib()

    def post_task(self, task: Coroutine[Any, Any, Any]) -> Task:
        return self.loop.create_task(task)
