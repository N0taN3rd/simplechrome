import asyncio

import pytest
from grappa import should

from simplechrome.events import Events

from .base_test import BaseChromeTest
from .utils import TestUtil

addElement = "tag => document.body.appendChild(document.createElement(tag))"


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestFrameExecutionContext(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_should_work(self):
        await self.goto_empty(waitUntil="load")
        await TestUtil.attachFrame(self.page, "frame1", self.full_test_url("empty.html"))
        assert len(self.page.frames) == 2
        frame1 = self.page.frames[0]
        frame2 = self.page.frames[1]
        context1 = await frame1.executionContext()
        context2 = await frame2.executionContext()
        assert context1 is not None
        assert context2 is not None
        assert context1 is not context2
        assert context1.frame is frame1
        assert context2.frame is frame2
        await context1.evaluate("() => window.a = 1")
        await context2.evaluate("() => window.a = 2")
        a1 = await context1.evaluate("() => window.a")
        a2 = await context2.evaluate("() => window.a")
        assert a1 == 1
        assert a2 == 2


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestFrameEvaluates(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_evaluateHandle_should_work(self):
        await self.goto_empty(waitUntil="load")
        frame = self.page.mainFrame
        windowHandle = await frame.evaluateHandle("window")
        assert windowHandle is not None

    @pytest.mark.asyncio
    async def test_evaluate_should_work(self):
        await self.reset_and_goto_empty(waitUntil="load")
        await TestUtil.attachFrame(self.page, "frame1", self.full_test_url("empty.html"))
        assert len(self.page.frames) == 2
        frame1 = self.page.frames[0]
        frame2 = self.page.frames[1]
        await frame1.evaluate("() => window.a = 1")
        await frame2.evaluate("() => window.a = 2")
        a1 = await frame1.evaluate("window.a")
        a2 = await frame2.evaluate("window.a")
        assert a1 == 1
        assert a2 == 2

    @pytest.mark.asyncio
    async def test_frame_evaluate_after_navigation(self, ee_helper, event_loop):
        promise = event_loop.create_future()

        async def frame_navigated(frame):
            try:
                result = await frame.evaluate("6 * 7")
                promise.set_result(result)
            except Exception as e:
                promise.set_exception(e)

        ee_helper.addEventListener(self.page, Events.Page.FrameNavigated, frame_navigated)
        await self.reset_and_goto_empty(waitUntil="load")
        await promise | should.be.equal.to(42)

    @pytest.mark.asyncio
    async def test_frame_evaluate_with_cli_api(self):
        await self.reset_and_goto_test("two-frames.html")
        results = await self.page.mainFrame.evaluate(
            "$x('//iframe').map(_if => _if.src)", withCliAPI=True
        )
        assert len(results) == 2
        frame_url = self.full_test_url("frame.html")
        assert [frame_url, frame_url] == results

    @pytest.mark.asyncio
    async def test_frame_evaluate_with_cli_iife(self):
        await self.reset_and_goto_test("two-frames.html")
        results = await self.page.mainFrame.evaluate(
            "(function (xpg){ return Promise.resolve(xpg('//iframe').map(_if => _if.src)); })($x);",
            withCliAPI=True,
        )
        assert len(results) == 2
        frame_url = self.full_test_url("frame.html")
        assert [frame_url, frame_url] == results

    @pytest.mark.asyncio
    async def test_frame_evaluate_expression_with_cli_api(self):
        await self.reset_and_goto_test("two-frames.html")
        results = await self.page.mainFrame.evaluate_expression(
            "$x('//iframe').map(_if => _if.src)", withCliAPI=True
        )
        assert len(results) == 2
        frame_url = self.full_test_url("frame.html")
        assert [frame_url, frame_url] == results

    @pytest.mark.asyncio
    async def test_frame_evaluate_expression_with_cli_iife(self):
        await self.reset_and_goto_test("two-frames.html")
        results = await self.page.mainFrame.evaluate_expression(
            "(function (xpg){ return Promise.resolve(xpg('//iframe').map(_if => _if.src)); })($x);",
            withCliAPI=True,
        )
        assert len(results) == 2
        frame_url = self.full_test_url("frame.html")
        assert [frame_url, frame_url] == results

    @pytest.mark.asyncio
    async def test_frame_evaluate_expression(self):
        results = await self.page.mainFrame.evaluate_expression(
            "Object.assign({}, {a: 1})"
        )
        assert dict(a=1) == results


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestFrameManagement(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_navigate_subframes(self):
        await self.goto_test("one-frame.html")
        assert len(self.page.frames) == 2
        self.page.frames[0].url.endswith("one-frame.html") | should.be.true
        self.page.frames[1].url.endswith("frame.html") | should.be.true
        res = await self.page.frames[1].goto(self.full_test_url("empty.html"))
        assert res.ok or res.status == 304
        assert res.frame is self.page.frames[1]

    @pytest.mark.asyncio
    async def test_frame_nested(self):
        await self.reset_and_goto_test("nested-frames.html")
        dumped_frames = TestUtil.dumpFrames(self.page.mainFrame)
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
        await self.reset_and_goto_empty()
        attachedFrames = []
        ee_helper.addEventListener(
            self.page, Events.Page.FrameAttached, lambda f: attachedFrames.append(f)
        )
        await TestUtil.attachFrame(self.page, "frame1", self.full_test_url("frame.html"))
        with should(attachedFrames):
            should.have.length.of(1)
            should.have.index.at(0).that.should.have.property("url").equal.to(
                self.full_test_url("frame.html")
            )

        navigatedFrames = []
        ee_helper.addEventListener(
            self.page, Events.Page.FrameNavigated, lambda f: navigatedFrames.append(f)
        )
        await TestUtil.navigateFrame(self.page, "frame1", self.full_test_url("empty.html"))
        with should(navigatedFrames):
            should.have.length.of(1)
            should.have.index.at(0).that.should.have.property("url").equal.to(
                self.full_test_url("empty.html")
            )

        detachedFrames = []
        ee_helper.addEventListener(
            self.page, Events.Page.FrameDetached, lambda f: detachedFrames.append(f)
        )
        await TestUtil.detachFrame(self.page, "frame1")
        len(detachedFrames) | should.be.equal.to(1)
        detachedFrames[0].isDetached() | should.be.true

    @pytest.mark.asyncio
    async def test_should_persit_main_frame_across_navigations(self):
        await self.reset_and_goto_empty()
        mainFrame = self.page.mainFrame
        await self.reset_and_goto_empty()
        self.page.mainFrame | should.be.equal.to(mainFrame)

    @pytest.mark.asyncio
    async def test_frame_events_main(self, ee_helper):
        # no attach/detach events should be emitted on main frame
        events = []
        navigatedFrames = []
        ee_helper.addEventListener(
            self.page, Events.Page.FrameAttached, lambda f: events.append(f)
        )
        ee_helper.addEventListener(
            self.page, Events.Page.FrameDetached, lambda f: events.append(f)
        )
        ee_helper.addEventListener(
            self.page, Events.Page.FrameNavigated, lambda f: navigatedFrames.append(f)
        )
        await self.reset_and_goto_empty()
        events | should.have.length.of(0)
        len(navigatedFrames) | should.be.equal.to(2)

    @pytest.mark.asyncio
    async def test_frame_events_child(self, ee_helper):
        attachedFrames = []
        detachedFrames = []
        navigatedFrames = []
        ee_helper.addEventListener(
            self.page, Events.Page.FrameAttached, lambda f: attachedFrames.append(f)
        )
        ee_helper.addEventListener(
            self.page, Events.Page.FrameDetached, lambda f: detachedFrames.append(f)
        )
        ee_helper.addEventListener(
            self.page, Events.Page.FrameNavigated, lambda f: navigatedFrames.append(f)
        )
        await self.reset_and_goto_test("nested-frames.html")
        len(attachedFrames) | should.be.equal.to(4)
        len(detachedFrames) | should.be.equal.to(0)
        len(navigatedFrames) | should.be.equal.to(6)

        attachedFrames.clear()
        detachedFrames.clear()
        navigatedFrames.clear()
        await self.reset_and_goto_empty()
        len(attachedFrames) | should.be.equal.to(0)
        len(detachedFrames) | should.be.equal.to(4)
        len(navigatedFrames) | should.be.equal.to(2)

    @pytest.mark.asyncio
    async def test_frame_name(self):
        await self.reset_and_goto_empty()
        await TestUtil.attachFrame(self.page, "FrameId", self.full_test_url("empty.html"))
        await asyncio.sleep(0.1)
        await self.page.evaluate(
            """(url) => {
                const frame = document.createElement('iframe');
                frame.name = 'FrameName';
                frame.src = url;
                document.body.appendChild(frame);
                return new Promise(x => frame.onload = x);
            }""",
            self.full_test_url("empty.html"),
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
        await self.reset_and_goto_empty()
        await TestUtil.attachFrame(self.page, "frame1", self.full_test_url("empty.html"))
        await TestUtil.attachFrame(self.page, "frame2", self.full_test_url("empty.html"))
        frame1 = self.page.frames[0]
        frame2 = self.page.frames[1]
        frame3 = self.page.frames[2]
        frame1 | should.be.equal.to(self.page.mainFrame)
        frame1.parentFrame | should.be.equal.to(None)
        frame2.parentFrame | should.be.equal.to(frame1)
        frame3.parentFrame | should.be.equal.to(frame1)
