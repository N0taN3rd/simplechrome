import pytest
from grappa import should

from simplechrome.events import Events
from .base_test import BaseChromeTest


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class TestDialog(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_prompt(self):
        await self.goto_test("dialogs.html", dict(waitUntil="load"))
        values = []

        async def dialog_test(dialog):
            values.append((dialog.type, dialog.defaultValue, dialog.message))
            await dialog.accept("answer!")

        self.page.once(Events.Page.Dialog, dialog_test)
        answer = await self.page.evaluate("showPrompt()")
        type_, dv, m = values[0]
        type_ | should.be.a(str).equal.to("prompt")
        dv | should.be.a(str).equal.to("yes.")
        m | should.should.be.a(str).equal.to("question?")
        answer | should.be.equal.to(True)

    @pytest.mark.asyncio
    async def test_alert(self):
        await self.goto_test("dialogs.html", dict(waitUntil="load"))
        values = []

        async def dialog_test(dialog):
            values.append((dialog.type, dialog.defaultValue, dialog.message))
            await dialog.accept()

        self.page.once(Events.Page.Dialog, dialog_test)
        await self.page.evaluate("showAlert()")
        type_, dv, m = values[0]
        type_ | should.be.a(str).equal.to("alert")
        dv | should.be.a(str).equal.to("")
        m | should.should.be.a(str).equal.to("sup")

    @pytest.mark.asyncio
    async def test_prompt_dismiss(self):
        await self.goto_test("dialogs.html", dict(waitUntil="load"))

        async def dismiss_test(dialog):
            await dialog.dismiss()

        self.page.once(Events.Page.Dialog, dismiss_test)
        result = await self.page.evaluate("dismissPromt()")
        result | should.be.equal.to(None)
