import pytest
from grappa import should

from simplechrome import NetworkError
from simplechrome.launcher import connect, launch


class TestConnection(object):
    @pytest.mark.asyncio
    async def test_connect(self):
        browser = await launch()
        browser2 = await connect(browserWSEndpoint=browser.wsEndpoint)
        page = await browser2.newPage()
        with should(await page.evaluate("() => 7 * 8")):
            should.be.a(int).that.should.be.equal.to(56)
        await browser2.disconnect()
        page2 = await browser.newPage()
        with should(await page2.evaluate("() => 7 * 6")):
            should.be.a(int).that.should.be.equal.to(42)
        await browser.close()

    @pytest.mark.asyncio
    async def test_reconnect(self):
        browser = await launch()
        browserWSEndpoint = browser.wsEndpoint
        await browser.disconnect()
        browser2 = await connect(browserWSEndpoint=browserWSEndpoint)
        page = await browser2.newPage()
        with should(await page.evaluate("() => 7 * 8")):
            should.be.a(int).that.should.be.equal.to(56)
        await browser2.disconnect()
        await browser.close()

    @pytest.mark.asyncio
    async def test_connection_raises_error_on_invalid_command(self, chrome):
        page = await chrome.newPage()
        with pytest.raises(NetworkError) as ne:
            await page._client.send("Bogus.command")
        str(ne.value) | should.start_with(
            "Protocol Error: 'Bogus.command' wasn't found"
        )


@pytest.mark.usefixtures("test_server", "chrome_page")
class TestCDPSession(object):
    @pytest.mark.asyncio
    async def test_create_session(self):
        client = await self.page.target.createCDPSession()
        await client.send("Runtime.enable")
        await client.send("Runtime.evaluate", {"expression": 'window.foo = "bar"'})
        await self.page.evaluate("window.foo") | should.be.equal.to("bar")

    @pytest.mark.asyncio
    async def test_send_event(self):
        client = await self.page.target.createCDPSession()
        await client.send("Network.enable")
        events = []
        client.on("Network.requestWillBeSent", lambda e: events.append(e))
        await self.page.goto(self.url + "empty.html")
        events | should.have.length.of(1)

    @pytest.mark.asyncio
    async def test_enable_disable_domain(self):
        client = await self.page.target.createCDPSession()
        await client.send("Runtime.enable")
        await client.send("Runtime.disable")
        res = await client.send(
            "Runtime.evaluate", {"expression": "1 + 3", "returnByValue": True}
        )
        with should(res):
            should.have.key("result").that.should.have.key("value").equal.to(4)

    @pytest.mark.asyncio
    async def test_detach(self):
        client = await self.page.target.createCDPSession()
        await client.send("Runtime.enable")
        evalResponse = await client.send(
            "Runtime.evaluate", {"expression": "1 + 2", "returnByValue": True}
        )
        with should(evalResponse):
            should.have.key("result").that.should.have.key("value").equal.to(3)

        await client.detach()
        with pytest.raises(NetworkError):
            await client.send(
                "Runtime.evaluate", {"expression": "1 + 3", "returnByValue": True}
            )