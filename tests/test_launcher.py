import asyncio
import psutil
import pytest
from pathlib import Path
from .assertions import expect
from simplechrome.launcher import Launcher, launch, DEFAULT_ARGS
from simplechrome.chrome import Chrome


class TestLauncher(object):
    def test_create_argless_no_throw(self):
        expect(Launcher).not_to.throw(Exception)

    def test_create_argless_default_values(self):
        l = Launcher()
        expect(l.port).to.eq(9222)
        expect(l.chrome_dead).to.be.true()
        expect(l.options).to.be.a.dict()
        expect(l.options).that.Is.empty()
        expect(l.cmd).not_to.be.empty()
        expect(l.cmd).to.contain(*DEFAULT_ARGS)

    @pytest.mark.asyncio
    async def test_launches_chrome_no_args(self):
        l = Launcher(headless=False)
        chrome = await expect(l.launch).that.it.resolves_within(10)
        temp_dir = Path(l._tmp_user_data_dir.name)
        expect(temp_dir.exists()).to.be.true()
        try:
            chrome_p = psutil.Process(chrome.process.pid)
            expect(chrome_p.name()).to.eq('chrome')
            expect(chrome_p.is_running()).to.be.true()
            cline = chrome_p.cmdline()
            expect(cline[0]).to.eq(' '.join(l.cmd))
        except Exception:
            await chrome.close()
            raise
        else:
            await expect(chrome.close).that.it.resolves_within(10)
            expect(chrome_p.is_running()).to.be.false()
            expect(temp_dir.exists()).to.be.false()

    @pytest.mark.asyncio
    async def test_launch_fn_no_args(self):
        chrome = await expect(launch).that.it.resolves_within(10)
        try:
            chrome_p = psutil.Process(chrome.process.pid)
            expect(chrome_p.name()).to.eq('chrome')
            expect(chrome_p.is_running()).to.be.true()
        except Exception:
            await chrome.close()
            raise
        else:
            await expect(chrome.close).that.it.resolves_within(10)
            expect(chrome_p.is_running()).to.be.false()
