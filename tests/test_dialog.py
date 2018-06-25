import pytest
from grappa import should
import asyncio


@pytest.mark.usefixtures("test_server", "chrome_page")
class TestCDPSession(object):
    @pytest.mark.asyncio
    async def test_alert(self):
        def dialog_test(dialog):
            dialog | should.have.property("type").that.should.be.a(str).equal.to(
                "alert"
            )
            dialog | should.have.property("defaultValue").that.should.be.a(
                str
            ).equal.to("")
            dialog | should.have.property("message").that.should.be.a(str).equal.to(
                "sup"
            )
            asyncio.ensure_future(dialog.accept())

        self.page.on("dialog", dialog_test)
        await self.page.evaluate('() => alert("sup")')

    @pytest.mark.asyncio
    async def test_prompt(self):
        def dialog_test(dialog):
            dialog | should.have.property("type").that.should.be.a(str).equal.to(
                "prompt"
            )
            dialog | should.have.property("defaultValue").that.should.be.a(
                str
            ).equal.to("yes.")
            dialog | should.have.property("message").that.should.be.a(str).equal.to(
                "question?"
            )
            asyncio.ensure_future(dialog.accept("answer!"))

        self.page.on("dialog", dialog_test)
        answer = await self.page.evaluate('() => prompt("question?", "yes.")')
        answer | should.be.equal.to("answer!")

    @pytest.mark.asyncio
    async def test_prompt_dismiss(self):
        def dismiss_test(dialog):
            asyncio.ensure_future(dialog.dismiss())

        self.page.on("dialog", dismiss_test)
        result = await self.page.evaluate('() => prompt("question?", "yes.")')
        result | should.be.none
