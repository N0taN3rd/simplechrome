from collections import Callable
from typing import List, Dict, Optional, Any
from asyncio import AbstractEventLoop
from pyee import EventEmitter
from .execution_context import ExecutionContext, JSHandle
from .connection import ClientType
from .util import ensure_loop


class Worker(EventEmitter):
    def __init__(
        self,
        client: ClientType,
        url: str,
        consoleAPICalled: Callable[[str, List[JSHandle]], Any],
        exceptionThrown: Callable[[Dict], Any],
        loop: Optional[AbstractEventLoop] = None,
    ) -> None:
        super().__init__(loop=ensure_loop(loop))
        self._client = client
        self._url = url
        self._executionContextPromise = self._loop.create_future()
