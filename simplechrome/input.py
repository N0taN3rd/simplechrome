"""Keyboard and Mouse module."""

import asyncio
import attr
from typing import Any, Dict, Set, Union, Optional

from .connection import ClientType
from .errors import InputError
from .us_keyboard_layout import keyDefinitions
from .util import merge_dict

__all__ = ["Keyboard", "Mouse", "Touchscreen"]


@attr.dataclass(slots=True)
class Keyboard(object):
    """Keyboard class."""

    client: ClientType = attr.ib()
    modifiers: int = attr.ib(init=False, default=0)
    pressedKeys: Set[str] = attr.ib(init=False, factory=set)

    async def down(
        self, key: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> None:
        """Dispatches a ``keydown`` event with ``key``.

        If ``key`` is a single character and no modifier keys besides ``shift``
        are being held down, and a ``keyparess``/``input`` event will also
        generated. The ``text`` option can be specified to force an ``input``
        event to be generated.

        If ``key`` is a modifier key, like ``Shift``, ``Meta``, or ``Alt``,
        subsequent key presses will be sent with that modifier active. To
        release the modifier key, use :meth:`up` method.

        :arg str key: Name of key to press, such as ``ArrowLeft``.
        :arg dict options: Option can have ``text`` field, and if this option
            spedified, generate an input event with this text.
        """
        opts = merge_dict(options, kwargs)

        description: Dict[str, Union[str, int]] = self._keyDescriptionForString(key)
        autoRepeat = description["code"] in self.pressedKeys
        self.pressedKeys.add(description["code"])
        self.modifiers |= self._modifierBit(description["key"])

        text = opts.get("text")
        if text is None:
            text = description["text"]

        await self.client.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyDown" if text else "rawKeyDown",
                "modifiers": self.modifiers,
                "windowsVirtualKeyCode": description["keyCode"],
                "code": description["code"],
                "key": description["key"],
                "text": text,
                "unmodifiedText": text,
                "autoRepeat": autoRepeat,
                "location": description["location"],
                "isKeypad": description["location"] == 3,
            },
        )

    def _modifierBit(self, key: str) -> int:
        if key == "Alt":
            return 1
        if key == "Control":
            return 2
        if key == "Meta":
            return 4
        if key == "Shift":
            return 8
        return 0

    def _keyDescriptionForString(
        self, keyString: str
    ) -> Dict[str, Union[str, int]]:  # noqa: C901
        shift = self.modifiers & 8
        description: Dict[str, Union[str, int]] = {
            "key": "",
            "keyCode": 0,
            "code": "",
            "text": "",
            "location": 0,
        }

        definition = keyDefinitions.get(keyString)
        if not definition:
            raise InputError(f"Unknown key: {keyString}")

        if "key" in definition:
            description["key"] = definition["key"]
        if shift and definition.get("shiftKey"):
            description["key"] = definition["shiftKey"]

        if "keyCode" in definition:
            description["keyCode"] = definition["keyCode"]
        if shift and definition.get("shiftKeyCode"):
            description["keyCode"] = definition["shiftKeyCode"]

        if "code" in definition:
            description["code"] = definition["code"]

        if "location" in definition:
            description["location"] = definition["location"]

        if len(description["key"]) == 1:  # type: ignore
            description["text"] = description["key"]

        if "text" in definition:
            description["text"] = definition["text"]
        if shift and definition.get("shiftText"):
            description["text"] = definition["shiftText"]

        if self.modifiers & ~8:
            description["text"] = ""

        return description

    async def up(self, key: str) -> None:
        """Dispatches a ``keyup`` event of the ``key``.

        :arg str key: Name of key to release, such as ``ArrowLeft``.
        """
        description = self._keyDescriptionForString(key)

        self.modifiers &= ~self._modifierBit(description["key"])
        if description["code"] in self.pressedKeys:
            self.pressedKeys.remove(description["code"])
        await self.client.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "modifiers": self.modifiers,
                "key": description["key"],
                "windowsVirtualKeyCode": description["keyCode"],
                "code": description["code"],
                "location": description["location"],
            },
        )

    async def sendCharacter(self, char: str) -> None:
        """Dispatches a ``keypress`` and ``input`` event.

        This does not send a ``keydown`` or ``keyup`` event.
        """
        await self.client.send(
            "Input.dispatchKeyEvent",
            {
                "type": "char",
                "modifiers": self.modifiers,
                "text": char,
                "key": char,
                "unmodifiedText": char,
            },
        )

    async def type(self, text: str, options: Dict = None, **kwargs: Any) -> None:
        """Type characters.

        This method sends ``keydown``, ``keypress``/``input``, and ``keyup``
        event for each character in the ``text``.

        To press a special key, like ``Control`` or ``ArrowDown``, use
        :meth:`press` method.

        :arg str text: Text to type into this element.
        :arg dict options: Options can have ``delay`` (int|float) field, which
          specifies time to wait between key presses in milliseconds. Defaults
          to 0.
        """
        opts = merge_dict(options, kwargs)
        delay = opts.get("delay", 0)
        for char in text:
            if char in keyDefinitions:
                await self.press(char, {"delay": delay})
            else:
                await self.sendCharacter(char)
            if delay:
                await asyncio.sleep(delay / 1000)

    async def press(
        self, key: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> None:
        """Press ``key``.

        If ``key`` is a single character and no modifier keys besides
        ``Shift`` are being held down, a ``keypress``/``input`` event will also
        generated. The ``text`` option can be specified to force an input event
        to be generated.

        :arg str key: Name of key to press, such as ``ArrowLeft``.

        This method accepts the following options:

        * ``text`` (str): If specified, generates an input event with this
          text.
        * ``delay`` (int|float): Time to wait between ``keydown`` and
          ``keyup``. Defaults to 0.
        """
        opts = merge_dict(options, kwargs)

        await self.down(key, opts)
        if "delay" in opts:
            await asyncio.sleep(opts["delay"])
        await self.up(key)


@attr.dataclass(slots=True)
class Mouse(object):
    """Mouse class."""

    client: ClientType = attr.ib()
    keyboard: Keyboard = attr.ib()
    _x: float = attr.ib(init=False, default=0.0)
    _y: float = attr.ib(init=False, default=0.0)
    _button: str = attr.ib(init=False, default="none")

    async def move(
        self, x: float, y: float, options: dict = None, **kwargs: Any
    ) -> None:
        """Move mouse cursor (dispatches a ``mousemove`` event).

        Options can accepts ``steps`` (int) field. If this ``steps`` option
        specified, Sends intermediate ``mousemove`` events. Defaults to 1.
        """
        opts = merge_dict(options, kwargs)
        fromX = self._x
        fromY = self._y
        self._x = x
        self._y = y
        steps = opts.get("steps", 1)
        for i in range(1, steps + 1):
            x = round(fromX + (self._x - fromX) * (i / steps))
            y = round(fromY + (self._y - fromY) * (i / steps))
            await self.client.send(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseMoved",
                    "button": self._button,
                    "x": x,
                    "y": y,
                    "modifiers": self.keyboard.modifiers,
                },
            )

    async def click(
        self, x: float, y: float, options: dict = None, **kwargs: Any
    ) -> None:
        """Click button at (``x``, ``y``).

        Shortcut to :meth:`move`, :meth:`down`, and :meth:`up`.

        This method accepts the following options:

        * ``button`` (str): ``left``, ``right``, or ``middle``, defaults to
          ``left``.
        * ``clickCount`` (int): defaults to 1.
        * ``delay`` (int|float): Time to wait between ``mousedown`` and
          ``mouseup`` in milliseconds. Defaults to 0.
        """
        opts = merge_dict(options, kwargs)
        await self.move(x, y)
        await self.down(opts)
        if opts.get("delay"):
            await asyncio.sleep(opts.get("delay", 0))
        await self.up(options)

    async def down(self, options: dict = None, **kwargs: Any) -> None:
        """Press down button (dispatches ``mousedown`` event).

        This method accepts the following options:

        * ``button`` (str): ``left``, ``right``, or ``middle``, defaults to
          ``left``.
        * ``clickCount`` (int): defaults to 1.
        """
        opts = merge_dict(options, kwargs)
        self._button = opts.get("button", "left")
        await self.client.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "button": self._button,
                "x": self._x,
                "y": self._y,
                "modifiers": self.keyboard.modifiers,
                "clickCount": opts.get("clickCount") or 1,
            },
        )

    async def up(self, options: dict = None, **kwargs: Any) -> None:
        """Release pressed button (dispatches ``mouseup`` event).

        This method accepts the following options:

        * ``button`` (str): ``left``, ``right``, or ``middle``, defaults to
          ``left``.
        * ``clickCount`` (int): defaults to 1.
        """
        opts = merge_dict(options, kwargs)
        self._button = "none"
        await self.client.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "button": opts.get("button", "left"),
                "x": self._x,
                "y": self._y,
                "modifiers": self.keyboard.modifiers,
                "clickCount": opts.get("clickCount") or 1,
            },
        )


@attr.dataclass(slots=True)
class Touchscreen(object):
    """Touchscreen class."""

    client: ClientType = attr.ib()
    keyboard: Keyboard = attr.ib()

    async def tap(self, x: float, y: float) -> None:
        """Tap (``x``, ``y``).

        Dispatches a ``touchstart`` and ``touchend`` event.
        """
        touchPoints = [{"x": round(x), "y": round(y)}]
        await self.client.send(
            "Input.dispatchTouchEvent",
            {
                "type": "touchStart",
                "touchPoints": touchPoints,
                "modifiers": self.keyboard.modifiers,
            },
        )
        await self.client.send(
            "Input.dispatchTouchEvent",
            {
                "type": "touchEnd",
                "touchPoints": [],
                "modifiers": self.keyboard.modifiers,
            },
        )
