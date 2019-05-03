from asyncio import AbstractEventLoop
from typing import Dict, List, Optional, Union

from pyee2 import EventEmitterS

from ._typings import CDPEvent, Number
from .connection import ClientType
from .helper import Helper
from .events import LogEvents

__all__ = ["Log", "LogEntry"]

ViolationSetting = Dict[str, Union[str, Number]]


class Log(EventEmitterS):
    """Provides access to log entries"""

    __slots__: List[str] = [
        "__weakref__",
        "_client",
        "_enabled",
        "_reporting_violations",
    ]

    def __init__(
        self, client: ClientType, loop: Optional[AbstractEventLoop] = None
    ) -> None:
        """Initialize a new Log instance

        :param loop: Optional EventLoop instance to use
        """
        super().__init__(Helper.ensure_loop(loop))
        self._client: ClientType = client
        self._enabled: bool = False
        self._reporting_violations: bool = False
        self._client.on("Log.entryAdded", self._onLogEntryAdded)

    @property
    def enabled(self) -> bool:
        """Is the domain enabled"""
        return self._enabled

    @property
    def reporting_violations(self) -> bool:
        """Are violations being reported"""
        return self._reporting_violations

    async def enable(self) -> None:
        """Enables log domain, sends the entries collected so far
        to the client by means of the entryAdded notification
        """
        if self._enabled:
            return
        await self._client.send("Log.enable", {})
        self._enabled = True

    async def disable(self) -> None:
        """Disables log domain, prevents further log entries from
        being reported to the client.
        """
        if not self._enabled:
            return
        await self._client.send("Log.disable", {})
        self._enabled = False

    async def clear(self) -> None:
        """Clears the log"""
        await self._client.send("Log.clear", {})

    async def startViolationsReport(self, config: List[ViolationSetting]) -> None:
        """Start violation reporting

        ViolationSetting properties:
          - name: The violation type, one of longTask, longLayout, blockedEvent,
            blockedParser, discouragedAPIUse, handler, recurringHandler
          - threshold: Time threshold to trigger upon

        :param config: List of violation settings used to configure violation reporting
        """
        self._reporting_violations = True
        await self._client.send("Log.startViolationsReport", {"config": config})

    async def stopViolationsReport(self) -> None:
        """Stop violation reporting"""
        self._reporting_violations = False
        await self._client.send("Log.stopViolationsReport", {})

    def _onLogEntryAdded(self, event: CDPEvent) -> None:
        entry = event.get("entry")
        args = entry.get("args")
        if args is not None:
            self._loop.create_task(self._release_log_args(args))
        self.emit(LogEvents.EntryAdded, LogEntry(entry))

    async def _release_log_args(self, args: List[Dict]) -> None:
        for arg in args:
            await Helper.releaseObject(self._client, arg)

    def __str__(self) -> str:
        return f"Log(enabled={self._enabled}, reporting_violations={self._reporting_violations})"

    def __repr__(self) -> str:
        return self.__str__()


class LogEntry:
    """An abstraction around Log.LogEntry"""

    __slots__: List[str] = ["_entry", "_location"]

    def __init__(self, entry: Dict) -> None:
        """Initialize a new LogEntry

        :param entry: The value for the log entry sent by the CDP
        """
        self._entry: Dict = entry
        self._location: Optional[Dict] = None
        call_frames: List[Dict] = self._entry.get("stackTrace", {}).get(
            "call_frames", []
        )
        if call_frames:
            self._location = {
                "url": call_frames[0].get("url"),
                "lineNumber": call_frames[0].get("lineNumber"),
                "columnNumber": call_frames[0].get("columnNumber"),
            }

    @property
    def cdp_entry(self) -> Dict:
        """The value for the log entry sent by the CDP"""
        return self._entry

    @property
    def level(self) -> str:
        """Log entry severity

        Potential values:
            - verbose
            - info
            - warning
            - error
        """
        return self._entry.get("level")

    @property
    def lineNumber(self) -> Optional[int]:
        """Line number in the resource"""
        return self._entry.get("lineNumber")

    @property
    def location(self) -> Optional[Dict[str, Union[str, int]]]:
        """Where did this log entry message occur"""
        return self._location

    @property
    def networkRequestId(self) -> Optional[str]:
        """Identifier of the network request associated with this entry"""
        return self._entry.get("networkRequestId")

    @property
    def stackTrace(self) -> Optional[Dict]:
        """JavaScript stack trace"""
        return self._entry.get("stackTrace")

    @property
    def source(self) -> str:
        """Log entry source

        Potential values:
           - xml
           - javascript
           - network
           - storage
           - appcache
           - rendering
           - security
           - deprecation
           - worker
           - violation
           - intervention
           - recommendation
           - other
        """
        return self._entry.get("source")

    @property
    def timestamp(self) -> Optional[Number]:
        """Timestamp when this entry was added"""
        return self._entry.get("timestamp")

    @property
    def type(self) -> str:
        """Type of the entry"""
        return self.level

    @property
    def url(self) -> Optional[str]:
        """URL of the resource if known"""
        return self._entry.get("url")

    @property
    def workerId(self) -> Optional[str]:
        """Identifier of the worker associated with this entry"""
        return self._entry.get("workerId")

    def __str__(self) -> str:
        return f"LogEntry(entry={self._entry})"

    def __repr__(self) -> str:
        return self.__str__()
