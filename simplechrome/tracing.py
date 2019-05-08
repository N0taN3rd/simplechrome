from base64 import b64decode
from typing import Any, Dict, List, Optional

import aiofiles

from ._typings import Loop, OptionalLoop, SlotsT
from .connection import ClientType
from .helper import Helper

__all__ = ["Tracing"]


class Tracing:
    __slots__: SlotsT = ["__weakref__", "_loop", "_path", "_recording", "client"]

    def __init__(self, client: ClientType, loop: OptionalLoop = None) -> None:
        self.client: ClientType = client
        self._loop: Loop = Helper.ensure_loop(loop)
        self._recording: bool = False
        self._path: Optional[str] = ""

    async def start(self, options: Optional[Dict], **kwargs: Any) -> None:
        opts = Helper.merge_dict(options, kwargs)
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
            {"transferMode": "ReturnAsStream", "categories": ",".join(categories)},
        )

    async def stop(self) -> bytes:
        contentPromise = self._loop.create_future()
        self.client.once(
            "Tracing.tracingComplete", lambda event: contentPromise.set_result(event)
        )
        await self.client.send("Tracing.end", {})
        self._recording = False
        complete_event = await contentPromise
        stream: str = complete_event.get("stream")
        if self._path:
            async with aiofiles.open(self._path, "wb") as out:
                return await self._readStream(stream, out)
        return await self._readStream(stream)

    async def _readStream(self, handle: str, fh: Optional[Any] = None) -> bytes:
        eof = False
        content = bytearray()
        handle_args = {"handle": handle}
        while not eof:
            response = await self.client.send("IO.read", handle_args)
            eof = response.get("eof")
            if response.get("base64Encoded", False):
                data = b64decode(response.get("data"))
            else:
                data = response.get("data").encode("utf-8")
            content += data
            if fh is not None:
                await fh.write(data)

        await self.client.send("IO.close", handle_args)
        return bytes(content)
