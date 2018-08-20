# -*- coding: utf-8 -*-
import asyncio
import logging
import ujson as json
from asyncio import Future
from concurrent.futures import CancelledError
from typing import Optional, Dict, Callable, Any

import websockets
import websockets.protocol
from pyee import EventEmitter
from websockets import WebSocketClientProtocol

from .errors import NetworkError

__all__ = ["Connection", "CDPSession"]

logger = logging.getLogger(__name__)


def createProtocolError(method, msg) -> str:
    error = msg["error"]
    data = error.get("data")
    emsg = f"Protocol Error ({method}): {error.get('message')}"
    if data:
        emsg += f" {data}"
    return emsg


class Connection(EventEmitter):
    """Websocket Connection To The Remote Browser"""

    def __init__(self, url: str, delay: int = 0, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._url: str = url
        self._lastId: int = 0
        self._callbacks: Dict[int, Future] = dict()
        self._delay: int = delay
        self._sessions: Dict[str, CDPSession] = dict()
        self.connected: bool = False
        self._ws: WebSocketClientProtocol = None
        self._recv_fut: Optional[Future] = None
        self._closeCallback: Optional[Callable[[], None]] = None
        self._loop = asyncio.get_event_loop()

    @property
    def url(self) -> str:
        """Get connected WebSocket url."""
        return self._url

    @staticmethod
    async def createForWebSocket(url: str, delay: int = 0) -> "Connection":
        con = Connection(url, delay)
        await con.connect()
        return con

    async def connect(self) -> None:
        self._ws = await websockets.client.connect(
            self._url,
            compression=None,
            max_queue=0,
            timeout=20,
            read_limit=2 ** 25,
            write_limit=2 ** 25,
        )
        self._recv_fut = asyncio.ensure_future(self._recv_loop(), loop=self._loop)

    async def _recv_loop(self) -> None:
        self.connected = True
        while self.connected:
            try:
                resp = await self._ws.recv()
                if resp:
                    self._on_message(resp)
            except (websockets.ConnectionClosed, ConnectionResetError) as e:
                logger.info("connection closed")
                break
        if self.connected:
            await self.dispose()

    def send(self, method: str = None, params: dict = None) -> Future:
        if self._lastId and not self.connected:
            raise ConnectionError("Connection is closed")
        if params is None:
            params = dict()
        self._lastId += 1
        _id = self._lastId
        msg = json.dumps(dict(method=method, params=params, id=_id))
        asyncio.ensure_future(self._send_async(msg, _id), loop=self._loop)
        callback = self._loop.create_future()
        self._callbacks[_id] = callback
        callback.method = method  # type: ignore
        return callback

    async def _send_async(self, msg: str, callback_id: int) -> None:
        while not self.connected:
            await asyncio.sleep(0)

        try:
            await self._ws.send(msg)
        except websockets.ConnectionClosed:
            logger.error("connection unexpectedly closed")
            callback = self._callbacks.get(callback_id, None)
            if callback and not callback.done():
                callback.set_result(None)
                await self.dispose()

    async def dispose(self) -> None:
        """Close all connection."""
        self.connected = False
        await self._on_close()

    async def createSession(self, targetId: str) -> "CDPSession":
        """Create new session."""
        resp = await self.send("Target.attachToTarget", {"targetId": targetId})
        sessionId = resp.get("sessionId")
        session = CDPSession(self, targetId, sessionId)
        self._sessions[sessionId] = session
        return session

    def set_close_callback(self, callback: Callable[[], None]) -> None:
        """Set closed callback."""
        self._closeCallback = callback

    def _on_message(self, message: str) -> None:
        msg = json.loads(message)
        if msg.get("id") in self._callbacks:
            self._on_response(msg)
        else:
            self._on_unsolicited(msg)

    def _on_response(self, msg: dict) -> None:
        callback = self._callbacks.pop(msg.get("id", -1))
        if callback and not callback.done():
            if "error" in msg:
                callback.set_exception(
                    NetworkError(createProtocolError(callback.method, msg))
                )
            else:
                callback.set_result(msg.get("result"))

    def _on_unsolicited(self, msg: dict) -> None:
        params = msg.get("params", {})
        method = msg.get("method", "")
        try:
            sessionId = params.get("sessionId")
            if method == "Target.receivedMessageFromTarget":
                session = self._sessions.get(sessionId)
                if session:
                    session.on_message(params.get("message"))
            elif method == "Target.detachedFromTarget":
                session = self._sessions.get(sessionId)
                if session:
                    session.on_closed()
                    del self._sessions[sessionId]
            else:
                self.emit(method, params)
        except Exception as e:
            import traceback

            traceback.print_exc()
            print("_on_unsolicited error", e)
            print("_on_unsolicited error", params)

    async def _on_close(self) -> None:
        if self._closeCallback:
            self._closeCallback()
            self._closeCallback = None

        for cb in self._callbacks.values():
            cb.cancel()
        self._callbacks.clear()

        for session in self._sessions.values():
            session.on_closed()
        self._sessions.clear()

        # close connection
        if not self._recv_fut.done():
            self._recv_fut.cancel()

        try:
            await self._ws.close()
        except:
            pass


class CDPSession(EventEmitter):
    def __init__(
        self,
        connection: Optional[Connection],
        targetId: str,
        sessionId: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Make new session."""
        super().__init__()
        self._lastId: int = 0
        self._callbacks: Dict[int, Future] = {}
        self._connection: Optional[Connection] = connection
        self._targetId: str = targetId
        self._sessionId: str = sessionId
        self._sessions: Dict[str, CDPSession] = dict()

    async def send(self, method: str, params: Optional[dict] = None) -> Any:
        """Send message to the connected session.
        :arg str method: Protocol method name.
        :arg dict params: Optional method parameters.
        """
        self._lastId += 1
        _id = self._lastId
        msg = json.dumps(dict(id=_id, method=method, params=params))

        callback = asyncio.get_event_loop().create_future()
        self._callbacks[_id] = callback
        callback.method = method

        if not self._connection:
            raise NetworkError("Connection closed.")
        try:
            await self._connection.send(
                "Target.sendMessageToTarget",
                {"sessionId": self._sessionId, "message": msg},
            )
        except CancelledError:
            raise NetworkError("connection unexpectedly closed")
        return await callback

    async def detach(self) -> None:
        """Detach session from target.
        Once detached, session won't emit any events and can't be used to send
        messages.
        """
        if not self._connection:
            raise NetworkError("Connection already closed.")
        await self._connection.send(
            "Target.detachFromTarget", {"sessionId": self._sessionId}
        )

    def create_session(self, targetId: str, sessionId: str) -> "CDPSession":
        sesh = CDPSession(self._connection, targetId, sessionId)
        self._sessions[sessionId] = sesh
        return sesh

    def on_message(self, message: str) -> None:
        # print('CDPSession.on_message', message)
        msg = json.loads(message)
        _id = msg.get("id")
        if _id and _id in self._callbacks:
            callback = self._callbacks.pop(_id)
            if "error" in msg:
                callback.set_exception(
                    NetworkError(createProtocolError(callback.method, msg))
                )
            else:
                result = msg.get("result")
                if callback and not callback.done():
                    callback.set_result(result)
        else:
            self.emit(msg.get("method"), msg.get("params"))

    def on_closed(self) -> None:
        for cb in self._callbacks.values():
            cb.cancel()
        self._callbacks.clear()
        self._connection = None
