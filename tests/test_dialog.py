import pytest
from grappa import should

from .base_test import BaseChromeTest


class TestDialog(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_prompt(self):
        await self.goto_test("dialogs.html", dict(waitUntil="networkidle0"))
        values = []

        async def dialog_test(dialog):
            values.append((dialog.type, dialog.defaultValue, dialog.message))
            await dialog.accept("answer!")

        self.page.once(self.page.Events.Dialog, dialog_test)
        answer = await self.page.evaluate("showPrompt()")
        type_, dv, m = values[0]
        type_ | should.be.a(str).equal.to("prompt")
        dv | should.be.a(str).equal.to("yes.")
        m | should.should.be.a(str).equal.to("question?")
        answer | should.be.equal.to(True)

    @pytest.mark.asyncio
    async def test_alert(self):
        await self.goto_test("dialogs.html", dict(waitUntil="networkidle0"))
        values = []

        async def dialog_test(dialog):
            values.append((dialog.type, dialog.defaultValue, dialog.message))
            await dialog.accept()

        self.page.once(self.page.Events.Dialog, dialog_test)
        await self.page.evaluate("showAlert()")
        type_, dv, m = values[0]
        type_ | should.be.a(str).equal.to("alert")
        dv | should.be.a(str).equal.to("")
        m | should.should.be.a(str).equal.to("sup")

    @pytest.mark.asyncio
    async def test_prompt_dismiss(self):
        await self.goto_test("dialogs.html", dict(waitUntil="networkidle0"))

        async def dismiss_test(dialog):
            await dialog.dismiss()

        self.page.once(self.page.Events.Dialog, dismiss_test)
        result = await self.page.evaluate("dismissPromt()")
        result | should.be.equal.to(None)
