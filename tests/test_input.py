import asyncio
from pathlib import Path

import pytest
from grappa import should

from simplechrome.errors import InputError
from simplechrome.events import Events
from .base_test import BaseChromeTest
from .frame_utils import attachFrame


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestClick(BaseChromeTest):
    get_dimensions = """
        function () {
            const rect = document.querySelector('textarea').getBoundingClientRect();
            return {
                x: rect.left,
                y: rect.top,
                width: rect.width,
                height: rect.height
            };
        }"""  # noqa: E501

    @pytest.mark.asyncio
    async def test_click(self):
        await self.goto_test("button.html")
        await self.page.click("button")
        await self.page.evaluate("result") | should.be.equal.to("Clicked")

    @pytest.mark.asyncio
    async def test_click_events(self):
        await self.goto_test(f"checkbox.html")
        await self.page.evaluate("result.check") | should.be.none
        await self.page.click("input#agree")
        await self.page.evaluate("result.check") | should.be.true
        events = await self.page.evaluate("result.events")
        events | should.be.equal.to(
            [
                "mouseover",
                "mouseenter",
                "mousemove",
                "mousedown",
                "mouseup",
                "click",
                "input",
                "change",
            ]
        )
        await self.page.click("input#agree")
        await self.page.evaluate("result.check") | should.be.equal.to(False)

    @pytest.mark.asyncio
    async def test_click_label(self):
        await self.goto_test("checkbox.html")
        await self.page.evaluate("result.check") | should.be.none
        await self.page.click('label[for="agree"]')
        await self.page.evaluate("result.check") | should.be.true
        events = await self.page.evaluate("result.events")
        events | should.be.equal.to(["click", "input", "change"])
        await self.page.click('label[for="agree"]')
        await self.page.evaluate("result.check") | should.be.equal.to(False)

    @pytest.mark.asyncio
    async def test_click_fail(self):
        await self.goto_test("button.html")
        with pytest.raises(Exception) as cm:
            await self.page.click("button.does-not-exist")
        str(cm.value) | should.be.equal.to(
            "No node found for selector: button.does-not-exist"
        )

    @pytest.mark.asyncio
    async def test_touch_enabled_viewport(self):
        await self.page.setViewport(
            {
                "width": 375,
                "height": 667,
                "deviceScaleFactor": 2,
                "isMobile": True,
                "hasTouch": True,
                "isLandscape": False,
            }
        )
        await self.page.mouse.down()
        await self.page.mouse.move(100, 10)
        await self.page.mouse.up()

    @pytest.mark.asyncio
    async def test_click_after_navigation(self):
        await self.goto_test("button.html")
        await self.page.click("button")
        await self.goto_test("button.html")
        await self.page.click("button")
        await self.page.evaluate("result") | should.be.equal.to("Clicked")

    @pytest.mark.asyncio
    async def test_resize_textarea(self):
        await self.goto_test("textarea.html")
        dimensions = await self.page.evaluate(self.get_dimensions)
        x = dimensions["x"]
        y = dimensions["y"]
        width = dimensions["width"]
        height = dimensions["height"]
        mouse = self.page.mouse
        await mouse.move(x + width - 4, y + height - 4)
        await mouse.down()
        await mouse.move(x + width + 100, y + height + 100)
        await mouse.up()
        new_dimensions = await self.page.evaluate(self.get_dimensions)
        new_dimensions["width"] | should.be.equal.to(width + 104)
        new_dimensions["height"] | should.be.equal.to(height + 104)

    @pytest.mark.asyncio
    async def test_scroll_and_click(self):
        await self.goto_test("scrollable.html")
        await self.page.click("#button-5")
        await self.page.evaluate(
            'document.querySelector("#button-5").textContent'
        ) | should.be.equal.to("clicked")
        await self.page.click("#button-80")
        await self.page.evaluate(
            'document.querySelector("#button-80").textContent'
        ) | should.be.equal.to("clicked")

    @pytest.mark.asyncio
    async def test_double_click(self):
        await self.goto_test("button.html")
        await self.page.evaluate(
            """() => {
            window.double = false;
            const button = document.querySelector('button');
            button.addEventListener('dblclick', event => {
                window.double = true;
            });
        }"""
        )
        button = await self.page.J("button")
        await button.click(clickCount=2)
        await self.page.evaluate("double") | should.be.true
        await self.page.evaluate("result") | should.be.equal.to("Clicked")

    @pytest.mark.asyncio
    async def test_click_partially_obscured_button(self):
        await self.goto_test("button.html")
        await self.page.evaluate(
            """() => {
            const button = document.querySelector('button');
            button.textContent = 'Some really long text that will go off screen';
            button.style.position = 'absolute';
            button.style.left = '368px';
        }"""
        )  # noqa: 501
        await self.page.click("button")
        await self.page.evaluate("result") | should.be.equal.to("Clicked")

    @pytest.mark.asyncio
    async def test_select_text_by_mouse(self):
        await self.goto_test("textarea.html")
        await self.page.focus("textarea")
        text = "This is the text that we are going to try to select. Let's see how it goes."  # noqa: E501
        await self.page.keyboard.type(text)
        await self.page.evaluate('document.querySelector("textarea").scrollTop = 0')
        dimensions = await self.page.evaluate(self.get_dimensions)
        x = dimensions["x"]
        y = dimensions["y"]
        await self.page.mouse.move(x + 2, y + 2)
        await self.page.mouse.down()
        await self.page.mouse.move(100, 100)
        await self.page.mouse.up()
        await self.page.evaluate(
            "() => window.getSelection().toString()"
        ) | should.be.equal.to(text)

    @pytest.mark.asyncio
    async def test_select_text_by_triple_click(self):
        await self.goto_test("textarea.html")
        await self.page.focus("textarea")
        text = "This is the text that we are going to try to select. Let's see how it goes."  # noqa: E501
        await self.page.keyboard.type(text)
        await self.page.click("textarea")
        await self.page.click("textarea", clickCount=2)
        await self.page.click("textarea", clickCount=3)
        await self.page.evaluate(
            "window.getSelection().toString()"
        ) | should.be.equal.to(text)

    @pytest.mark.asyncio
    async def test_trigger_hover(self):
        await self.goto_test("scrollable.html")
        await self.page.hover("#button-6")
        await self.page.evaluate(
            'document.querySelector("button:hover").id'
        ) | should.be.equal.to("button-6")
        await self.page.hover("#button-2")
        await self.page.evaluate(
            'document.querySelector("button:hover").id'
        ) | should.be.equal.to("button-2")
        await self.page.hover("#button-91")
        await self.page.evaluate(
            'document.querySelector("button:hover").id'
        ) | should.be.equal.to("button-91")

    @pytest.mark.asyncio
    async def test_right_click(self):
        await self.page.goto(self.full_test_url("scrollable.html"), waitUntil="load")
        await self.page.click("#button-8", button="right")
        await self.page.evaluate(
            'document.querySelector("#button-8").textContent'
        ) | should.be.equal.to("context menu")

    @pytest.mark.asyncio
    async def test_click_with_modifier_key(self):
        await self.page.goto(self.full_test_url("scrollable.html"), waitUntil="load")
        await self.page.evaluate(
            '() => document.querySelector("#button-3").addEventListener("mousedown", e => window.lastEvent = e, true)'
        )
        modifiers = {
            "Shift": "shiftKey",
            "Control": "ctrlKey",
            "Alt": "altKey",
            "Meta": "metaKey",
        }
        for key, value in modifiers.items():
            await self.page.keyboard.down(key)
            await self.page.click("#button-3")
            await self.page.evaluate(
                "mod => window.lastEvent[mod]", value
            ) | should.be.true
            await self.page.keyboard.up(key)
        await self.page.click("#button-3")
        for key, value in modifiers.items():
            await self.page.evaluate(
                "mod => window.lastEvent[mod]", value
            ) | should.be.false

    @pytest.mark.asyncio
    async def test_click_link(self, ee_helper):
        await self.goto_empty()
        results = []
        ee_helper.addEventListener(
            self.page, Events.Page.FrameNavigated, lambda x: results.append(True)
        )
        await self.page.setContent(
            '<a href="{}">empty.html</a>'.format("f{self.url}empty.html")
        )
        await self.page.click("a")
        await asyncio.sleep(1)
        with should(results):
            should.have.length.of(1)
            should.have.index.at(0).that.should.be.true

    @pytest.mark.asyncio
    async def test_mouse_movement(self):
        await self.page.mouse.move(100, 100)
        await self.page.evaluate(
            """() => {
                window.result = [];
                document.addEventListener('mousemove', event => {
                    window.result.push([event.clientX, event.clientY]);
                });
            }"""
        )
        await self.page.mouse.move(200, 300, steps=5)
        await self.page.evaluate("window.result") | should.be.equal.to(
            [[120, 140], [140, 180], [160, 220], [180, 260], [200, 300]]
        )

    @pytest.mark.asyncio
    async def test_tap_button(self):
        await self.page.goto(self.full_test_url("button.html"), waitUntil="load")
        await self.page.tap("button")
        await self.page.evaluate("result") | should.be.equal.to("Clicked")

    @pytest.mark.asyncio
    async def test_touches_report(self):
        await self.page.goto(self.full_test_url("touches.html"), waitUntil="load")
        button = await self.page.J("button")
        await button.tap()
        await self.page.evaluate("getResult()") | should.be.equal.to(
            ["Touchstart: 0", "Touchend: 0"]
        )

    @pytest.mark.asyncio
    async def test_click_inside_frame(self):
        await self.page.goto(self.full_test_url("empty.html"), waitUntil="load")
        await self.page.setContent(
            '<div style="width:100px;height:100px;>spacer</div>"'
        )
        await attachFrame(self.page, "button-test", self.full_test_url("button.html"))
        frame = self.page.frames[1]
        button = await frame.J("button")
        await button.click()
        await frame.evaluate("result") | should.be.equal.to("Clicked")

    @pytest.mark.asyncio
    async def test_click_with_device_scale_factor(self):
        await self.page.goto(self.full_test_url("empty.html"), waitUntil="load")
        await self.page.setViewport(
            {"width": 400, "height": 400, "deviceScaleFactor": 5}
        )
        await self.page.evaluate("devicePixelRatio") | should.be.equal.to(5)
        await self.page.setContent(
            '<div style="width:100px;height:100px;>spacer</div>"'
        )
        await attachFrame(self.page, "button-test", self.full_test_url("button.html"))
        frame = self.page.frames[1]
        button = await frame.J("button")
        await button.click()
        await frame.evaluate("result") | should.be.equal.to("Clicked")


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestFileUpload(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_file_upload(self):
        await self.goto_test("fileupload.html")
        filePath = Path(__file__).parent / "file-to-upload.txt"
        input = await self.page.J("input")
        await input.uploadFile(str(filePath))
        result = await self.page.evaluate("e => e.files[0].name", input)
        result | should.be.equal.to("file-to-upload.txt")
        results = await self.page.evaluate(
            """e => {
                const reader = new FileReader();
                const promise = new Promise(fulfill => reader.onload = fulfill);
                reader.readAsText(e.files[0]);
                return promise.then(() => reader.result);
            }""",
            input,
        )
        results | should.be.equal.to("contents of the file\n")


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestType(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_key_type(self):
        await self.goto_test("textarea.html")
        textarea = await self.page.J("textarea")
        text = "Type in this text!"
        await textarea.type(text)
        result = await self.page.evaluate(
            '() => document.querySelector("textarea").value'
        )
        result | should.be.equal.to(text)
        result = await self.page.evaluate("() => result")
        result | should.be.equal.to(text)

    @pytest.mark.asyncio
    async def test_key_arrowkey(self):
        await self.goto_test("textarea.html")
        await self.page.type("textarea", "Hello World!")
        for char in "World!":
            await self.page.keyboard.press("ArrowLeft")
        await self.page.keyboard.type("inserted ")
        result = await self.page.evaluate(
            '() => document.querySelector("textarea").value'
        )
        result | should.be.equal.to("Hello inserted World!")

        await self.page.keyboard.down("Shift")
        for char in "inserted ":
            await self.page.keyboard.press("ArrowLeft")
        await self.page.keyboard.up("Shift")
        await self.page.keyboard.press("Backspace")
        result = await self.page.evaluate(
            '() => document.querySelector("textarea").value'
        )
        result | should.be.equal.to("Hello World!")

    @pytest.mark.asyncio
    async def test_key_press_element_handle(self):
        await self.goto_test("textarea.html")
        textarea = await self.page.J("textarea")
        await textarea.press("a", text="f")
        result = await self.page.evaluate(
            '() => document.querySelector("textarea").value'
        )
        result | should.be.equal.to("f")

        await self.page.evaluate(
            '() => window.addEventListener("keydown", e => e.preventDefault(), true)'  # noqa: E501
        )
        await textarea.press("a", text="y")
        result | should.be.equal.to("f")

    @pytest.mark.asyncio
    async def test_key_send_char(self):
        await self.goto_test("textarea.html")
        await self.page.focus("textarea")
        await self.page.keyboard.sendCharacter("朝")
        result = await self.page.evaluate(
            '() => document.querySelector("textarea").value'
        )
        result | should.be.equal.to("朝")

        await self.page.evaluate(
            '() => window.addEventListener("keydown", e => e.preventDefault(), true)'  # noqa: E501
        )
        await self.page.keyboard.sendCharacter("a")
        result = await self.page.evaluate(
            '() => document.querySelector("textarea").value'
        )
        result | should.be.equal.to("朝a")

    @pytest.mark.asyncio
    async def test_repeat_shift_key(self):
        await self.goto_test("keyboard.html")
        keyboard = self.page.keyboard
        codeForKey = {"Shift": 16, "Alt": 18, "Meta": 91, "Control": 17}
        for key, code in codeForKey.items():
            await keyboard.down(key)
            await self.page.evaluate("getResult()") | should.be.equal.to(
                "Keydown: {key} {key}Left {code} [{key}]".format(key=key, code=code)
            )
            await keyboard.down("!")
            if key == "Shift":
                await self.page.evaluate("getResult()") | should.be.equal.to(
                    "Keydown: ! Digit1 49 [{key}]\n"
                    "Keypress: ! Digit1 33 33 33 [{key}]".format(key=key)
                )
            else:
                await self.page.evaluate("getResult()") | should.be.equal.to(
                    "Keydown: ! Digit1 49 [{key}]".format(key=key)
                )
            await keyboard.up("!")
            await self.page.evaluate("getResult()") | should.be.equal.to(
                "Keyup: ! Digit1 49 [{key}]".format(key=key)
            )
            await keyboard.up(key)
            await self.page.evaluate("getResult()") | should.be.equal.to(
                "Keyup: {key} {key}Left {code} []".format(key=key, code=code)
            )

    @pytest.mark.asyncio
    async def test_repeat_multiple_modifiers(self):
        await self.goto_test("keyboard.html")
        keyboard = self.page.keyboard
        await keyboard.down("Control")
        await self.page.evaluate("getResult()") | should.be.equal.to(
            "Keydown: Control ControlLeft 17 [Control]"
        )
        await keyboard.down("Meta")
        await self.page.evaluate("getResult()") | should.be.equal.to(
            "Keydown: Meta MetaLeft 91 [Control Meta]"
        )
        await keyboard.down(";")
        await self.page.evaluate("getResult()") | should.be.equal.to(
            "Keydown: ; Semicolon 186 [Control Meta]"
        )
        await keyboard.up(";")
        await self.page.evaluate("getResult()") | should.be.equal.to(
            "Keyup: ; Semicolon 186 [Control Meta]"
        )
        await keyboard.up("Control")
        await self.page.evaluate("getResult()") | should.be.equal.to(
            "Keyup: Control ControlLeft 17 [Meta]"
        )
        await keyboard.up("Meta")
        await self.page.evaluate("getResult()") | should.be.equal.to(
            "Keyup: Meta MetaLeft 91 []"
        )

    @pytest.mark.asyncio
    async def test_send_proper_code_while_typing(self):
        await self.goto_test("keyboard.html")
        await self.page.keyboard.type("!")
        await self.page.evaluate("getResult()") | should.be.equal.to(
            "Keydown: ! Digit1 49 []\n"
            "Keypress: ! Digit1 33 33 33 []\n"
            "Keyup: ! Digit1 49 []"
        )
        await self.page.keyboard.type("^")
        await self.page.evaluate("getResult()") | should.be.equal.to(
            "Keydown: ^ Digit6 54 []\n"
            "Keypress: ^ Digit6 94 94 94 []\n"
            "Keyup: ^ Digit6 54 []"
        )

    @pytest.mark.asyncio
    async def test_send_proper_code_while_typing_with_shift(self):
        await self.goto_test("keyboard.html")
        await self.page.keyboard.down("Shift")
        await self.page.keyboard.type("~")
        await self.page.evaluate("getResult()") | should.be.equal.to(
            "Keydown: Shift ShiftLeft 16 [Shift]\n"
            "Keydown: ~ Backquote 192 [Shift]\n"
            "Keypress: ~ Backquote 126 126 126 [Shift]\n"
            "Keyup: ~ Backquote 192 [Shift]"
        )
        await self.page.keyboard.up("Shift")

    @pytest.mark.asyncio
    async def test_not_type_prevent_events(self):
        await self.goto_test("textarea.html")
        await self.page.focus("textarea")
        await self.page.evaluate(
            """() => {
window.addEventListener('keydown', event => {
    event.stopPropagation();
    event.stopImmediatePropagation();
    if (event.key === 'l')
        event.preventDefault();
    if (event.key === 'o')
        Promise.resolve().then(() => event.preventDefault());
}, false);
} """
        )
        await self.page.keyboard.type("Hello World!")
        await self.page.evaluate("textarea.value") | should.be.equal.to("He Wrd!")

    @pytest.mark.asyncio
    async def test_key_modifiers(self):
        keyboard = self.page.keyboard
        keyboard.modifiers | should.be.equal.to(0)
        await keyboard.down("Shift")
        keyboard.modifiers | should.be.equal.to(8)
        await keyboard.down("Alt")
        keyboard.modifiers | should.be.equal.to(9)
        await keyboard.up("Shift")
        keyboard.modifiers | should.be.equal.to(1)
        await keyboard.up("Alt")
        keyboard.modifiers | should.be.equal.to(0)

    @pytest.mark.asyncio
    async def test_repeat_properly(self):
        await self.goto_test("textarea.html")
        await self.page.focus("textarea")
        await self.page.evaluate(
            """() => {
            document.querySelector("textarea").addEventListener("keydown", e => window.lastEvent = e, true);
            }"""
        )
        await self.page.keyboard.down("a")
        await self.page.evaluate("window.lastEvent.repeat") | should.be.false
        await self.page.keyboard.press("a")
        await self.page.evaluate("window.lastEvent.repeat") | should.be.true

        await self.page.keyboard.down("b")
        await self.page.evaluate("window.lastEvent.repeat") | should.be.false
        await self.page.keyboard.down("b")
        await self.page.evaluate("window.lastEvent.repeat") | should.be.true

        await self.page.keyboard.up("a")
        await self.page.keyboard.down("a")
        await self.page.evaluate("window.lastEvent.repeat") | should.be.false

    @pytest.mark.asyncio
    async def test_key_type_long(self):
        await self.goto_test("textarea.html")
        textarea = await self.page.J("textarea")
        text = "This text is two lines.\\nThis is character 朝."
        await textarea.type(text)
        result = await self.page.evaluate(
            '() => document.querySelector("textarea").value'
        )
        result | should.be.equal.to(text)
        result = await self.page.evaluate("() => result")
        result | should.be.equal.to(text)

    @pytest.mark.asyncio
    async def test_key_location(self):
        await self.goto_test("textarea.html")
        textarea = await self.page.J("textarea")
        await self.page.evaluate(
            '() => window.addEventListener("keydown", e => window.keyLocation = e.location, true)'  # noqa: E501
        )

        await textarea.press("Digit5")
        await self.page.evaluate("keyLocation") | should.be.equal.to(0)

        await textarea.press("ControlLeft")
        await self.page.evaluate("keyLocation") | should.be.equal.to(1)

        await textarea.press("ControlRight")
        await self.page.evaluate("keyLocation") | should.be.equal.to(2)

        await textarea.press("NumpadSubtract")
        await self.page.evaluate("keyLocation") | should.be.equal.to(3)

    @pytest.mark.asyncio
    async def test_key_unknown(self):
        with pytest.raises(InputError):
            await self.page.keyboard.press("NotARealKey")
        with pytest.raises(InputError):
            await self.page.keyboard.press("ё")
        with pytest.raises(InputError):
            await self.page.keyboard.press("😊")
