import asyncio
import time

import pytest
from async_timeout import timeout
from grappa import should

from simplechrome.errors import (
    ElementHandleError,
    WaitTimeoutError,
    NavigationError,
    EvaluationError,
)
from .base_test import BaseChromeTest
from .frame_utils import attachFrame, detachFrame, dumpFrames, navigateFrame

addElement = "tag=>document.body.appendChild(document.createElement(tag))"


class TestContext(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_frame_context(self):
        await self.goto_empty(waitUntil="load")
        await attachFrame(self.page, "frame1", f"{self.url}empty.html")
        self.page.frames | should.have.length(2)
        frame1 = self.page.frames[0]
        frame2 = self.page.frames[1]
        context1 = await frame1.executionContext()
        context2 = await frame2.executionContext()
        context1 | should.not_be.none
        context2 | should.not_be.none
        context1 | should.not_be.equal.to(context2)
        context1.frame | should.be.equal.to(frame1)
        context2.frame | should.be.equal.to(frame2)

        await context1.evaluate("() => window.a = 1")
        await context2.evaluate("() => window.a = 2")
        a1 = await context1.evaluate("() => window.a")
        a2 = await context2.evaluate("() => window.a")
        a1 | should.be.equal.to(1)
        a2 | should.be.equal.to(2)


class TestFrameGoto(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_navigate_subframes(self):
        await self.goto_test("one-frame.html")
        self.page.frames | should.have.length.of(2)
        self.page.frames[0].url.endswith("one-frame.html") | should.be.true
        self.page.frames[1].url.endswith("frame.html") | should.be.true
        res = await self.page.frames[1].goto(self.full_url("empty.html"))
        (res.ok or res.status == 304) | should.be.true
        (res.frame is self.page.frames[1]) | should.be.true

    @pytest.mark.asyncio
    async def test_navigate_subframes_should_fail_when_frame_detaches(self):
        await self.goto_test("one-frame.html")
        self.page.frames | should.have.length.of(2)
        navigationPromise = self.page.frames[1].goto(self.full_url("empty.html"))
        await self.page.Jeval("iframe", "frame => frame.remove()")
        with pytest.raises(NavigationError):
            await navigationPromise


class TestEvaluateHandle(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_evaluate_handle(self):
        await self.goto_empty(waitUntil="load")
        frame = self.page.mainFrame
        windowHandle = await frame.evaluateHandle("window")
        windowHandle | should.not_be.none


class TestEvaluate(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_frame_evaluate(self):
        await self.goto_empty(waitUntil="load")
        await attachFrame(self.page, "frame1", f"{self.url}empty.html")
        len(self.page.frames) | should.be.equal.to(2)
        frame1 = self.page.frames[0]
        frame2 = self.page.frames[1]
        await frame1.evaluate("() => window.a = 1")
        await frame2.evaluate("() => window.a = 2")
        a1 = await frame1.evaluate("window.a")
        a2 = await frame2.evaluate("window.a")
        a1 | should.be.equal.to(1)
        a2 | should.be.equal.to(2)

    @pytest.mark.asyncio
    async def test_frame_evaluate_after_navigation(self, ee_helper):
        await self.goto_empty(waitUntil="load")
        self.result = None

        def frame_navigated(frame):
            self.result = asyncio.ensure_future(frame.evaluate("6 * 7"))

        ee_helper.addEventListener(self.page, "framenavigated", frame_navigated)
        await self.goto_test("empty.html")
        self.result | should.not_be.none
        await self.result | should.be.equal.to(42)

    @pytest.mark.asyncio
    async def test_frame_cross_site(self):
        await self.goto_empty(waitUntil="load")
        mainFrame = self.page.mainFrame
        loc = await mainFrame.evaluate("window.location.href")
        loc | should.be.a(str).that.should.be.equal.to(f"{self.url}empty.html")

    @pytest.mark.asyncio
    async def test_frame_evaluate_with_cli_api(self):
        await self.goto_test("two-frames.html")
        results = await self.page.mainFrame.evaluate(
            "$x('//iframe').map(_if => _if.src)", withCliAPI=True
        )
        frame_url = self.full_url("frame.html")
        assert [frame_url, frame_url] == results

    @pytest.mark.asyncio
    async def test_frame_evaluate_with_cli_iife(self):
        await self.goto_test("two-frames.html")
        results = await self.page.mainFrame.evaluate(
            "(function (xpg){ return Promise.resolve(xpg('//iframe').map(_if => _if.src)); })($x);",
            withCliAPI=True,
        )
        frame_url = self.full_url("frame.html")
        assert [frame_url, frame_url] == results

    @pytest.mark.asyncio
    async def test_frame_evaluate_expression_with_cli_api(self):
        await self.goto_test("two-frames.html")
        results = await self.page.mainFrame.evaluate_expression(
            "$x('//iframe').map(_if => _if.src)", withCliAPI=True
        )
        frame_url = self.full_url("frame.html")
        assert [frame_url, frame_url] == results

    @pytest.mark.asyncio
    async def test_frame_evaluate_expression_with_cli_iife(self):
        await self.goto_test("two-frames.html")
        results = await self.page.mainFrame.evaluate_expression(
            "(function (xpg){ return Promise.resolve(xpg('//iframe').map(_if => _if.src)); })($x);",
            withCliAPI=True,
        )
        frame_url = self.full_url("frame.html")
        assert [frame_url, frame_url] == results

    @pytest.mark.asyncio
    async def test_frame_evaluate_expression(self):
        await self.goto_empty()
        results = await self.page.mainFrame.evaluate_expression(
            "Object.assign({}, {a: 1})"
        )
        assert dict(a=1) == results


class TestWaitForFunction(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_wait_for_expression(self):
        await self.goto_empty(waitUntil="load")
        fut = asyncio.ensure_future(self.page.waitForFunction("window.__FOO === 1"))
        await self.page.evaluate("window.__FOO = 1;")
        await fut

    @pytest.mark.asyncio
    async def test_wait_for_function(self):
        await self.goto_empty(waitUntil="load")
        fut = asyncio.ensure_future(
            self.page.waitForFunction("() => window.__FOO === 2")
        )
        await self.page.evaluate("window.__FOO = 2;")
        await fut

    @pytest.mark.asyncio
    async def test_wait_for_function_args(self):
        await self.goto_empty(waitUntil="load")
        fut = asyncio.ensure_future(
            self.page.waitForFunction("(a, b) => a + b === 3", {}, 1, 2)
        )
        await fut

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


class TestWaitForSelector(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_wait_for_selector_immediate(self):
        await self.goto_empty(waitUntil="load")
        frame = self.page.mainFrame
        result = []
        fut = asyncio.ensure_future(frame.waitForSelector("*"))
        fut.add_done_callback(lambda fut: result.append(True))
        await fut
        result | should.not_be.none
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
        await attachFrame(self.page, "frame1", f"{self.url}empty.html")
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
        await attachFrame(self.page, "frame1", f"{self.url}empty.html")
        await attachFrame(self.page, "frame2", f"{self.url}empty.html")
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
        await self.goto_empty(waitUntil="load")
        await self.page.evaluate("() => document.querySelector = null")
        with pytest.raises(EvaluationError):
            await self.page.waitForSelector("*")

    @pytest.mark.asyncio
    async def test_fail_frame_detached(self):
        await self.goto_empty(waitUntil="load")
        await attachFrame(self.page, "frame1", f"{self.url}empty.html")
        frame = self.page.frames[1]
        fut = frame.waitForSelector(".box")
        await detachFrame(self.page, "frame1")
        with pytest.raises(Exception):
            await fut

    # @pytest.mark.skip("FIXME!!")
    @pytest.mark.asyncio
    async def test_cross_process_navigation(self):
        await self.goto_empty(waitUntil="load")
        result = []
        fut = asyncio.ensure_future(self.page.waitForSelector("h1"))
        fut.add_done_callback(lambda fut: result.append(True))
        await asyncio.sleep(0.1)
        result | should.have.length.of(0)
        await self.page.reload()
        await asyncio.sleep(0.1)
        result | should.have.length.of(0)
        await self.page.goto(f"{self.url}h1.html", dict(waitUntil="load"))
        await fut
        result | should.have.index.at(0).equal.to(True)

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
            await self.page.waitForSelector("div", timeout=10)

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


class TestWaitForXPath(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_fancy_xpath(self):
        await self.goto_test("empty.html")
        await self.page.setContent("<p>red heering</p><p>hello world  </p>")
        waitForXPath = await self.page.waitForXPath(
            '//p[normalize-space(.)="hello world"]'
        )  # noqa: E501
        await self.page.evaluate(
            "x => x.textContent", waitForXPath
        ) | should.be.equal.to("hello world  ")

    @pytest.mark.asyncio
    async def test_specified_frame(self):
        await self.goto_empty()
        result = []
        await attachFrame(self.page, "frame1", f"{self.url}empty.html")
        await attachFrame(self.page, "frame2", f"{self.url}empty.html")
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
    async def test_evaluation_failed(self):
        await self.goto_empty()
        await self.page.evaluate("document.evaluate = null;")
        with pytest.raises(EvaluationError):
            await self.page.waitForXPath("*")

    @pytest.mark.asyncio
    async def test_frame_detached(self):
        await self.goto_empty(waitUntil="load")
        await attachFrame(self.page, "frame1", f"{self.url}empty.html")
        frame = self.page.frames[1]
        waitPromise = frame.waitForXPath('//*[@class="box"]', timeout=1000)
        await detachFrame(self.page, "frame1")
        with pytest.raises(Exception):
            await waitPromise

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


class TestFrames(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_frame_nested(self):
        await self.goto_test("nested-frames.html")
        dumped_frames = dumpFrames(self.page.mainFrame)
        dumped_frames["0"] | should.contain(
            "http://localhost:8888/static/nested-frames.html"
        )
        dumped_frames["1"] | should.contain(
            "http://localhost:8888/static/frame.html",
            "http://localhost:8888/static/two-frames.html",
        )
        dumped_frames["2"] | should.contain(
            "http://localhost:8888/static/frame.html",
            "http://localhost:8888/static/frame.html",
        )

    @pytest.mark.asyncio
    async def test_frame_events(self, ee_helper):
        await self.goto_test("empty.html")
        attachedFrames = []
        ee_helper.addEventListener(
            self.page, "frameattached", lambda f: attachedFrames.append(f)
        )
        await attachFrame(self.page, "frame1", f"{self.url}frame.html")
        with should(attachedFrames):
            should.have.length.of(1)
            should.have.index.at(0).that.should.have.property("url").equal.to(
                f"{self.url}frame.html"
            )

        navigatedFrames = []
        ee_helper.addEventListener(
            self.page, "framenavigated", lambda f: navigatedFrames.append(f)
        )
        await navigateFrame(self.page, "frame1", f"{self.url}empty.html")
        with should(navigatedFrames):
            should.have.length.of(1)
            should.have.index.at(0).that.should.have.property("url").equal.to(
                f"{self.url}empty.html"
            )

        detachedFrames = []
        ee_helper.addEventListener(
            self.page, "framedetached", lambda f: detachedFrames.append(f)
        )
        await detachFrame(self.page, "frame1")
        len(detachedFrames) | should.be.equal.to(1)
        detachedFrames[0].isDetached() | should.be.true

    @pytest.mark.asyncio
    async def test_frame_cross_process(self):
        await self.goto_test("empty.html")
        mainFrame = self.page.mainFrame
        await self.goto_test("empty.html")
        self.page.mainFrame | should.be.equal.to(mainFrame)

    @pytest.mark.asyncio
    async def test_frame_events_main(self, ee_helper):
        # no attach/detach events should be emitted on main frame
        events = []
        navigatedFrames = []
        ee_helper.addEventListener(
            self.page, "frameattached", lambda f: events.append(f)
        )
        ee_helper.addEventListener(
            self.page, "framedetached", lambda f: events.append(f)
        )
        ee_helper.addEventListener(
            self.page, "framenavigated", lambda f: navigatedFrames.append(f)
        )
        await self.goto_test("empty.html")
        events | should.have.length.of(0)
        len(navigatedFrames) | should.be.equal.to(1)

    @pytest.mark.asyncio
    async def test_frame_events_child(self, ee_helper):
        attachedFrames = []
        detachedFrames = []
        navigatedFrames = []
        ee_helper.addEventListener(
            self.page, "frameattached", lambda f: attachedFrames.append(f)
        )
        ee_helper.addEventListener(
            self.page, "framedetached", lambda f: detachedFrames.append(f)
        )
        ee_helper.addEventListener(
            self.page, "framenavigated", lambda f: navigatedFrames.append(f)
        )
        await self.goto_test("nested-frames.html")
        len(attachedFrames) | should.be.equal.to(4)
        len(detachedFrames) | should.be.equal.to(0)
        len(navigatedFrames) | should.be.equal.to(5)

        attachedFrames.clear()
        detachedFrames.clear()
        navigatedFrames.clear()
        await self.goto_test("empty.html")
        len(attachedFrames) | should.be.equal.to(0)
        len(detachedFrames) | should.be.equal.to(4)
        len(navigatedFrames) | should.be.equal.to(1)

    @pytest.mark.asyncio
    async def test_frame_name(self):
        await self.goto_test("empty.html")
        await attachFrame(self.page, "FrameId", f"{self.url}empty.html")
        await asyncio.sleep(0.1)
        await self.page.evaluate(
            """(url) => {
                const frame = document.createElement('iframe');
                frame.name = 'FrameName';
                frame.src = url;
                document.body.appendChild(frame);
                return new Promise(x => frame.onload = x);
            }""",
            f"{self.url}empty.html",
        )
        await asyncio.sleep(0.1)

        frame1 = self.page.frames[0]
        frame2 = self.page.frames[1]
        frame3 = self.page.frames[2]
        frame1.name | should.be.equal.to("")
        frame2.name | should.be.equal.to("FrameId")
        frame3.name | should.be.equal.to("FrameName")

    @pytest.mark.asyncio
    async def test_frame_parent(self):
        await self.goto_test("empty.html")
        await attachFrame(self.page, "frame1", f"{self.url}empty.html")
        await attachFrame(self.page, "frame2", f"{self.url}empty.html")
        frame1 = self.page.frames[0]
        frame2 = self.page.frames[1]
        frame3 = self.page.frames[2]
        frame1 | should.be.equal.to(self.page.mainFrame)
        frame1.parentFrame | should.be.equal.to(None)
        frame2.parentFrame | should.be.equal.to(frame1)
        frame3.parentFrame | should.be.equal.to(frame1)
