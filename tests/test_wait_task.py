import asyncio
import time

import pytest
from async_timeout import timeout
from grappa import should

from simplechrome.errors import EvaluationError, WaitTimeoutError
from .base_test import BaseChromeTest
from .utils import TestUtil

addElement = "tag => document.body.appendChild(document.createElement(tag))"


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestWaitForFunction(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_wait_for_expression(self):
        await self.goto_empty(waitUntil="load")
        fut = asyncio.ensure_future(self.page.waitForFunction("window.__FOO === 1"))
        await self.page.evaluate("window.__FOO = 1;")
        assert await fut

    @pytest.mark.asyncio
    async def test_wait_for_function(self):
        await self.goto_empty(waitUntil="load")
        fut = asyncio.ensure_future(
            self.page.waitForFunction("() => window.__FOO === 2")
        )
        await self.page.evaluate("window.__FOO = 2;")
        assert await fut

    @pytest.mark.asyncio
    async def test_wait_for_function_args(self):
        await self.goto_empty(waitUntil="load")
        fut = asyncio.ensure_future(
            self.page.waitForFunction("(a, b) => a + b === 3", {}, 1, 2)
        )
        assert await fut

    @pytest.mark.asyncio
    async def test_poll_on_interval(self):
        await self.goto_empty(waitUntil="load")
        result = []
        start_time = time.perf_counter()
        fut = asyncio.ensure_future(
            self.page.waitForFunction('() => window.__FOO === "hit"', polling=100)
        )
        fut.add_done_callback(lambda f: result.append(True))
        await asyncio.sleep(0)  # once switch task
        await self.page.evaluate('window.__FOO = "hit"')
        await self.page.evaluate(
            'document.body.appendChild(document.createElement("div"))'
        )
        await asyncio.sleep(0.02)
        result | should.have.length.of(0)
        await fut
        time.perf_counter() - start_time | should.be.higher.than(0.1)
        await self.page.evaluate("window.__FOO") | should.be.equal.to("hit")

    @pytest.mark.asyncio
    async def test_poll_on_mutation(self):
        await self.goto_empty(waitUntil="load")
        result = []
        fut = asyncio.ensure_future(
            self.page.waitForFunction(
                '() => window.__FOO === "hit"', polling="mutation"
            )
        )
        fut.add_done_callback(lambda f: result.append(True))
        await asyncio.sleep(1)  # once switch task
        await self.page.evaluate('window.__FOO = "hit"')
        await asyncio.sleep(1)
        await self.page.evaluate(
            'document.body.appendChild(document.createElement("div"))'
        )
        await fut
        result | should.not_be.none

    @pytest.mark.asyncio
    async def test_poll_on_raf(self):
        await self.goto_empty(waitUntil="load")
        result = []
        fut = asyncio.ensure_future(
            self.page.waitForFunction('() => window.__FOO === "hit"', polling="raf")
        )
        fut.add_done_callback(lambda f: result.append(True))
        await asyncio.sleep(0)  # once switch task
        await self.page.evaluate('window.__FOO = "hit"')
        await asyncio.sleep(0)  # once switch task
        result | should.have.length.of(0)
        await fut
        result | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_bad_polling_value(self):
        await self.goto_empty(waitUntil="load")
        with pytest.raises(ValueError) as cm:
            await self.page.waitForFunction("() => true", polling="unknown")
        str(cm.value) | should.contain("polling")
        # self.assertIn("polling", cm.exception.args[0])

    @pytest.mark.asyncio
    async def test_negative_polling_value(self):
        await self.goto_empty(waitUntil="load")
        with pytest.raises(ValueError) as cm:
            await self.page.waitForFunction("() => true", polling=-100)
        str(cm.value) | should.contain("Cannot poll with non-positive interval")

    @pytest.mark.asyncio
    async def test_wait_for_fucntion_return_value(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.waitForFunction("() => 5")
        await result.jsonValue() | should.be.equal.to(5)

    @pytest.mark.asyncio
    async def test_wait_for_function_window(self):
        await self.goto_empty(waitUntil="load")
        async with timeout(5) as to:
            await self.page.waitForFunction("() => window") | should.not_be.none
        to.expired | should.be.false

    @pytest.mark.asyncio
    async def test_wait_for_function_arg_element(self):
        await self.goto_empty(waitUntil="load")
        await self.page.setContent("<div></div>")
        div = await self.page.J("div")
        fut = asyncio.ensure_future(
            self.page.waitForFunction("e => !e.parentElement", {}, div)
        )
        result = []
        fut.add_done_callback(lambda fut: result.append(True))
        await asyncio.sleep(0.1)
        result | should.have.length.of(0)
        await self.page.evaluate("e => e.remove()", div)
        await fut
        result | should.have.index.at(0).equal.to(True)


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestWaitForSelector(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_wait_for_selector_immediate(self):
        await self.goto_empty(waitUntil="load")
        frame = self.page.mainFrame
        result = []
        fut = asyncio.ensure_future(frame.waitForSelector("*"))
        fut.add_done_callback(lambda fut: result.append(True))
        await fut
        result | should.have.index.at(0).equal.to(True)
        result.clear()
        await frame.evaluate(addElement, "div")
        fut = asyncio.ensure_future(frame.waitForSelector("div"))
        fut.add_done_callback(lambda fut: result.append(True))
        await fut
        result | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_wait_for_selector_after_node_appear(self):
        await self.goto_empty(waitUntil="load")
        frame = self.page.mainFrame
        result = []
        fut = asyncio.ensure_future(frame.waitForSelector("div"))
        fut.add_done_callback(lambda fut: result.append(True))
        await frame.evaluate("() => 42") | should.be.equal.to(42)
        await asyncio.sleep(0.1)
        result | should.have.length.of(0)
        await frame.evaluate(addElement, "br")
        await asyncio.sleep(0.1)
        result | should.have.length.of(0)
        await frame.evaluate(addElement, "div")
        await fut
        result | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_wait_for_selector_inner_html(self):
        await self.goto_empty(waitUntil="load")
        fut = asyncio.ensure_future(self.page.waitForSelector("h3 div"))
        await self.page.evaluate(addElement, "span")
        await self.page.evaluate(
            '() => document.querySelector("span").innerHTML = "<h3><div></div></h3>"'
        )  # noqa: E501
        async with timeout(5) as to:
            await fut
        to.expired | should.be.false

    @pytest.mark.asyncio
    async def test_shortcut_for_main_frame(self):
        await self.goto_empty(waitUntil="load")
        await TestUtil.attachFrame(
            self.page, "frame1", self.full_test_url("empty.html")
        )
        otherFrame = self.page.frames[1]
        result = []
        fut = asyncio.ensure_future(self.page.waitForSelector("div"))
        fut.add_done_callback(lambda fut: result.append(True))
        await otherFrame.evaluate(addElement, "div")
        await asyncio.sleep(0.1)
        result | should.have.length.of(0)
        await self.page.evaluate(addElement, "div")
        await fut
        result | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_run_in_specified_frame(self):
        await self.goto_empty(waitUntil="load")
        result = []
        await TestUtil.attachFrame(
            self.page, "frame1", self.full_test_url("empty.html")
        )
        await TestUtil.attachFrame(
            self.page, "frame2", self.full_test_url("empty.html")
        )
        frame1 = self.page.frames[1]
        frame2 = self.page.frames[2]
        fut = asyncio.ensure_future(frame2.waitForSelector("div"))
        fut.add_done_callback(lambda fut: result.append(True))
        await frame1.evaluate(addElement, "div")
        await asyncio.sleep(0.1)
        result | should.have.length.of(0)
        await frame2.evaluate(addElement, "div")
        await fut
        result | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_wait_for_selector_fail(self):
        await self.reset_and_goto_empty(waitUntil="load")
        await self.page.evaluate("() => document.querySelector = null")
        await self.page.waitForSelector("*")

    @pytest.mark.asyncio
    async def test_fail_frame_detached(self):
        await self.reset_and_goto_empty(waitUntil="load")
        await TestUtil.attachFrame(
            self.page, "frame1", self.full_test_url("empty.html")
        )
        frame = self.page.frames[1]
        fut = frame.waitForSelector(".box")
        await TestUtil.detachFrame(self.page, "frame1")
        with pytest.raises(Exception):
            await fut

    @pytest.mark.asyncio
    async def test_cross_process_navigation(self):
        await self.goto_empty(waitUntil="load")
        mainFrame = self.page.mainFrame
        await self.page.goto(self.full_test_url("h1.html"), {"waitUntil": "load"})
        assert mainFrame is self.page.mainFrame

    @pytest.mark.asyncio
    async def test_wait_for_selector_visible(self):
        await self.goto_test("empty.html")
        div = []
        fut = asyncio.ensure_future(self.page.waitForSelector("div", visible=True))
        fut.add_done_callback(lambda fut: div.append(True))
        await self.page.setContent(
            '<div style="display: none; visibility: hidden;">1</div>'
        )
        await asyncio.sleep(0.1)
        div | should.have.length.of(0)
        await self.page.evaluate(
            '() => document.querySelector("div").style.removeProperty("display")'
        )  # noqa: E501
        await asyncio.sleep(0.1)
        div | should.have.length.of(0)
        await self.page.evaluate(
            '() => document.querySelector("div").style.removeProperty("visibility")'
        )  # noqa: E501
        await fut
        div | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_wait_for_selector_visible_inner(self):
        await self.goto_empty(waitUntil="load")
        div = []
        fut = asyncio.ensure_future(
            self.page.waitForSelector("div#inner", visible=True)
        )
        fut.add_done_callback(lambda fut: div.append(True))
        await self.page.setContent(
            '<div style="display: none; visibility: hidden;">'
            '<div id="inner">hi</div></div>'
        )
        await asyncio.sleep(0.1)
        div | should.have.length.of(0)
        await self.page.evaluate(
            '() => document.querySelector("div").style.removeProperty("display")'
        )  # noqa: E501
        await asyncio.sleep(0.1)
        div | should.have.length.of(0)
        await self.page.evaluate(
            '() => document.querySelector("div").style.removeProperty("visibility")'
        )  # noqa: E501
        await fut
        div | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_wait_for_selector_hidden(self):
        await self.goto_empty(waitUntil="load")
        div = []
        await self.page.setContent('<div style="display: block;"></div>')
        fut = asyncio.ensure_future(self.page.waitForSelector("div", hidden=True))
        fut.add_done_callback(lambda fut: div.append(True))
        await asyncio.sleep(0.1)
        div | should.have.length.of(0)
        await self.page.evaluate(
            '() => document.querySelector("div").style.setProperty("visibility", "hidden")'
        )  # noqa: E501
        await fut
        div | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_wait_for_selector_display_none(self):
        await self.goto_empty(waitUntil="load")
        div = []
        await self.page.setContent('<div style="display: block;"></div>')
        fut = asyncio.ensure_future(self.page.waitForSelector("div", hidden=True))
        fut.add_done_callback(lambda fut: div.append(True))
        await asyncio.sleep(0.1)
        div | should.have.length.of(0)
        await self.page.evaluate(
            '() => document.querySelector("div").style.setProperty("display", "none")'
        )  # noqa: E501
        await fut
        div | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_wait_for_selector_remove(self):
        await self.goto_empty(waitUntil="load")
        div = []
        await self.page.setContent("<div></div>")
        fut = asyncio.ensure_future(self.page.waitForSelector("div", hidden=True))
        fut.add_done_callback(lambda fut: div.append(True))
        await asyncio.sleep(0.1)
        div | should.have.length.of(0)
        await self.page.evaluate(
            '() => document.querySelector("div").remove()'
        )  # noqa: E501
        await fut
        div | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_wait_for_selector_timeout(self):
        await self.goto_empty(waitUntil="load")
        with pytest.raises(WaitTimeoutError):
            await self.page.waitForSelector("div", timeout=5)

    @pytest.mark.asyncio
    async def test_wait_for_selector_node_mutation(self):
        await self.goto_empty(waitUntil="load")
        div = []
        fut = asyncio.ensure_future(self.page.waitForSelector(".cls"))
        fut.add_done_callback(lambda fut: div.append(True))
        await self.page.setContent('<div class="noCls"></div>')
        div | should.have.length.of(0)
        await self.page.evaluate('() => document.querySelector("div").className="cls"')
        await asyncio.sleep(0.1)
        div | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_wait_for_selector_return_element(self):
        await self.goto_empty(waitUntil="load")
        selector = asyncio.ensure_future(self.page.waitForSelector(".zombo"))
        await self.page.setContent('<div class="zombo">anything</div>')
        await self.page.evaluate(
            "e => e.textContent", await selector
        ) | should.be.equal.to("anything")


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestWaitForXPath(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_fancy_xpath(self):
        await self.goto_empty()
        await self.page.setContent("<p>red heering</p><p>hello world  </p>")
        waitForXPath = await self.page.waitForXPath(
            '//p[normalize-space(.)="hello world"]'
        )  # noqa: E501
        await self.page.evaluate(
            "x => x.textContent", waitForXPath
        ) | should.be.equal.to("hello world  ")

    @pytest.mark.skip("FIX ME!!")
    @pytest.mark.asyncio
    async def test_specified_frame(self):
        await self.goto_empty()
        result = []
        await TestUtil.attachFrame(
            self.page, "frame1", self.full_test_url("empty.html")
        )
        await TestUtil.attachFrame(
            self.page, "frame2", self.full_test_url("empty.html")
        )
        frame1 = self.page.frames[1]
        frame2 = self.page.frames[2]
        fut = asyncio.ensure_future(frame2.waitForXPath("//div"))
        fut.add_done_callback(lambda fut: result.append(True))
        result | should.have.length.of(0)
        await frame1.evaluate(addElement, "div")
        result | should.have.length.of(0)
        await frame2.evaluate(addElement, "div")
        result | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_hidden(self):
        await self.goto_empty(waitUntil="load")
        result = []
        await self.page.setContent('<div style="display: block;"></div>')
        waitForXPath = asyncio.ensure_future(
            self.page.waitForXPath("//div", hidden=True)
        )
        waitForXPath.add_done_callback(lambda fut: result.append(True))
        await self.page.waitForXPath("//div")
        result | should.have.length.of(0)
        await self.page.evaluate(
            'document.querySelector("div").style.setProperty("display", "none")'
        )  # noqa: E501
        with timeout(5) as to:
            await waitForXPath
        to.expired | should.be.false
        result | should.have.index.at(0).equal.to(True)

    @pytest.mark.asyncio
    async def test_return_element_handle(self):
        await self.goto_empty(waitUntil="load")
        waitForXPath = self.page.waitForXPath('//*[@class="zombo"]')
        await self.page.setContent('<div class="zombo">anything</div>')
        await asyncio.sleep(0.5)
        await self.page.evaluate(
            "x => x.textContent", await waitForXPath
        ) | should.be.equal.to("anything")

    @pytest.mark.asyncio
    async def test_text_node(self):
        await self.goto_empty(waitUntil="load")
        await self.page.setContent("<div>some text</dev>")
        await asyncio.sleep(0.5)
        text = await self.page.waitForXPath("//div/text()")
        res = await text.getProperty("nodeType")
        await res.jsonValue() | should.be.equal.to(3)

    @pytest.mark.asyncio
    async def test_single_slash(self):
        await self.goto_empty(waitUntil="load")
        await self.page.setContent("<div>some text</div>")
        waitForXPath = self.page.waitForXPath("/html/body/div")
        await self.page.evaluate(
            "x => x.textContent", await waitForXPath
        ) | should.be.equal.to("some text")
