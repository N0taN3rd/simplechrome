"""Execut Context Module."""

import math
from typing import Any, Dict, Optional, TYPE_CHECKING, Callable

from . import helper
from .connection import CDPSession
from .errors import ElementHandleError, NetworkError

if TYPE_CHECKING:
    from .element_handle import ElementHandle  # noqa: F401
    from .frame_manager import Frame  # noqa: F401

__all__ = ["ExecutionContext", "JSHandle"]


class ExecutionContext(object):
    """Execution Context class."""

    def __init__(
        self,
        client: CDPSession,
        contextPayload: Dict,
        objectHandleFactory: Callable[..., "JSHandle"],
        frame: Optional["Frame"],
    ) -> None:
        self._client = client
        self._frame = frame
        self._contextId = contextPayload.get("id")

        auxData = contextPayload.get("auxData", {"isDefault": True})
        self._frameId = auxData.get("frameId", None)
        self._isDefault = bool(auxData.get("isDefault"))
        self._objectHandleFactory = objectHandleFactory

    @property
    def frame(self) -> Optional["Frame"]:
        """Return frame associated with this execution context."""
        return self._frame

    async def evaluate(
        self, pageFunction: str, *args: Any, force_expr: bool = False
    ) -> Any:
        """Execute ``pageFunction`` on this context.

        Details see :meth:`pyppeteer.page.Page.evaluate`.
        """
        handle = await self.evaluateHandle(pageFunction, *args, force_expr=force_expr)
        try:
            result = await handle.jsonValue()
        except NetworkError as e:
            if "Object reference chain is too long" in e.args[0]:
                return
            raise
        await handle.dispose()
        return result

    async def evaluateHandle(
        self, pageFunction: str, *args: Any, force_expr: bool = False
    ) -> "JSHandle":
        """Execute ``pageFunction`` on this context.

        Details see :meth:`pyppeteer.page.Page.evaluateHandle`.
        """
        if force_expr or (not args and not helper.is_jsfunc(pageFunction)):
            _obj = await self._client.send(
                "Runtime.evaluate",
                {
                    "expression": pageFunction,
                    "contextId": self._contextId,
                    "returnByValue": False,
                    "awaitPromise": True,
                },
            )
            exceptionDetails = _obj.get("exceptionDetails")
            if exceptionDetails:
                raise ElementHandleError(
                    "Evaluation failed: {}".format(
                        helper.getExceptionMessage(exceptionDetails)
                    )
                )
            remoteObject = _obj.get("result")
            return self._objectHandleFactory(remoteObject)

        _obj = await self._client.send(
            "Runtime.callFunctionOn",
            {
                "functionDeclaration": pageFunction,
                "executionContextId": self._contextId,
                "arguments": [self._convertArgument(arg) for arg in args],
                "returnByValue": False,
                "awaitPromise": True,
            },
        )
        exceptionDetails = _obj.get("exceptionDetails")
        if exceptionDetails:
            raise ElementHandleError(
                "Evaluation failed: {}".format(
                    helper.getExceptionMessage(exceptionDetails)
                )
            )
        remoteObject = _obj.get("result")
        return self._objectHandleFactory(remoteObject)

    def _convertArgument(self, arg: Any) -> Dict:  # noqa: C901
        if arg == math.inf:
            return {"unserializableValue": "Infinity"}
        if arg == -math.inf:
            return {"unserializableValue": "-Infinity"}
        objectHandle = arg if isinstance(arg, JSHandle) else None
        if objectHandle:
            if objectHandle._context != self:
                raise ElementHandleError(
                    "JSHandles can be evaluated only in the context they were created!"
                )  # noqa: E501
            if objectHandle._disposed:
                raise ElementHandleError("JSHandle is disposed!")
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

    async def queryObjects(self, prototypeHandle: "JSHandle") -> "JSHandle":
        """Send query.

        Details see :meth:`pyppeteer.page.Page.queryObjects`.
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
        return self._objectHandleFactory(response.get("objects"))


class JSHandle(object):
    """JSHandle class.

    JSHandle represents an in-page JavaScript object. JSHandle can be created
    with the :meth:`~pyppeteer.page.Page.evaluateHandle` method.
    """

    def __init__(
        self, context: ExecutionContext, client: CDPSession, remoteObject: Dict
    ) -> None:
        self._context = context
        self._client = client
        self._remoteObject = remoteObject
        self._disposed = False

    @property
    def executionContext(self) -> ExecutionContext:
        """Get execution context of this handle."""
        return self._context

    async def getProperty(self, propertyName: str) -> "JSHandle":
        """Get property value of ``propertyName``."""
        objectHandle = await self._context.evaluateHandle(
            """(object, propertyName) => {
                const result = {__proto__: null};
                result[propertyName] = object[propertyName];
                return result;
            }""",
            self,
            propertyName,
        )
        properties = await objectHandle.getProperties()
        result = properties[propertyName]
        await objectHandle.dispose()
        return result

    async def getProperties(self) -> Dict[str, "JSHandle"]:
        """Get all properties of this handle."""
        response = await self._client.send(
            "Runtime.getProperties",
            {"objectId": self._remoteObject.get("objectId", ""), "ownProperties": True},
        )
        result = dict()
        for prop in response["result"]:
            if not prop.get("enumerable"):
                continue
            result[prop.get("name")] = self._context._objectHandleFactory(
                prop.get("value")
            )
        return result

    async def jsonValue(self) -> Dict:
        """Get Jsonized value of this object."""
        objectId = self._remoteObject.get("objectId")
        if objectId:
            response = await self._client.send(
                "Runtime.callFunctionOn",
                {
                    "functionDeclaration": "function() { return this; }",
                    "objectId": objectId,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            )
            return helper.valueFromRemoteObject(response["result"])
        return helper.valueFromRemoteObject(self._remoteObject)

    def asElement(self) -> Optional["ElementHandle"]:
        """Return either null or the object handle itself."""
        return None

    async def dispose(self) -> None:
        """Stop referencing the handle."""
        if self._disposed:
            return
        self._disposed = True
        await helper.releaseObject(self._client, self._remoteObject)

    def toString(self) -> str:
        """Get string representation."""
        if self._remoteObject.get("objectId"):
            _type = self._remoteObject.get("subtype") or self._remoteObject.get("type")
            return f"JSHandle@{_type}"
        return "JSHandle:{}".format(helper.valueFromRemoteObject(self._remoteObject))
