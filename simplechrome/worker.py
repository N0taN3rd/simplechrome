from asyncio import AbstractEventLoop
from collections import Callable
from typing import Any, Dict, List, Optional

from pyee2 import EventEmitter

from .connection import ClientType
from .execution_context import JSHandle
from .helper import Helper


class Worker(EventEmitter):
    def __init__(
        self,
        client: ClientType,
        url: str,
        consoleAPICalled: Callable[[str, List[JSHandle]], Any],
        exceptionThrown: Callable[[Dict], Any],
        loop: Optional[AbstractEventLoop] = None,
    ) -> None:
        super().__init__(loop=Helper.ensure_loop(loop))
        self._client = client
        self._url = url
        self._executionContextPromise = self._loop.create_future()
