import base64
from typing import Any, Dict, List, Optional, Awaitable

import attr
import aiofiles
import asyncio
from .connection import ClientType
from .util import merge_dict

__all__ = ["Tracing"]


@attr.dataclass(slots=True)
class Tracing(object):
    client: ClientType = attr.ib()
    _recording: bool = attr.ib(init=False, default=False)
    _path: Optional[str] = attr.ib(init=False, default="")

    async def start(self, options: Optional[Dict], **kwargs: Any) -> None:
        opts = merge_dict(options, kwargs)
        defaultCategories: List[str] = [
            "-*",
            "devtools.timeline",
            "v8.execute",
            "disabled-by-default-devtools.timeline",
            "disabled-by-default-devtools.timeline.frame",
            "toplevel",
            "blink.console",
            "blink.user_timing",
            "latencyInfo",
            "disabled-by-default-devtools.timeline.stack",
            "disabled-by-default-v8.cpu_profiler",
            "disabled-by-default-v8.cpu_profiler.hires",
        ]
        path = opts.get("path", None)
        categories = opts.get("categories", defaultCategories)
        if opts.get("screenshots", False):
            categories.append("disabled-by-default-devtools.screenshot")

        self._path = path
        self._recording = True
        await self.client.send(
            "Tracing.start",
            dict(transferMode="ReturnAsStream", categories=",".join(categories)),
        )

    async def stop(self) -> Awaitable[bytes]:
        contentPromise = asyncio.get_event_loop().create_future()

        @self.client.once("Tracing.tracingComplete")
        async def done(event: Dict) -> None:
            stream: str = event.get("stream")
            if self._path:
                content: bytes = await self._serialize_stream_to_file(
                    stream, self._path
                )
            else:
                content = await self._readStream(stream)
            contentPromise.set_result(content)

        return contentPromise

    async def _readStream(self, handle: str) -> bytes:
        eof = False
        content: List[bytes] = []
        while not eof:
            response = await self.client.send("IO.read", dict(handle=handle))
            eof = response.get("eof")
            if response.get("base64Encoded", False):
                content.append(base64.b64decode(response.get("data")))
            else:
                content.append(response.get("data").encode("utf-8"))

        await self.client.send("IO.close", dict(handle=handle))
        return b"".join(content)

    async def _serialize_stream_to_file(self, handle: str, path: str) -> bytes:
        eof = False
        content: List[bytes] = []
        async with aiofiles.open(path, "wb") as out:
            while not eof:
                response = await self.client.send("IO.read", dict(handle=handle))
                eof = response.get("eof")
                if response.get("base64Encoded", False):
                    data = base64.b64decode(response.get("data"))
                else:
                    data = response.get("data").encode("utf-8")
                content.append(data)
                await out.write(data)
        return b"".join(content)
