from typing import Dict, List, Optional

from ._typings import CDPEvent, JHandleFact, Number
from .execution_context import ExecutionContext
from .helper import Helper
from .jsHandle import JSHandle, createJSHandle

__all__ = ["ConsoleMessage"]


class ConsoleMessage:
    """Console message class.

    ConsoleMessage objects are dispatched by page via the ``console`` event.
    """

    __slots__: List[str] = ["_args", "_event", "_location", "_text"]

    def __init__(
        self,
        event: CDPEvent,
        context: Optional[ExecutionContext] = None,
        jsHandleFactory: Optional[JHandleFact] = None,
    ) -> None:
        """Initialize a new Log instance

        :param event: The CDP event object for Runtime.consoleAPICalled
        :param context: Optional context to be used to convert args
        :param jsHandleFactory: Optional JSHandle factory function for converting args
        """
        self._event: CDPEvent = event
        self._args: List[JSHandle] = []
        self._text: str = ""
        self._location: Optional[Dict] = None
        self.__init(context, jsHandleFactory)

    @property
    def type(self) -> str:
        """Type of the call

        One of:
          - log
          - debug
          - info
          - error
          - warning
          - dir
          - dirxml
          - table
          - trace
          - clear
          - startGroup
          - startGroupCollapsed
          - endGroup
          - assert
          - profile
          - profileEnd
          - count
          - timeEnd
        """
        return self._event.get("type", "")

    @property
    def text(self) -> str:
        """The message logged to the console"""
        return self._text

    @property
    def args(self) -> List[JSHandle]:
        """The arguments used to produce this message"""
        return self._args

    @property
    def location(self) -> Optional[Dict]:
        """Where did this console message occur"""
        return self._location

    @property
    def timestamp(self) -> Number:
        """Call timestamp"""
        return self._event.get("timestamp")

    @property
    def executionContextId(self) -> str:
        """Identifier of the context where the call was made"""
        return self._event.get("event", {}).get("executionContextId", "")

    @property
    def stackTrace(self) -> Optional[Dict]:
        """JavaScript stack trace"""
        return self._event.get("stackTrace")

    @property
    def consoleContext(self) -> Optional[str]:
        """
        Console context descriptor for calls on non-default console context (not console.*):
          - 'anonymous#unique-logger-id' for call on unnamed context, 'name#unique-logger-id'
             for call on named context
        """
        return self._event.get("event", {}).get("executionContextId", "")

    def __init(
        self,
        context: Optional[ExecutionContext] = None,
        jsHandleFactory: Optional[JHandleFact] = None,
    ) -> None:
        call_frames: List[Dict] = self._event.get("stackTrace", {}).get(
            "call_frames", []
        )
        if call_frames:
            self._location = {
                "url": call_frames[0].get("url"),
                "lineNumber": call_frames[0].get("lineNumber"),
                "columnNumber": call_frames[0].get("columnNumber"),
            }
        args: List[Dict] = self._event.get("args")
        if args:
            text_tokens: List[str] = []
            add_tt = text_tokens.append
            add_arg = self._args.append
            for arg in args:
                handle = (
                    createJSHandle(context, arg) if context else jsHandleFactory(arg)
                )
                add_arg(handle)
                remote_object = handle._remoteObject
                if remote_object.get("objectId"):
                    add_tt(handle.toString())
                else:
                    add_tt(Helper.valueFromRemoteObject(remote_object))
            self._text = " ".join(text_tokens)

    def __str__(self) -> str:
        return f"ConsoleMessage(type={self.type}, message={self._text})"

    def __repr__(self) -> str:
        return self.__str__()
