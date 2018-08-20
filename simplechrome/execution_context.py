"""Execut Context Module."""
import copy
from typing import Any, Dict, Optional, TYPE_CHECKING, Union, List

import math
import os

from . import helper
from .connection import CDPSession
from .errors import ElementHandleError, NetworkError
from .util import merge_dict

if TYPE_CHECKING:
    from .page import Page
    from .frame_manager import FrameManager, Frame


__all__ = ["ExecutionContext", "JSHandle", "ElementHandle", "createJSHandle"]


def createJSHandle(
    context: "ExecutionContext", remoteObject: Dict
) -> Union["ElementHandle", "JSHandle"]:
    frame = context.frame
    if remoteObject.get("subtype") == "node" and frame is not None:
        frameManager = frame._frameManager
        return ElementHandle(
            context, context._client, remoteObject, frameManager.page, frameManager
        )
    return JSHandle(context, context._client, remoteObject)


class ExecutionContext(object):
    def __init__(
        self, client: CDPSession, contextPayload: Dict, frame: Optional["Frame"]
    ) -> None:
        self._client = client
        self._frame = frame
        self._contextId = contextPayload.get("id")

        auxData = contextPayload.get("auxData", {"isDefault": True})
        self._frameId = auxData.get("frameId", None)
        self._isDefault = bool(auxData.get("isDefault"))

    @property
    def frame(self):
        return self._frame

    async def evaluate(self, pageFunction: str, *args: Any) -> Any:
        """Execute ``pageFunction`` on this context.

        Details see :meth:`pyppeteer.page.Page.evaluate`.
        """
        handle = await self.evaluateHandle(pageFunction, *args)
        try:
            result = await handle.jsonValue()
        except NetworkError as e:
            if "Object reference chain is too long" in e.args[0]:
                return
            if "Object couldn't be returned by value" in e.args[0]:
                return
            raise
        await handle.dispose()
        return result

    async def evaluateHandle(self, pageFunction: str, *args: Any) -> "JSHandle":
        """Execute ``pageFunction`` on this context.

        Details see :meth:`pyppeteer.page.Page.evaluateHandle`.
        """
        if not helper.is_jsfunc(pageFunction):
            _obj = await self._client.send(
                "Runtime.evaluate",
                {
                    "expression": pageFunction,
                    "contextId": self._contextId,
                    "returnByValue": False,
                    "awaitPromise": True,
                    "userGesture": True,
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
            return createJSHandle(self, remoteObject)

        _obj = await self._client.send(
            "Runtime.callFunctionOn",
            {
                "functionDeclaration": pageFunction,
                "executionContextId": self._contextId,
                "arguments": [self._convertArgument(arg) for arg in args],
                "returnByValue": False,
                "awaitPromise": True,
                "userGesture": True,
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
        return createJSHandle(self, remoteObject)

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
        return createJSHandle(self, response.get("objects"))


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
            result[prop.get("name")] = createJSHandle(self._context, prop.get("value"))
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


def computeQuadArea(quad: List[Dict[str, float]]) -> float:
    area = 0.0
    qlen = len(quad)
    for i in range(0, qlen):
        p1 = quad[i]
        p2 = quad[(i + 1) % qlen]
        area += (p1["x"] * p2["y"] - p2["x"] * p1["y"]) / 2
    return area


class ElementHandle(JSHandle):
    def __init__(
        self,
        context: ExecutionContext,
        client: CDPSession,
        remoteObject: dict,
        page: "Page",
        frameManager: "FrameManager",
    ) -> None:
        super().__init__(context, client, remoteObject)
        self._client = client
        self._remoteObject = remoteObject
        self._page = page
        self._frameManager = frameManager
        self._disposed = False

    def asElement(self) -> "ElementHandle":
        """Return this ElementHandle."""
        return self

    async def contentFrame(self) -> Optional["Frame"]:
        nodeInfo = await self._client.send(
            "DOM.describeNode", {"objectId": self._remoteObject.get("objectId")}
        )
        frameId = nodeInfo.get("node", {}).get("frameId")
        if frameId is None:
            return None
        return self._frameManager.frame(frameId)

    async def _scrollIntoViewIfNeeded(self) -> None:
        error = await self.executionContext.evaluate(
            """async (element, pageJavascriptEnabled) => {
                if (!element.isConnected)
                    return 'Node is detached from document';
                if (element.nodeType !== Node.ELEMENT_NODE)
                    return 'Node is not of type HTMLElement';
                // force-scroll if page's javascript is disabled.
                if (!pageJavascriptEnabled) {
                    element.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
                    return false;
                }
                const visibleRatio = await new Promise(resolve => {
                    const observer = new IntersectionObserver(entries => {
                        resolve(entries[0].intersectionRatio);
                        observer.disconnect();
                    });
                    observer.observe(element);
                });
                if (visibleRatio !== 1.0)
                    element.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
                return false;
            }""",
            self,
            self._page._javascriptEnabled,
        )
        if error:
            raise ElementHandleError(error)

    async def _clickablePoint(self) -> Dict[str, float]:
        try:
            result = await self._client.send(
                "DOM.getContentQuads", dict(objectId=self._remoteObject.get("objectId"))
            )
        except Exception:
            raise Exception("Node is either not visible or not an HTMLElement")

        quads = []
        for pquad in result.get("quads"):
            quad = self._fromProtocolQuad(pquad)
            if computeQuadArea(quad) > 1:
                quads.append(quad)
        if len(quads) == 0:
            raise Exception("Node is either not visible or not an HTMLElement")
        quad = quads[0]
        x = 0.0
        y = 0.0
        for point in quad:
            x += point["x"]
            y += point["y"]
        return dict(x=x / 4, y=y / 4)

    async def _getBoxModel(self) -> Optional[Dict]:
        try:
            result: Optional[Dict] = await self._client.send(
                "DOM.getBoxModel", {"objectId": self._remoteObject.get("objectId")}
            )
        except NetworkError:
            result = None
        return result

    def _fromProtocolQuad(self, quad: List[int]) -> List[Dict[str, float]]:
        return [
            {"x": quad[0], "y": quad[1]},
            {"x": quad[2], "y": quad[3]},
            {"x": quad[4], "y": quad[5]},
            {"x": quad[6], "y": quad[7]},
        ]

    async def _visibleCenter(self) -> Dict[str, float]:
        await self._scrollIntoViewIfNeeded()
        box = await self.boundingBox()
        if not box:
            raise ElementHandleError("Node is not visible.")
        return {"x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2}

    async def _assertBoundingBox(self) -> Dict:
        boundingBox = await self.boundingBox()
        if boundingBox:
            return boundingBox
        raise ElementHandleError("Node is either not visible or not an HTMLElement")

    async def hover(self) -> None:
        """Move mouse over to center of this element.

        If needed, this method scrolls eleemnt into view. If this element is
        detached from DOM tree, the method raises an ``ElementHandleError``.
        """
        await self._scrollIntoViewIfNeeded()
        obj = await self._visibleCenter()
        x = obj.get("x", 0)
        y = obj.get("y", 0)
        await self._page.mouse.move(x, y)

    async def click(self, options: dict = None, **kwargs: Any) -> None:
        """Click the center of this element.

        If needed, this method scrolls element into view. If the element is
        detached from DOM, the method raises ``ElementHandleError``.

        ``options`` can contain the following fields:

        * ``button`` (str): ``left``, ``right``, of ``middle``, defaults to
          ``left``.
        * ``clickCount`` (int): Defaults to 1.
        * ``delay`` (int|float): Time to wait between ``mousedown`` and
          ``mouseup`` in milliseconds. Defaults to 0.
        """
        options = merge_dict(options, kwargs)
        await self._scrollIntoViewIfNeeded()
        obj = await self._visibleCenter()
        x = obj.get("x", 0)
        y = obj.get("y", 0)
        await self._page.mouse.click(x, y, options)

    async def uploadFile(self, *filePaths: str) -> Dict:
        """Upload files."""
        files = [os.path.abspath(p) for p in filePaths]
        objectId = self._remoteObject.get("objectId")
        return await self._client.send(
            "DOM.setFileInputFiles", {"objectId": objectId, "files": files}
        )

    async def tap(self) -> None:
        """Tap the center of this element.

        If needed, this method scrolls element into view. If the element is
        detached from DOM, the method raises ``ElementHandleError``.
        """
        await self._scrollIntoViewIfNeeded()
        center = await self._visibleCenter()
        x = center.get("x", 0)
        y = center.get("y", 0)
        await self._page.touchscreen.tap(x, y)

    async def focus(self) -> None:
        """Focus on this element."""
        await self.executionContext.evaluate("element => element.focus()", self)

    async def type(self, text: str, options: Dict = None, **kwargs: Any) -> None:
        """Focus the element and then type text.

        Details see :meth:`pyppeteer.input.Keyboard.type` method.
        """
        options = merge_dict(options, kwargs)
        await self.focus()
        await self._page.keyboard.type(text, options)

    async def press(self, key: str, options: Dict = None, **kwargs: Any) -> None:
        """Press ``key`` onto the element.

        This method focuses the element, and then uses
        :meth:`pyppeteer.input.keyboard.down` and
        :meth:`pyppeteer.input.keyboard.up`.

        :arg str key: Name of key to press, such as ``ArrowLeft``.

        This method accepts the following options:

        * ``text`` (str): If specified, generates an input event with this
          text.
        * ``delay`` (int|float): Time to wait between ``keydown`` and
          ``keyup``. Defaults to 0.
        """
        options = merge_dict(options, kwargs)
        await self.focus()
        await self._page.keyboard.press(key, options)

    async def boundingBox(self) -> Optional[Dict[str, float]]:
        """Return bounding box of this element.

        If the element is not visible, return ``None``.

        This method returns dictionary of bounding box, which contains:

        * ``x`` (int): The X coordinate of the element in pixels.
        * ``y`` (int): The Y coordinate of the element in pixels.
        * ``width`` (int): The width of the element in pixels.
        * ``height`` (int): The height of the element in pixels.
        """
        result = await self._getBoxModel()
        if not result:
            return None

        quad = result["model"]["border"]
        x = min(quad[0], quad[2], quad[4], quad[6])
        y = min(quad[1], quad[3], quad[5], quad[7])
        width = max(quad[0], quad[2], quad[4], quad[6]) - x
        height = max(quad[1], quad[3], quad[5], quad[7]) - y
        return {"x": x, "y": y, "width": width, "height": height}

    async def boxModel(self) -> Optional[Dict[str, Union[int, List[Dict[str, float]]]]]:
        """Return boxes of element.
        Return ``None`` if element is not visivle. Boxes are represented as an
        list of dictionaries, {x, y} for each point, points clock-wise as
        below:
        Returned value is a dictionary with the following fields:
        * ``content`` (List[Dict]): Content box.
        * ``padding`` (List[Dict]): Padding box.
        * ``border`` (List[Dict]): Border box.
        * ``margin`` (List[Dict]): Margin box.
        * ``width`` (int): Element's width.
        * ``heidht`` (int): Element's height.
        """
        result = await self._getBoxModel()

        if not result:
            return None

        model = result.get("model", {})
        return {
            "content": self._fromProtocolQuad(model.get("content")),
            "padding": self._fromProtocolQuad(model.get("padding")),
            "border": self._fromProtocolQuad(model.get("border")),
            "margin": self._fromProtocolQuad(model.get("margin")),
            "width": model.get("width"),
            "height": model.get("height"),
        }

    async def screenshot(self, options: Dict = None, **kwargs: Any) -> bytes:
        """Take a screenshot of this element.

        If the element is detached from DOM, this method raises an
        ``ElementHandleError``.

        Available options are same as :meth:`pyppeteer.page.Page.screenshot`.
        """
        options = merge_dict(options, kwargs)

        needsViewportReset = False
        boundingBox = await self.boundingBox()
        original_viewport = copy.deepcopy(self._page.viewport)

        if (
            boundingBox["width"] > original_viewport["width"]
            or boundingBox["height"] > original_viewport["height"]
        ):
            newViewport = {
                "width": max(
                    original_viewport["width"], math.ceil(boundingBox["width"])
                ),
                "height": max(
                    original_viewport["height"], math.ceil(boundingBox["height"])
                ),
            }
            new_viewport = copy.deepcopy(original_viewport)
            new_viewport.update(newViewport)
            await self._page.setViewport(new_viewport)
            needsViewportReset = True

        await self._scrollIntoViewIfNeeded()

        boundingBox = await self.boundingBox()
        _obj = await self._client.send("Page.getLayoutMetrics")
        pageX = _obj["layoutViewport"]["pageX"]
        pageY = _obj["layoutViewport"]["pageY"]

        clip: Dict[str, float] = {}
        clip.update(boundingBox)
        clip["x"] = clip["x"] + pageX
        clip["y"] = clip["y"] + pageY
        opt = {"clip": clip}
        opt.update(options)
        imageData = await self._page.screenshot(opt)

        if needsViewportReset:
            await self._page.setViewport(original_viewport)

        return imageData

    async def querySelector(self, selector: str) -> Optional["ElementHandle"]:
        """Return first element which matches ``selector`` under this element.

        If no element mathes the ``selector``, returns ``None``.
        """
        handle = await self.executionContext.evaluateHandle(
            "(element, selector) => element.querySelector(selector)", self, selector
        )
        element = handle.asElement()
        if element:
            return element
        await handle.dispose()
        return None

    async def querySelectorAll(self, selector: str) -> List["ElementHandle"]:
        """Return all elements which match ``selector`` under this element.

        If no element matches the ``selector``, returns empty list (``[]``).
        """
        arrayHandle = await self.executionContext.evaluateHandle(
            "(element, selector) => Array.from(element.querySelectorAll(selector))",
            self,
            selector,
        )
        properties = await arrayHandle.getProperties()
        await arrayHandle.dispose()
        result = []
        for prop in properties.values():
            elementHandle = prop.asElement()
            if elementHandle:
                result.append(elementHandle)
        return result

    #: alias to :meth:`querySelector`
    J = querySelector
    #: alias to :meth:`querySelectorAll`
    JJ = querySelectorAll

    async def xpath(self, expression: str) -> List["ElementHandle"]:
        """Evaluate XPath expression relative to this elementHandle.

        If there is no such element, return None.

        :arg str expression: XPath string to be evaluated.
        """
        arrayHandle = await self.executionContext.evaluateHandle(
            """(element, expression) => {
                const document = element.ownerDocument || element;
                const iterator = document.evaluate(expression, element, null, XPathResult.ORDERED_NODE_ITERATOR_TYPE);
                const array = [];
                let item;
                while ((item = iterator.iterateNext()))
                    array.push(item);
                return array;

            }""",
            self,
            expression,
        )
        properties = await arrayHandle.getProperties()
        await arrayHandle.dispose()
        result = []
        for prop in properties.values():
            elementHandle = prop.asElement()
            if elementHandle:
                result.append(elementHandle)
        return result

    #: alias to :meth:`xpath`
    Jx = xpath
