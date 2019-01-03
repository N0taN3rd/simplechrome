import os

import pytest
from cripy.errors import NetworkError
from grappa import should

from simplechrome.launcher import connect, launch
from .base_test import BaseChromeTest


class TestConnection(object):
    @pytest.mark.asyncio
    async def test_connect(self):
        if os.environ.get("INTRAVIS", None) is not None:
            browser = await launch(
                executablePath="google-chrome-beta",
                headless=False
            )
        else:
            browser = await launch()
        browser2 = await connect(browserWSEndpoint=browser.wsEndpoint)
        page = await browser2.newPage()
        result = await page.evaluate("() => 7 * 8")
        result | should.be.a(int).that.should.be.equal.to(56)
        await browser2.disconnect()
        page2 = await browser.newPage()
        result = await page2.evaluate("() => 7 * 6")
        result | should.be.a(int).that.should.be.equal.to(42)
        await browser.close()

    @pytest.mark.asyncio
    async def test_reconnect(self, travis_project_root):
        if os.environ.get("INTRAVIS", None) is not None:
            browser = await launch(
                executablePath="google-chrome-beta",
                headless=False
            )
        else:
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
    async def test_connection_raises_error_on_invalid_command(
        self, travis_project_root
    ):
        if os.environ.get("INTRAVIS", None) is not None:
            chrome = await launch(
                executablePath="google-chrome-beta",
                headless=False
            )
        else:
            chrome = await launch()
        page = await chrome.newPage()
        with pytest.raises(NetworkError) as ne:
            await page._client.send("Bogus.command")
        str(ne.value) | should.start_with(
            "Protocol Error (Bogus.command): 'Bogus.command' wasn't found"
        )


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestCDPSession(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_create_session(self):
        client = await self.page.target.createCDPSession()
        await client.send("Runtime.enable")
        await client.send("Runtime.evaluate", {"expression": 'window.foo = "bar"'})
        try:
            await self.page.evaluate("window.foo") | should.be.equal.to("bar")
        finally:
            await client.detach()

    @pytest.mark.asyncio
    async def test_send_event(self, ee_helper):
        client = await self.page.target.createCDPSession()
        await client.send("Network.enable")
        events = []
        ee_helper.addEventListener(
            client, "Network.requestWillBeSent", lambda e: events.append(e)
        )
        await self.goto_empty()
        try:
            assert len(events) >= 1
        finally:
            await client.detach()

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
        await client.detach()

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
