import pytest
from grappa import should
import asyncio


@pytest.mark.usefixtures("test_server", "chrome_page")
class TestCDPSession(object):
    @pytest.mark.asyncio
    async def test_alert(self):
        values = []

        def dialog_test(dialog):
            values.append((dialog.type, dialog.defaultValue, dialog.message))
            asyncio.ensure_future(dialog.accept())

        self.page.on("dialog", dialog_test)
        await self.page.evaluate('() => alert("sup")')
        type_, dv, m = values[0]
        type_ | should.be.a(str).equal.to("alert")
        dv | should.be.a(str).equal.to("")
        m | should.should.be.a(str).equal.to("sup")

    @pytest.mark.skip("FIXME!!")
    @pytest.mark.asyncio
    async def test_prompt(self):
        values = []

        async def dialog_test(dialog):
            values.append((dialog.type, dialog.defaultValue, dialog.message))
            await dialog.accept("answer!")

        self.page.on("dialog", dialog_test)
        answer = await self.page.evaluate('() => prompt("question?", "yes.")')
        type_, dv, m = values[0]
        type_ | should.be.a(str).equal.to("prompt")
        dv | should.be.a(str).equal.to("yes.")
        m | should.should.be.a(str).equal.to("question?")
        answer | should.be.equal.to("answer!")

    @pytest.mark.asyncio
    async def test_prompt_dismiss(self):
        def dismiss_test(dialog):
            asyncio.ensure_future(dialog.dismiss())
        self.page.on("dialog", dismiss_test)
        result = await self.page.evaluate('() => prompt("question?", "yes.")')
        result | should.be.equal.to("")
