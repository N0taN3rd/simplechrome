from asyncio import gather, sleep
from typing import Dict, Optional, Set

from ._typings import Number, NumberOrStr, SlotsT
from .connection import ClientType
from .errors import InputError
from .us_keyboard_layout import keyDefinitions

__all__ = ["Input", "Keyboard", "Mouse", "Touchscreen"]


class Keyboard:
    """Class representing an abstraction around keyboard input via the CDP"""

    __slots__: SlotsT = ["__weakref__", "client", "modifiers", "pressedKeys"]

    def __init__(self, client: ClientType) -> None:
        """Initialize a new instance of Keyboard

        :param client: The client instance used to communicate with the remote browser
        """
        self.client: ClientType = client
        self.modifiers: int = 0
        self.pressedKeys: Set[int] = set()

    async def down(self, key: str, text: Optional[str] = None) -> None:
        """Dispatches a ``keydown`` event with ``key``.

        If ``key`` is a single character and no modifier keys besides ``shift``
        are being held down, and a ``keyparess``/``input`` event will also
        generated. The ``text`` option can be specified to force an ``input``
        event to be generated.

        If ``key`` is a modifier key, like ``Shift``, ``Meta``, or ``Alt``,
        subsequent key presses will be sent with that modifier active. To
        release the modifier key, use :meth:`up` method.

        :arg key: Name of key to press, such as ``ArrowLeft``.
        :arg text: Optional text value to be generated with this event.
        """
        description = self._keyDescriptionForString(key)
        autoRepeat = description["code"] in self.pressedKeys
        self.pressedKeys.add(description["code"])  # type: ignore
        self.modifiers |= modifierBit(description["key"])  # type: ignore

        if text is None:
            text = description["text"]  # type: ignore

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

    async def up(self, key: str) -> None:
        """Dispatches a ``keyup`` event of the ``key``.

        :arg str key: Name of key to release, such as ``ArrowLeft``.
        """
        description = self._keyDescriptionForString(key)

        self.modifiers &= ~modifierBit(description["key"])  # type: ignore
        if description["code"] in self.pressedKeys:
            self.pressedKeys.remove(description["code"])  # type: ignore
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

    async def sendCharacter(self, char: str, delay: Optional[Number] = None) -> None:
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
        if delay is not None:
            await sleep(delay, loop=self.client.loop)

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
        press_key = self.press
        send_char = self.sendCharacter
        for char in text:
            if char in keyDefinitions:
                await press_key(char, delay=delay)
            else:
                await send_char(char, delay)

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
        await self.down(key, text)
        await sleep(delay, loop=self.client.loop)
        await self.up(key)

    def _keyDescriptionForString(self, keyString: str) -> Dict[str, NumberOrStr]:
        shift = self.modifiers & 8
        description: Dict[str, NumberOrStr] = {
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


def modifierBit(key: str) -> int:
    if key == "Alt":
        return 1
    if key == "Control":
        return 2
    if key == "Meta":
        return 4
    if key == "Shift":
        return 8
    return 0


class Mouse:
    """Class representing an abstraction around mouse input via the CDP"""

    __slots__: SlotsT = ["client", "keyboard", "_x", "_y", "_button"]

    def __init__(self, client: ClientType, keyboard: Keyboard) -> None:
        """Initialize a new instance of Mouse

        :param client: The client instance used to communicate with the remote browser
        :param keyboard: The backing instance of keyboard to be used
        """
        self.client: ClientType = client
        self.keyboard: Keyboard = keyboard
        self._x: Number = 0.0
        self._y: Number = 0.0
        self._button: str = "none"

    async def move(self, x: Number, y: Number, steps: int = 1) -> None:
        """Move mouse cursor (dispatches a ``mousemove`` event).

        Options can accepts ``steps`` (int) field. If this ``steps`` option
        specified, Sends intermediate ``mousemove`` events. Defaults to 1.
        """
        fromX = self._x
        fromY = self._y
        self._x = x
        self._y = y
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
        self,
        x: Number,
        y: Number,
        button: str = "left",
        clickCount: int = 1,
        delay: Optional[Number] = None,
    ) -> None:
        """Click button at (``x``, ``y``).

        Shortcut to :meth:`move`, :meth:`down`, and :meth:`up`.

        This method accepts the following options:

        :param x: The position on the x axis to click
        :param y: The position on the y axis to click
        :param button: ``left``, ``right``, or ``middle``, defaults to ``left``
        :param clickCount: defaults to 1
        :param delay: Time to wait between ``mousedown`` and ``mouseup`` in milliseconds. Defaults to 0.
        """
        if delay is not None:
            await gather(self.move(x, y), self.down(button, clickCount))
            await sleep(delay, loop=self.client.loop)
            await self.up(button, clickCount)
        else:
            await gather(
                self.move(x, y),
                self.down(button, clickCount),
                self.up(button, clickCount),
            )

    async def down(self, button: str = "left", clickCount: int = 1) -> None:
        """Press down button (dispatches ``mousedown`` event).

        This method accepts the following options:

        * ``button`` (str): ``left``, ``right``, or ``middle``, defaults to
          ``left``.
        * ``clickCount`` (int): defaults to 1.
        """
        self._button = button
        await self.client.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "button": self._button,
                "x": self._x,
                "y": self._y,
                "modifiers": self.keyboard.modifiers,
                "clickCount": clickCount,
            },
        )

    async def up(self, button: str = "left", clickCount: Number = 1) -> None:
        """Release pressed button (dispatches ``mouseup`` event).

        This method accepts the following options:

        * ``button`` (str): ``left``, ``right``, or ``middle``, defaults to
          ``left``.
        * ``clickCount`` (int): defaults to 1.
        """
        self._button = "none"
        await self.client.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "button": button,
                "x": self._x,
                "y": self._y,
                "modifiers": self.keyboard.modifiers,
                "clickCount": clickCount,
            },
        )


class Touchscreen:
    """Touchscreen class."""

    __slots__: SlotsT = ["__weakref__", "client", "keyboard"]

    def __init__(self, client: ClientType, keyboard: Keyboard) -> None:
        self.client: ClientType = client
        self.keyboard: Keyboard = keyboard

    async def tap(self, x: Number, y: Number) -> None:
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


class Input:
    __slots__: SlotsT = [
        "__weakref__",
        "_keyboard",
        "_mouse",
        "_touchscreen",
        "_client",
    ]

    def __init__(self, client: ClientType) -> None:
        self._keyboard: Keyboard = Keyboard(client)
        self._mouse: Mouse = Mouse(client, self._keyboard)
        self._touchscreen: Touchscreen = Touchscreen(client, self._keyboard)
        self._client: ClientType = client

    @property
    def keyboard(self) -> Keyboard:
        return self._keyboard

    @property
    def mouse(self) -> Mouse:
        return self._mouse

    @property
    def touchscreen(self) -> Touchscreen:
        return self._touchscreen
