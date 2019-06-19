from contextlib import asynccontextmanager
from typing import Any, Optional, Union

import aiofiles
from aiofiles.threadpool import (
    AsyncBufferedIOBase,
    AsyncBufferedReader,
    AsyncFileIO,
    AsyncTextIOWrapper,
)

__all__ = ["maybe_open_file"]

AIOFilesIO = Union[
    AsyncTextIOWrapper, AsyncBufferedIOBase, AsyncFileIO, AsyncBufferedReader
]


@asynccontextmanager
async def maybe_open_file(
    file: Optional[str] = None, *args: Any, **kwargs: Any
) -> Optional[AIOFilesIO]:
    if file is None:
        yield None
    else:
        async with aiofiles.open(file, *args, **kwargs) as io:
            yield io
