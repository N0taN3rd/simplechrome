"""ExecutionContext Context Module."""
import re
from typing import Any, Awaitable, Dict, List, Optional, Pattern, TYPE_CHECKING

import math

from ._typings import AsyncAny, CoAny, SlotsT
from .connection import ClientType
from .domWorld import DOMWorld
from .errors import EvaluationError
from .helper import Helper
from .jsHandle import ElementHandle, JSHandle, createJSHandle

if TYPE_CHECKING:
    from .frame_manager import Frame  # noqa: F401

__all__ = ["ExecutionContext", "EVALUATION_SCRIPT_URL"]

EVALUATION_SCRIPT_URL: str = "__simplechrome_evaluation_script__"
SOURCE_URL_REGEX: Pattern = re.compile(
    r"^[\040\t]*//[@#] sourceURL=\s*(\S*)?\s*$", re.MULTILINE
)
suffix = f"//# sourceURL={EVALUATION_SCRIPT_URL}"


class ExecutionContext:
    __slots__: SlotsT = [
        "__weakref__",
        "_client",
        "_contextPayload",
        "_world",
        "_contextId",
        "_isDefault",
    ]

    def __init__(
        self, client: ClientType, contextPayload: Dict, world: Optional[DOMWorld] = None
    ) -> None:
        self._client: ClientType = client
        self._contextPayload: Dict = contextPayload
        self._world: Optional[DOMWorld] = world
        self._contextId: str = self._contextPayload.get("id")
        self._isDefault: bool = self._contextPayload.get("auxData", {}).get(
            "isDefault", False
        )

    @property
    def default(self) -> bool:
        return self._isDefault

    @property
    def contextId(self) -> str:
        return self._contextId

    @property
    def frame(self) -> Optional["Frame"]:
        return self._world.frame if self._world is not None else None

    def evaluate(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> CoAny:
        """Execute ``pageFunction`` on this context.

        Details see :meth:`simplechrome.page.Page.evaluate`.
        """
        return self._evaluateInternal(pageFunction, *args, withCliAPI=withCliAPI)

    def evaluateHandle(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> Awaitable[JSHandle]:
        """Execute ``pageFunction`` on this context.

        Details see :meth:`simplechrome.page.Page.evaluateHandle`.
        """
        return self._evaluateInternal(
            pageFunction, *args, withCliAPI=withCliAPI, returnByValue=False
        )

    def evaluate_expression(
        self, expression: str, withCliAPI: bool = False
    ) -> CoAny:
        return self._evaluateInternal(expression, withCliAPI=withCliAPI)

    async def queryObjects(self, prototypeHandle: JSHandle) -> JSHandle:
        """Send query.

        Details see :meth:`simplechrome.page.Page.queryObjects`.
        """
        if prototypeHandle._disposed:
            raise Exception("Prototype JSHandle is disposed!")
        if not prototypeHandle._remoteObject.get("objectId"):
            raise Exception(
                "Prototype JSHandle must not be referencing primitive value"
            )
        response = await self._client.send(
            "Runtime.queryObjects",
            {"prototypeObjectId": prototypeHandle._remoteObject["objectId"]},
        )
        return createJSHandle(self, response.get("objects"))

    async def globalLexicalScopeNames(self) -> List[str]:
        """Returns all let, const and class variables from the global scope"""
        results = await self._client.send(
            "Runtime.globalLexicalScopeNames", {"executionContextId": self._contextId}
        )
        return results.get("names")

    def globalObject(self) -> Awaitable[JSHandle]:
        return self._evaluateInternal("() => self")

    async def _evaluateInternal(
        self,
        pageFunction: str,
        *args: Any,
        withCliAPI: bool = False,
        returnByValue: bool = True,
    ) -> CoAny:
        if not Helper.is_jsfunc(pageFunction):
            expression_with_source_url = (
                pageFunction
                if SOURCE_URL_REGEX.match(pageFunction) is not None
                else f"{pageFunction}\n{suffix}"
            )
            try:
                _obj = await self._client.send(
                    "Runtime.evaluate",
                    {
                        "expression": expression_with_source_url,
                        "contextId": self._contextId,
                        "awaitPromise": True,
                        "userGesture": True,
                        "includeCommandLineAPI": withCliAPI,
                        "returnByValue": returnByValue,
                    },
                )
            except Exception as e:
                _obj = rewrite_error(e)
            exceptionDetails = _obj.get("exceptionDetails")
            if exceptionDetails:
                raise EvaluationError(
                    f"Evaluation failed: {Helper.getExceptionMessage(exceptionDetails)}"
                )
            remoteObject = _obj.get("result")
            return (
                Helper.valueFromRemoteObject(remoteObject)
                if returnByValue
                else createJSHandle(self, remoteObject)
            )

        try:
            _obj = await self._client.send(
                "Runtime.callFunctionOn",
                {
                    "functionDeclaration": f"{pageFunction}\n{suffix}\n",
                    "executionContextId": self._contextId,
                    "arguments": [self._convertArgument(arg) for arg in args],
                    "userGesture": True,
                    "awaitPromise": True,
                    "includeCommandLineAPI": withCliAPI,
                    "returnByValue": returnByValue,
                },
            )
        except Exception as e:
            msg = str(e)
            if msg == "Converting circular structure to JSON":
                raise Exception(f"{msg} Are you passing a nested JSHandle?")
            raise e
        exceptionDetails = _obj.get("exceptionDetails")
        if exceptionDetails:
            raise Exception(
                f"Evaluation failed: {Helper.getExceptionMessage(exceptionDetails)}"
            )
        remoteObject = _obj.get("result")
        return (
            Helper.valueFromRemoteObject(remoteObject)
            if returnByValue
            else createJSHandle(self, remoteObject)
        )

    def _convertArgument(self, arg: Any) -> Dict:  # noqa: C901
        if arg == -0:
            return {"unserializableValue": "-0"}
        if arg == math.inf:
            return {"unserializableValue": "Infinity"}
        if arg == -math.inf:
            return {"unserializableValue": "-Infinity"}
        objectHandle = arg if isinstance(arg, JSHandle) else None
        if objectHandle:
            if objectHandle._context is not self:
                raise Exception(
                    "JSHandles can be evaluated only in the context they were created!"
                )  # noqa: E501
            if objectHandle._disposed:
                raise Exception("JSHandle is disposed!")
            if objectHandle._remoteObject.get("unserializableValue"):
                return {
                    "unserializableValue": objectHandle._remoteObject.get(
                        "unserializableValue"
                    )
                }  # noqa: E501
            if not objectHandle._remoteObject.get("objectId"):
                return {"value": objectHandle._remoteObject.get("value")}
            return {"objectId": objectHandle._remoteObject.get("objectId")}
        return {"value": arg}

    async def _adoptElementHandle(self, elementHandle: ElementHandle) -> ElementHandle:
        if elementHandle.executionContext is self:
            raise Exception(
                "Cannot adopt handle that already belongs to this execution context"
            )
        nodeInfo = await self._client.send(
            "DOM.describeNode", {"objectId": elementHandle._remoteObject["objectId"]}
        )

        resolvedNode = await self._client.send(
            "DOM.resolveNode",
            {
                "backendNodeId": nodeInfo.get("node").get("backendNodeId"),
                "executionContextId": self._contextId,
            },
        )
        return createJSHandle(self, resolvedNode.get("object")).asElement()

    def __str__(self) -> str:
        frame_id = f"frameId={self.frame.id}, " if self.frame else ""
        return f"ExecutionContext(contextId={self._contextId}, {frame_id}isDefault={self._isDefault})"

    def __repr__(self) -> str:
        return self.__str__()


def rewrite_error(error: Exception) -> Dict:
    msg = str(error)
    if "Object reference chain is too long" in msg:
        return {"result": {"type": "undefined"}}
    if "Object couldn't be returned by value" in msg:
        return {"result": {"type": "undefined"}}
    if msg.endswith("Cannot find context with specified id"):
        raise Exception(
            "Execution context was destroyed, most likely because of a navigation"
        )
    raise error
