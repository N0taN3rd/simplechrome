import pytest
from grappa import should

from simplechrome.errors import ElementHandleError


@pytest.mark.usefixtures("test_server", "chrome_page")
class TestBoundingBox(object):
    @pytest.mark.asyncio
    async def test_bounding_box(self):
        await self.page.setViewport({"width": 500, "height": 500})
        await self.page.goto(f"{self.url}grid.html")
        elementHandle = await self.page.J(".box:nth-of-type(13)")
        box = await elementHandle.boundingBox()
        box | should.be.equal.to({"x": 150, "y": 50, "width": 50, "height": 50})

    @pytest.mark.asyncio
    async def test_nested_frame(self):
        await self.page.setViewport({"width": 500, "height": 500})
        await self.page.goto(f"{self.url}nested-frames.html")
        nestedFrame = self.page.frames[1].childFrames[1]
        elementHandle = await nestedFrame.J("div")
        box = await elementHandle.boundingBox()
        box["x"] | should.be.equal.to(28)
        box["y"] | should.pass_function(lambda x: x == 182 or x == 28)
        box["width"] | should.be.equal.to(249)

    @pytest.mark.asyncio
    async def test_invisible_element(self):
        await self.page.setContent('<div style="display: none;">hi</div>')
        element = await self.page.J("div")
        await element.boundingBox() | should.be.none


@pytest.mark.usefixtures("test_server", "chrome_page")
class TestClick(object):
    @pytest.mark.asyncio
    async def test_clik(self):
        await self.page.goto(f"{self.url}button.html")
        button = await self.page.J("button")
        await button.click()
        await self.page.evaluate("result") | should.be.equal.to("Clicked")

    @pytest.mark.asyncio
    async def test_shadow_dom(self):
        await self.page.goto(f"{self.url}shadow.html")
        button = await self.page.evaluateHandle("() => button")
        await button.click()
        await self.page.evaluate("clicked") | should.be.true

    @pytest.mark.asyncio
    async def test_text_node(self):
        await self.page.goto(f"{self.url}button.html")
        buttonTextNode = await self.page.evaluateHandle(
            '() => document.querySelector("button").firstChild'
        )
        with pytest.raises(ElementHandleError) as cm:
            await buttonTextNode.click()
        str(cm.value) | should.be.equal.to("Node is not of type HTMLElement")

    @pytest.mark.asyncio
    async def test_detached_node(self):
        await self.page.goto(f"{self.url}button.html")
        button = await self.page.J("button")
        await self.page.evaluate("btn => btn.remove()", button)
        with pytest.raises(ElementHandleError) as cm:
            await button.click()
        str(cm.value) | should.be.equal.to("Node is detached from document")

    @pytest.mark.asyncio
    async def test_hidden_node(self):
        await self.page.goto(f"{self.url}button.html")
        button = await self.page.J("button")
        await self.page.evaluate('btn => btn.style.display = "none"', button)
        with pytest.raises(ElementHandleError) as cm:
            await button.click()
        str(cm.value) | should.be.equal.to("Node is not visible.")

    @pytest.mark.asyncio
    async def test_recursively_hidden_node(self):
        await self.page.goto(f"{self.url}button.html")
        button = await self.page.J("button")
        await self.page.evaluate(
            'btn => btn.parentElement.style.display = "none"', button
        )
        with pytest.raises(ElementHandleError) as cm:
            await button.click()
        str(cm.value) | should.be.equal.to("Node is not visible.")

    @pytest.mark.asyncio
    async def test_br_node(self):
        await self.page.setContent("hello<br>goodbye")
        br = await self.page.J("br")
        with pytest.raises(ElementHandleError) as cm:
            await br.click()
        str(cm.value) | should.be.equal.to("Node is not visible.")


@pytest.mark.usefixtures("test_server", "chrome_page")
class TestHover(object):
    @pytest.mark.asyncio
    async def test_hover(self):
        await self.page.goto(f"{self.url}scrollable.html")
        button = await self.page.J("#button-6")
        await button.hover()
        await self.page.evaluate(
            'document.querySelector("button:hover").id'
        ) | should.be.equal.to("button-6")


@pytest.mark.usefixtures("test_server", "chrome_page")
class TestQuerySelector(object):
    @pytest.mark.asyncio
    async def test_element_handle_J(self):
        await self.page.setContent(
            """
<html><body><div class="second"><div class="inner">A</div></div></body></html>
        """
        )
        html = await self.page.J("html")
        second = await html.J(".second")
        inner = await second.J(".inner")
        content = await self.page.evaluate("e => e.textContent", inner)
        content | should.be.equal.to("A")

    @pytest.mark.asyncio
    async def test_element_handle_J_none(self):
        await self.page.setContent(
            """
<html><body><div class="second"><div class="inner">A</div></div></body></html>
        """
        )
        html = await self.page.J("html")
        second = await html.J(".third")
        second | should.be.none

    @pytest.mark.asyncio
    async def test_element_handle_JJ(self):
        await self.page.setContent(
            """
<html><body><div>A</div><br/><div>B</div></body></html>
        """
        )
        html = await self.page.J("html")
        elements = await html.JJ("div")
        len(elements) | should.be.equal.to(2)
        result = []
        for elm in elements:
            result.append(await self.page.evaluate("(e) => e.textContent", elm))
        result | should.be.equal.to(["A", "B"])

    @pytest.mark.asyncio
    async def test_element_handle_JJ_empty(self):
        await self.page.setContent(
            """
<html><body><span>A</span><br/><span>B</span></body></html>
        """
        )
        html = await self.page.J("html")
        elements = await html.JJ("div")
        len(elements) | should.be.equal.to(0)

    @pytest.mark.asyncio
    async def test_element_handle_xpath(self):
        await self.page.setContent(
            '<html><body><div class="second"><div class="inner">A</div></div></body></html>'  # noqa: E501
        )
        html = await self.page.querySelector("html")
        second = await html.xpath("./body/div[contains(@class, 'second')]")
        inner = await second[0].xpath("./div[contains(@class, 'inner')]")
        content = await self.page.evaluate("(e) => e.textContent", inner[0])
        content | should.be.equal.to("A")

    @pytest.mark.asyncio
    async def test_element_handle_xpath_not_found(self):
        await self.page.goto(self.url + "empty")
        html = await self.page.querySelector("html")
        element = await html.xpath("/div[contains(@class, 'third')]")
        element | should.be.equal.to([])
