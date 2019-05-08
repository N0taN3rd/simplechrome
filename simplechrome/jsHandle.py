import copy
import os
from asyncio import gather
from typing import Any, Awaitable, Dict, List, Optional, TYPE_CHECKING, Union

import math

from ._typings import Number, SlotsT
from .connection import ClientType
from .helper import Helper

if TYPE_CHECKING:
    from .execution_context import ExecutionContext  # noqa: F401
    from .frame_manager import FrameManager, Frame  # noqa: F401
    from .page import Page  # noqa: F401

__all__ = ["JSHandle", "ElementHandle", "createJSHandle"]


def createJSHandle(
    context: "ExecutionContext", remoteObject: Dict
) -> Union["ElementHandle", "JSHandle"]:
    frame = context.frame
    if remoteObject.get("subtype") == "node" and frame:
        frameManager = frame._frameManager
        return ElementHandle(
            context, context._client, remoteObject, frameManager.page, frameManager
        )
    return JSHandle(context, context._client, remoteObject)


class JSHandle:
    __slots__: SlotsT = [
        "__weakref__",
        "_context",
        "_client",
        "_remoteObject",
        "_disposed",
    ]

    @classmethod
    def create(cls, context: "ExecutionContext", remoteObject: Dict) -> "JSHandle":
        return cls(context, context._client, remoteObject)

    def __init__(
        self, context: "ExecutionContext", client: ClientType, remoteObject: Dict
    ) -> None:
        self._context = context
        self._client = client
        self._remoteObject = remoteObject
        self._disposed = False

    @property
    def executionContext(self) -> "ExecutionContext":
        """Get execution context of this handle."""
        return self._context

    def asElement(self) -> Optional["ElementHandle"]:
        """Return either null or the object handle itself."""
        if isinstance(self, ElementHandle):
            return self
        return None

    def toString(self) -> str:
        """Get string representation."""
        if self._remoteObject.get("objectId"):
            sub_type = self._remoteObject.get("subtype")
            if sub_type == "node":
                _type = f"{self._remoteObject.get('className')}-{self._remoteObject.get('description')}"
            else:
                _type = sub_type or self._remoteObject.get("type")
            return f"{self.__class__.__name__}@{_type}"
        return f"{self.__class__.__name__}:{Helper.valueFromRemoteObject(self._remoteObject)}"

    async def getProperty(
        self, propertyName: str
    ) -> Union["JSHandle", "ElementHandle"]:
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

    async def getProperties(self) -> Dict[str, Union["JSHandle", "ElementHandle"]]:
        """Get all properties of this handle."""
        properties = await self._properties()
        result = {}
        context = self._context
        for prop in properties["result"]:
            if not prop.get("enumerable"):
                continue
            result[prop.get("name")] = createJSHandle(context, prop.get("value"))
        return result

    async def asArray(self) -> List["JSHandle"]:
        properties = await self._properties()
        return self._handle_list(properties)

    async def asElementArray(self) -> List["ElementHandle"]:
        properties = await self._properties()
        return self._element_list(properties)

    async def jsonValue(self) -> Any:
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
            return Helper.valueFromRemoteObject(response["result"])
        return Helper.valueFromRemoteObject(self._remoteObject)

    async def dispose(self) -> None:
        """Stop referencing the handle."""
        if self._disposed:
            return
        self._disposed = True
        await Helper.releaseObject(self._client, self._remoteObject)

    def _properties(self) -> Awaitable[Dict]:
        return self._client.send(
            "Runtime.getProperties",
            {"objectId": self._remoteObject.get("objectId", ""), "ownProperties": True},
        )

    def _handle_list(self, properties: Dict) -> List["JSHandle"]:
        handle_list: List[JSHandle] = []
        add_handle = handle_list.append
        context = self._context
        for prop in properties["result"]:
            if not prop.get("enumerable"):
                continue
            remote_obj = prop.get("value")
            add_handle(createJSHandle(context, remote_obj))
        return handle_list

    def _element_list(self, properties: Dict) -> List["ElementHandle"]:
        handle_list: List[ElementHandle] = []
        add_handle = handle_list.append
        context = self._context
        for prop in properties["result"]:
            if not prop.get("enumerable"):
                continue
            remote_obj = prop.get("value")
            add_handle(createJSHandle(context, remote_obj).asElement())
        return handle_list

    def __str__(self) -> str:
        return self.toString()

    def __repr__(self) -> str:
        return self.__str__()


class ElementHandle(JSHandle):
    __slots__: SlotsT = ["_frameManager", "_page"]

    def __init__(
        self,
        context: "ExecutionContext",
        client: ClientType,
        remoteObject: Dict,
        page: "Page",
        frameManager: "FrameManager",
    ) -> None:
        super().__init__(context, client, remoteObject)
        self._page: Optional["Page"] = page
        self._frameManager: "FrameManager" = frameManager

    def isIntersectingViewport(self) -> Awaitable[bool]:
        return self.executionContext.evaluate(
            """async element => {
        const visibleRatio = await new Promise(resolve => {
        const observer = new IntersectionObserver(entries => {
          resolve(entries[0].intersectionRatio);
          observer.disconnect();
        });
        observer.observe(element);
      });
      return visibleRatio > 0;
    }""",
            self,
        )

    def innerText(self, text: Optional[str] = None) -> Awaitable[str]:
        return self.executionContext.evaluate(
            """(element, newValue) => {
          if (newValue) element.innerText = newValue;
          return element.innerText;
        }""",
            self,
            text,
        )

    def innerHTML(self, html: Optional[str] = None) -> Awaitable[str]:
        return self.executionContext.evaluate(
            """(element, newValue) => {
          if (newValue) element.innerHTML = newValue;
          return element.innerHTML;
        }""",
            self,
            html,
        )

    def outerHTML(self, html: Optional[str] = None) -> Awaitable[str]:
        return self.executionContext.evaluate(
            """(element, newValue) => {
          if (newValue) element.outerHTML = newValue;
          return element.outerHTML;
        }""",
            self,
            html,
        )

    def hasChildNodes(self) -> Awaitable[bool]:
        return self.executionContext.evaluate("elem => elem.hasChildNodes()", self)

    def childElementCount(self) -> Awaitable[Number]:
        return self.executionContext.evaluate("elem => elem.childElementCount", self)

    def getAttribute(self, attr: str) -> Awaitable[Any]:
        return self.executionContext.evaluate(
            """(element, attr) => element.getAttribute(attr)""", self, attr
        )

    async def contentFrame(self) -> Optional["Frame"]:
        nodeInfo = await self._client.send(
            "DOM.describeNode", {"objectId": self._remoteObject.get("objectId")}
        )
        frameId = nodeInfo.get("node", {}).get("frameId")
        if frameId is None:
            return None
        return self._frameManager.frame(frameId)

    async def hover(self) -> None:
        """Move mouse over to center of this element.

        If needed, this method scrolls eleemnt into view. If this element is
        detached from DOM tree, the method raises an ``ElementHandleError``.
        """
        await self._scrollIntoViewIfNeeded()
        obj = await self._clickablePoint()
        x = obj.get("x", 0)
        y = obj.get("y", 0)
        await self._page.mouse.move(x, y)

    async def click(
        self, button: str = "left", clickCount: int = 1, delay: Number = 0
    ) -> None:
        """Click the center of this element.

        If needed, this method scrolls element into view. If the element is
        detached from DOM, the method raises ``ElementHandleError``.

        :param button: ``left``, ``right``, or ``middle``, defaults to ``left``
        :param clickCount: defaults to 1
        :param delay: Time to wait between ``mousedown`` and ``mouseup`` in milliseconds. Defaults to 0.
        """
        await self._scrollIntoViewIfNeeded()
        obj = await self._clickablePoint()
        x = obj.get("x", 0)
        y = obj.get("y", 0)
        await self._page.mouse.click(x, y, button, clickCount, delay)

    async def uploadFile(self, *filePaths: str) -> None:
        """Upload files."""
        files = [os.path.abspath(p) for p in filePaths]
        objectId = self._remoteObject.get("objectId")
        await self._client.send(
            "DOM.setFileInputFiles", {"objectId": objectId, "files": files}
        )

    async def tap(self) -> None:
        """Tap the center of this element.

        If needed, this method scrolls element into view. If the element is
        detached from DOM, the method raises ``ElementHandleError``.
        """
        await self._scrollIntoViewIfNeeded()
        center = await self._clickablePoint()
        x = center.get("x", 0)
        y = center.get("y", 0)
        await self._page.touchscreen.tap(x, y)

    async def focus(self) -> None:
        """Focus on this element."""
        await self.executionContext.evaluate("element => element.focus()", self)

    async def type(self, text: str, delay: Number = 0) -> None:
        """Type characters.

        This method sends ``keydown``, ``keypress``/``input``, and ``keyup``
        event for each character in the ``text``.

        To press a special key, like ``Control`` or ``ArrowDown``, use
        :meth:`press` method.

        :param text: Text to type into this element.
        :param delay: Optional amount of ``delay`` that specifies the amount
         of time to wait between key presses in seconds. Defaults to 0.
        """
        await self.focus()
        await self._page.keyboard.type(text, delay)

    async def press(
        self, key: str, text: Optional[str] = None, delay: Number = 0
    ) -> None:
        """Press ``key``.

        If ``key`` is a single character and no modifier keys besides
        ``Shift`` are being held down, a ``keypress``/``input`` event will also
        generated. The ``text`` option can be specified to force an input event
        to be generated.

        :param key: Name of key to press, such as ``ArrowLeft``
        :param text: If specified, generates an input event with this text
        :param delay: Time to wait between ``keydown`` and ``keyup``. Defaults to 0
        """
        await self.focus()
        await self._page.keyboard.press(key, text, delay)

    async def boundingBox(self) -> Optional[Dict[str, Number]]:
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

    async def boxModel(
        self
    ) -> Optional[Dict[str, Union[Number, List[Dict[str, float]]]]]:
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
            "content": fromProtocolQuad(model.get("content")),
            "padding": fromProtocolQuad(model.get("padding")),
            "border": fromProtocolQuad(model.get("border")),
            "margin": fromProtocolQuad(model.get("margin")),
            "width": model.get("width"),
            "height": model.get("height"),
        }

    async def screenshot(self, options: Dict = None, **kwargs: Any) -> bytes:
        """Take a screenshot of this element.

        If the element is detached from DOM, this method raises an
        ``ElementHandleError``.

        Available options are same as :meth:`simplechrome.page.Page.screenshot`.
        """
        options = Helper.merge_dict(options, kwargs)

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

    async def querySelectorEval(
        self, selector: str, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> Optional[Any]:
        """Execute function on element which matches selector.

        Details see :meth:`simplechrome.page.Page.querySelectorEval`.
        """
        elementHandle = await self.querySelector(selector)
        if elementHandle is None:
            raise Exception(
                f'Error: failed to find element matching selector "{selector}"'
            )
        result = await self.executionContext.evaluate(
            pageFunction, elementHandle, *args, withCliAPI=withCliAPI
        )
        await elementHandle.dispose()
        return result

    async def querySelectorAll(self, selector: str) -> List["ElementHandle"]:
        arrayHandle = await self.executionContext.evaluateHandle(
            "(element, selector) => Array.from(element.querySelectorAll(selector))",
            self,
            selector,
        )
        return await arrayHandle.asElementArray()

    async def querySelectorAllEval(
        self, selector: str, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> List[Any]:
        arrayHandle = await self.executionContext.evaluateHandle(
            "(element, selector) => Array.from(element.querySelectorAll(selector))",
            self,
            selector,
        )
        result = await self.executionContext.evaluate(
            pageFunction, arrayHandle, *args, withCliAPI=withCliAPI
        )
        return result

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
        return await arrayHandle.asElementArray()

    #: alias to :meth:`xpath`
    Jx = xpath
    #: alias to :meth:`querySelector`
    J = querySelector
    #: alias to :meth:`querySelectorEval`
    Jeval = querySelectorEval
    #: alias to :meth:`querySelectorAll`
    JJ = querySelectorAll
    #: alias to :meth:`querySelectorAllEval`
    JJeval = querySelectorAllEval

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
            raise Exception(error)

    async def _clickablePoint(self) -> Dict[str, Number]:
        try:
            result, layoutMetrics = await gather(
                self._client.send(
                    "DOM.getContentQuads",
                    {"objectId": self._remoteObject.get("objectId")},
                ),
                self._client.send("Page.getLayoutMetrics"),
                loop=self._client.loop,
            )
        except Exception:
            raise Exception("Node is either not visible or not an HTMLElement")

        if not result.get("quads"):
            raise Exception("Node is either not visible or not an HTMLElement")

        clientWidth = layoutMetrics["layoutViewport"]["clientWidth"]
        clientHeight = layoutMetrics["layoutViewport"]["clientHeight"]
        quads: List[List[Dict[str, Number]]] = []
        add_quad = quads.append
        for pquad in result.get("quads"):
            quad = fromProtocolQuad(pquad)
            if (
                computeQuadArea(
                    intersectQuadWithViewport(quad, clientWidth, clientHeight)
                )
                > 1
            ):
                add_quad(quad)
        if len(quads) == 0:
            raise Exception("Node is either not visible or not an HTMLElement")
        quad = quads[0]
        x = 0.0
        y = 0.0
        for point in quad:
            x += point["x"]
            y += point["y"]
        return {"x": x / 4, "y": y / 4}

    async def _getBoxModel(self) -> Optional[Dict]:
        try:
            result: Optional[Dict] = await self._client.send(
                "DOM.getBoxModel", {"objectId": self._remoteObject.get("objectId")}
            )
        except Exception:
            result = None
        return result

    async def _visibleCenter(self) -> Dict[str, Number]:
        await self._scrollIntoViewIfNeeded()
        box = await self.boundingBox()
        if not box:
            raise Exception("Node is not visible.")
        return {"x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2}

    async def _assertBoundingBox(self) -> Dict[str, Number]:
        boundingBox = await self.boundingBox()
        if boundingBox is not None:
            return boundingBox
        raise Exception("Node is either not visible or not an HTMLElement")


def intersectQuadWithViewport(
    quad: List[Dict[str, Number]], width: Number, height: Number
) -> List[Dict[str, Number]]:
    return [
        {"x": min(max(point["x"], 0), width), "y": min(max(point["y"], 0), height)}
        for point in quad
    ]


def fromProtocolQuad(quad: List[Number]) -> List[Dict[str, Number]]:
    return [
        {"x": quad[0], "y": quad[1]},
        {"x": quad[2], "y": quad[3]},
        {"x": quad[4], "y": quad[5]},
        {"x": quad[6], "y": quad[7]},
    ]


def computeQuadArea(quad: List[Dict[str, Number]]) -> Number:
    area = 0.0
    qlen = len(quad)
    for i in range(0, qlen):
        p1 = quad[i]
        p2 = quad[(i + 1) % qlen]
        area += (p1["x"] * p2["y"] - p2["x"] * p1["y"]) / 2
    return math.fabs(area)
