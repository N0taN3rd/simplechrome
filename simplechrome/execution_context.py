"""ExecutionContext Context Module."""
import math
import re
from typing import Any, Dict, Optional, Pattern, TYPE_CHECKING

import attr

from .connection import ClientType
from .domWorld import DOMWorld
from .errors import ElementHandleError, EvaluationError, ProtocolError
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


@attr.dataclass(slots=True, str=False, cmp=False)
class ExecutionContext:
    _client: ClientType = attr.ib()
    _contextPayload: Dict = attr.ib()
    _world: Optional[DOMWorld] = attr.ib()
    _contextId: str = attr.ib(init=False)
    _isDefault: bool = attr.ib(init=False)

    @property
    def default(self) -> bool:
        return self._isDefault

    @property
    def contextId(self) -> str:
        return self._contextId

    @property
    def frame(self) -> Optional["Frame"]:
        return self._world.frame if self._world is not None else None

    async def evaluate(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> Any:
        """Execute ``pageFunction`` on this context.

        Details see :meth:`simplechrome.page.Page.evaluate`.
        """
        handle = await self.evaluateHandle(pageFunction, *args, withCliAPI=withCliAPI)
        try:
            result = await handle.jsonValue()
        except ProtocolError as e:
            if "Object reference chain is too long" in e.args[0]:
                return
            if "Object couldn't be returned by value" in e.args[0]:
                return
            raise EvaluationError(e.args[0])
        await handle.dispose()
        return result

    async def evaluateHandle(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> "JSHandle":
        """Execute ``pageFunction`` on this context.

        Details see :meth:`simplechrome.page.Page.evaluateHandle`.
        """
        if withCliAPI or not Helper.is_jsfunc(pageFunction):
            expression_with_source_url = (
                pageFunction
                if SOURCE_URL_REGEX.match(pageFunction) is not None
                else f"{pageFunction}\n{suffix}"
            )
            _obj = await self._client.send(
                "Runtime.evaluate",
                {
                    "expression": expression_with_source_url,
                    "contextId": self._contextId,
                    "returnByValue": False,
                    "awaitPromise": True,
                    "userGesture": True,
                    "includeCommandLineAPI": withCliAPI,
                },
            )
            exceptionDetails = _obj.get("exceptionDetails")
            if exceptionDetails:
                raise EvaluationError(
                    "Evaluation failed: {}".format(
                        Helper.getExceptionMessage(exceptionDetails)
                    )
                )
            remoteObject = _obj.get("result")
            return createJSHandle(self, remoteObject)

        _obj = await self._client.send(
            "Runtime.callFunctionOn",
            {
                "functionDeclaration": f"{pageFunction}\n{suffix}\n",
                "executionContextId": self._contextId,
                "arguments": [self._convertArgument(arg) for arg in args],
                "returnByValue": False,
                "awaitPromise": True,
                "userGesture": True,
            },
        )
        exceptionDetails = _obj.get("exceptionDetails")
        if exceptionDetails:
            raise EvaluationError(
                "Evaluation failed: {}".format(
                    Helper.getExceptionMessage(exceptionDetails)
                )
            )
        remoteObject = _obj.get("result")
        return createJSHandle(self, remoteObject)

    async def evaluate_expression(
        self, expression: str, withCliAPI: bool = False
    ) -> Any:
        results = await self._client.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "contextId": self._contextId,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
                "includeCommandLineAPI": withCliAPI,
            },
        )
        exceptionDetails = results.get("exceptionDetails")
        if exceptionDetails:
            raise EvaluationError(
                "Evaluation failed: {}".format(
                    Helper.getExceptionMessage(exceptionDetails)
                )
            )
        return Helper.valueFromRemoteObject(results["result"])

    async def queryObjects(self, prototypeHandle: "JSHandle") -> "JSHandle":
        """Send query.

        Details see :meth:`simplechrome.page.Page.queryObjects`.
        """
        if prototypeHandle._disposed:
            raise ElementHandleError("Prototype JSHandle is disposed!")
        if not prototypeHandle._remoteObject.get("objectId"):
            raise ElementHandleError(
                "Prototype JSHandle must not be referencing primitive value"
            )
        response = await self._client.send(
            "Runtime.queryObjects",
            {"prototypeObjectId": prototypeHandle._remoteObject["objectId"]},
        )
        return createJSHandle(self, response.get("objects"))

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

    def __attrs_post_init__(self) -> None:
        self._contextId = self._contextPayload.get("id")
        self._isDefault = self._contextPayload.get("auxData", {}).get(
            "isDefault", False
        )
