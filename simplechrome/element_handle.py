# -*- coding: utf-8 -*-
"""Element handle module."""

import copy
import os.path
import math
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

from .connection import CDPSession
from .errors import ElementHandleError, NetworkError
from .execution_context import ExecutionContext, JSHandle
from .util import merge_dict

__all__ = ["ElementHandle"]

if TYPE_CHECKING:
    from simplechrome.page import Page
    from simplechrome.frame_manager import FrameManager, Frame


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

    async def boxModel(self) -> Optional[Dict[str, Union[List[Dict[str, int]], Dict]]]:
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
        boundingBox = await self._assertBoundingBox()
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

        boundingBox = await self._assertBoundingBox()
        _obj = await self._client.send("Page.getLayoutMetrics")
        pageX = _obj["layoutViewport"]["pageX"]
        pageY = _obj["layoutViewport"]["pageY"]

        clip = {}
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
        for property in properties.values():
            elementHandle = property.asElement()
            if elementHandle:
                result.append(elementHandle)
        return result

    #: alias to :meth:`xpath`
    Jx = xpath
