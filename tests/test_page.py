import asyncio
import math
import time

import pytest
from grappa import should

from simplechrome.errors import (
    ElementHandleError,
    PageError,
    NavigationTimeoutError,
    EvaluationError,
)
from .base_test import BaseChromeTest
from .frame_utils import attachFrame

iPhone = {
    "name": "iPhone 6",
    "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 Mobile/13B143 Safari/601.1",  # noqa: E501
    "viewport": {
        "width": 375,
        "height": 667,
        "deviceScaleFactor": 2,
        "isMobile": True,
        "hasTouch": True,
        "isLandscape": False,
    },
}


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestEvaluate(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_evaluate(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate("() => 7 * 3")
        result | should.be.equal.to(21)

    @pytest.mark.asyncio
    async def test_await_promise(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate("() => Promise.resolve(8 * 7)")
        result | should.be.equal.to(56)

    @pytest.mark.asyncio
    async def test_after_framenavigation(self, ee_helper):
        frameEvaluation = asyncio.get_event_loop().create_future()

        async def evaluate_frame(frame):
            frameEvaluation.set_result(await frame.evaluate("() => 6 * 7"))

        ee_helper.addEventListener(
            self.page,
            "framenavigated",
            lambda frame: asyncio.ensure_future(evaluate_frame(frame)),
        )

        await self.goto_test("empty.html")
        await frameEvaluation
        frameEvaluation.result() | should.be.equal.to(42)

    @pytest.mark.asyncio
    async def test_promise_reject(self):
        await self.goto_empty(waitUntil="load")
        with pytest.raises(EvaluationError) as cm:
            await self.page.evaluate("() => not.existing.object.property")
        str(cm.value) | should.contain("not is not defined")

    @pytest.mark.asyncio
    async def test_return_complex_object(self):
        await self.goto_empty(waitUntil="load")
        obj = {"foo": "bar!"}
        result = await self.page.evaluate("(a) => a", obj)
        result | should.be.equal.to(obj)

    @pytest.mark.asyncio
    async def test_return_nan(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate("() => NaN")
        result | should.be.none

    @pytest.mark.asyncio
    async def test_return_minus_zero(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate("() => -0")
        result | should.be.equal.to(-0)

    @pytest.mark.asyncio
    async def test_return_infinity(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate("() => Infinity")
        result | should.be.equal.to(math.inf)

    @pytest.mark.asyncio
    async def test_return_infinity_minus(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate("() => -Infinity")
        result | should.be.equal.to(-math.inf)

    @pytest.mark.asyncio
    async def test_accept_none(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate(
            '(a, b) => Object.is(a, null) && Object.is(b, "foo")', None, "foo"
        )
        result | should.be.true

    @pytest.mark.asyncio
    async def test_serialize_null_field(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate("() => {a: undefined}")
        result | should.be.equal.to(None)

    @pytest.mark.asyncio
    async def test_fail_window_object(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate("() => window")
        result | should.be.none

    @pytest.mark.asyncio
    async def test_accept_string(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate("1 + 2")
        result | should.be.equal.to(3)

    @pytest.mark.asyncio
    async def test_accept_string_with_semicolon(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate("1 + 5;")
        result | should.be.equal.to(6)

    @pytest.mark.asyncio
    async def test_accept_string_with_comments(self):
        await self.goto_empty(waitUntil="load")
        result = await self.page.evaluate("2 + 5;\n// do some math!")
        result | should.be.equal.to(7)

    @pytest.mark.asyncio
    async def test_element_handle_as_argument(self):
        await self.goto_empty(waitUntil="load")
        await self.page.setContent("<section>42</section>")
        element = await self.page.J("section")
        text = await self.page.evaluate("(e) => e.textContent", element)
        text | should.be.equal.to("42")

    @pytest.mark.asyncio
    async def test_element_handle_disposed(self):
        await self.goto_empty(waitUntil="load")
        await self.page.setContent("<section>39</section>")
        element = await self.page.J("section")
        element | should.not_be.none
        await element.dispose()
        with pytest.raises(ElementHandleError) as cm:
            await self.page.evaluate("(e) => e.textContent", element)
        str(cm.value) | should.be.equal.to("JSHandle is disposed!")

    @pytest.mark.asyncio
    async def test_element_handle_from_other_frame(self):
        await self.goto_empty(waitUntil="load")
        await attachFrame(self.page, "frame1", self.url + "empty.html")
        body = await self.page.frames[1].J("body")
        with pytest.raises(ElementHandleError) as cm:
            await self.page.evaluate("body => body.innerHTML", body)
        str(cm.value) | should.be.equal.to(
            "JSHandles can be evaluated only in the context they were created!"
        )

    @pytest.mark.asyncio
    async def test_object_handle_as_argument(self):
        await self.goto_empty(waitUntil="load")
        navigator = await self.page.evaluateHandle("() => navigator")
        navigator | should.not_be.none
        text = await self.page.evaluate("(e) => e.userAgent", navigator)
        text | should.contain("Mozilla")

    @pytest.mark.asyncio
    async def test_object_handle_to_primitive_value(self):
        await self.goto_empty(waitUntil="load")
        aHandle = await self.page.evaluateHandle("() => 5")
        isFive = await self.page.evaluate("(e) => Object.is(e, 5)", aHandle)
        isFive | should.be.true


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestOfflineMode(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_offline_mode(self):
        await self.page.setOfflineMode(True)
        had_error = False
        try:
            await self.goto_test("empty.html")
        except Exception as e:
            had_error = True
        await self.page.setOfflineMode(False)
        had_error | should.be.true
        res = await self.page.reload()
        (res.status in [200, 304]) | should.be.true

    @pytest.mark.asyncio
    async def test_emulate_navigator_offline(self):
        await self.page.evaluate("window.navigator.onLine") | should.be.true
        await self.page.setOfflineMode(True)
        await self.page.evaluate("window.navigator.onLine") | should.be.false
        await self.page.setOfflineMode(False)
        await self.page.evaluate("window.navigator.onLine") | should.be.true


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestEvaluateHandle(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_evaluate_handle(self):
        windowHandle = await self.page.evaluateHandle("() => window")
        windowHandle | should.not_be.none


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestWaitFor(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_wait_for_selector(self):
        result = []
        fut = asyncio.ensure_future(self.page.waitFor("div"))
        fut.add_done_callback(lambda f: result.append(True))
        await self.goto_test("empty.html")
        result | should.have.length.of(0)
        await self.goto_test("grid.html")
        await fut
        result | should.have.length.of(1)
        await self.goto_test("empty.html")

    @pytest.mark.asyncio
    async def test_wait_for_xpath(self):
        result = []
        waitFor = asyncio.ensure_future(self.page.waitFor("//div"))
        waitFor.add_done_callback(lambda fut: result.append(True))
        await self.goto_test("empty.html")
        result | should.have.length.of(0)
        await self.goto_test("grid.html")
        await waitFor
        result | should.have.length.of(1)

    @pytest.mark.asyncio
    async def test_single_slash_fail(self):
        await self.page.setContent("<div>some text</div>")
        with pytest.raises(Exception):
            await self.page.waitFor("/html/body/div")

    @pytest.mark.asyncio
    async def test_wait_for_timeout(self):
        result = []
        start_time = time.perf_counter()
        fut = asyncio.ensure_future(self.page.waitFor(100))
        fut.add_done_callback(lambda f: result.append(True))
        await fut
        time.perf_counter() - start_time | should.be.above(0.01)
        result | should.have.length.of(1)

    @pytest.mark.asyncio
    async def test_wait_for_error_type(self):
        with pytest.raises(TypeError) as cm:
            await self.page.waitFor({"a": 1})
        str(cm.value) | should.be.equal.to("Unsupported target type: <class 'dict'>")

    @pytest.mark.asyncio
    async def test_wait_for_func_with_args(self):
        await self.page.waitFor("(arg1, arg2) => arg1 !== arg2", {}, 1, 2)


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestConsole(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_console_event(self, ee_helper):
        messages = []
        ee_helper.addEventListener(self.page, "console", lambda m: messages.append(m))
        await self.page.evaluate('() => console.log("hello", 5, {foo: "bar"})')
        await asyncio.sleep(0.01)
        len(messages) | should.be.equal.to(1)

        msg = messages[0]
        msg.type | should.be.equal.to("log")
        msg.text | should.be.equal.to("hello 5 JSHandle@object")
        await msg.args[0].jsonValue() | should.be.equal.to("hello")
        await msg.args[1].jsonValue() | should.be.equal.to(5)
        await msg.args[2].jsonValue() | should.be.equal.to({"foo": "bar"})

    @pytest.mark.asyncio
    async def test_console_event_many(self, ee_helper):
        messages = []
        ee_helper.addEventListener(self.page, "console", lambda m: messages.append(m))
        await self.page.evaluate(
            """
// A pair of time/timeEnd generates only one Console API call.
console.time('calling console.time');
console.timeEnd('calling console.time');
console.trace('calling console.trace');
console.dir('calling console.dir');
console.warn('calling console.warn');
console.error('calling console.error');
console.log(Promise.resolve('should not wait until resolved!'));
        """
        )
        await asyncio.sleep(0.1)
        [msg.type for msg in messages] | should.be.equal.to(
            ["timeEnd", "trace", "dir", "warning", "error", "log"]
        )
        messages[0].text | should.contain("calling console.time")
        [msg.text for msg in messages[1:]] | should.be.equal.to(
            [
                "calling console.trace",
                "calling console.dir",
                "calling console.warn",
                "calling console.error",
                "JSHandle@promise",
            ]
        )

    @pytest.mark.asyncio
    async def test_console_window(self):
        messages = []
        self.page.once("console", lambda m: messages.append(m))
        await self.page.evaluate("console.error(window);")
        await asyncio.sleep(0.1)
        len(messages) | should.be.equal.to(1)
        msg = messages[0]
        msg.text | should.be.equal.to("JSHandle@object")


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestDOMContentLoaded(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_fired(self):
        result = []
        self.page.once("domcontentloaded", result.append(True))
        result | should.have.length.of(1)


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestRequest(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_request(self, ee_helper):
        requests = []

        def no_favico(req):
            if ".ico" not in req.url:
                requests.append(req)

        ee_helper.addEventListener(self.page, "request", no_favico)
        await self.goto_test("empty.html")
        await attachFrame(self.page, "frame1", self.url + "empty.html")
        requests[0].url | should.be.equal.to(self.url + "empty.html")
        requests[0].frame | should.be.equal.to(self.page.mainFrame)
        requests[0].frame.url | should.be.equal.to(self.url + "empty.html")
        requests[1].url | should.be.equal.to(self.url + "empty.html")
        requests[1].frame | should.be.equal.to(self.page.frames[1])
        requests[1].frame.url | should.be.equal.to(self.url + "empty.html")


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestQuerySelector(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_jeval(self):
        await self.goto_test("empty.html")
        await self.page.setContent('<section id="testAttribute">43543</section>')
        idAttribute = await self.page.Jeval("section", "e => e.id")
        idAttribute | should.be.equal.to("testAttribute")

    @pytest.mark.asyncio
    async def test_jeval_argument(self):
        await self.goto_test("empty.html")
        await self.page.setContent("<section>hello</section>")
        text = await self.page.Jeval(
            "section", "(e, suffix) => e.textContent + suffix", " world!"
        )
        text | should.be.equal.to("hello world!")

    @pytest.mark.asyncio
    async def test_jeval_argument_element(self):
        await self.goto_test("empty.html")
        await self.page.setContent("<section>hello</section><div> world</div>")
        divHandle = await self.page.J("div")
        text = await self.page.Jeval(
            "section", "(e, div) => e.textContent + div.textContent", divHandle
        )
        text | should.be.equal.to("hello world")

    @pytest.mark.asyncio
    async def test_jeval_not_found(self):
        await self.goto_test("empty.html")
        with pytest.raises(PageError) as cm:
            await self.page.Jeval("section", "e => e.id")
        str(cm.value) | should.be.equal.to(
            'Error: failed to find element matching selector "section"'
        )

    @pytest.mark.asyncio
    async def test_JJeval(self):
        await self.goto_empty(waitUntil="load")
        await self.page.setContent(
            "<div>hello</div><div>beautiful</div><div>world</div>"
        )
        divsCount = await self.page.JJeval("div", "divs => divs.length")
        divsCount | should.be.equal.to(3)

    @pytest.mark.asyncio
    async def test_query_selector(self):
        await self.goto_empty(waitUntil="load")
        await self.page.setContent("<section>test</section>")
        element = await self.page.J("section")
        element | should.not_be.none

    @pytest.mark.asyncio
    async def test_query_selector_all(self):
        await self.goto_empty(waitUntil="load")
        await self.page.setContent("<div>A</div><br/><div>B</div>")
        elements = await self.page.JJ("div")
        len(elements) | should.be.equal.to(2)
        results = []
        for e in elements:
            results.append(await self.page.evaluate("e => e.textContent", e))
        results | should.be.equal.to(["A", "B"])

    @pytest.mark.asyncio
    async def test_query_selector_all_not_found(self):
        await self.goto_test("empty.html")
        elements = await self.page.JJ("div")
        len(elements) | should.be.equal.to(0)

    @pytest.mark.asyncio
    async def test_xpath(self):
        await self.goto_empty(waitUntil="load")
        await self.page.setContent("<section>test</section>")
        element = await self.page.xpath("/html/body/section")
        element | should.not_be.none

    @pytest.mark.asyncio
    async def test_xpath_alias(self):
        await self.goto_empty(waitUntil="load")
        await self.page.setContent("<section>test</section>")
        element = await self.page.Jx("/html/body/section")
        element | should.not_be.none

    @pytest.mark.asyncio
    async def test_xpath_not_found(self):
        await self.goto_empty(waitUntil="load")
        element = await self.page.xpath("/html/body/no-such-tag")
        element | should.be.equal.to([])

    @pytest.mark.asyncio
    async def test_xpath_multiple(self):
        await self.goto_empty(waitUntil="load")
        await self.page.setContent("<div></div><div></div>")
        element = await self.page.xpath("/html/body/div")
        len(element) | should.be.equal.to(2)


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestSetContent(BaseChromeTest):
    expectedOutput = "<html><head></head><body><div>hello</div></body></html>"

    @pytest.mark.asyncio
    async def test_set_content(self):
        await self.page.setContent("<div>hello</div>")
        result = await self.page.content()
        result | should.be.equal.to(self.expectedOutput)

    @pytest.mark.asyncio
    async def test_with_doctype(self):
        doctype = "<!DOCTYPE html>"
        await self.page.setContent(doctype + "<div>hello</div>")
        result = await self.page.content()
        result | should.be.equal.to(doctype + self.expectedOutput)

    @pytest.mark.asyncio
    async def test_with_html4_doctype(self):
        doctype = (
            '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN" '
            '"http://www.w3.org/TR/html4/strict.dtd">'
        )
        await self.page.setContent(doctype + "<div>hello</div>")
        result = await self.page.content()
        result | should.be.equal.to(doctype + self.expectedOutput)


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestUrl(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_url(self):
        await self.page.goto("about:blank")
        self.page.url | should.be.equal.to("about:blank")
        await self.goto_test("empty.html")
        self.page.url | should.be.equal.to(self.url + "empty.html")


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestGoto(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_goto_time_out(self):
        with pytest.raises(
            NavigationTimeoutError,
            message="Navigation Timeout Exceeded: 5 seconds exceeded",
        ):
            await self.goto_test("never-loads1.html", waitUntil="load", timeout=5)
