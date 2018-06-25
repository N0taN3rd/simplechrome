from pathlib import Path

import psutil
import pytest
from async_timeout import timeout
from grappa import should

from simplechrome.errors import NetworkError
from simplechrome.launcher import Launcher, launch, DEFAULT_ARGS


class TestLauncher(object):
    def test_create_argless_no_throw(self):
        Launcher | should.do_not.raise_error(Exception)

    def test_create_argless_default_values(self):
        l = Launcher()
        l.port | should.be.equal.to(9222)
        l.chrome_dead | should.be.true
        with should(l.options):
            should.be.a(dict)
            should.have.length(0)
        with should(l.cmd):
            should.not_have.length.equal.to(0)
            should.that.contains(*DEFAULT_ARGS)

    @pytest.mark.asyncio
    async def test_launches_chrome_no_args(self):
        l = Launcher()
        async with timeout(10) as to:
            chrome = await l.launch()
        to.expired | should.be.false
        tempdir = Path(l._tmp_user_data_dir.name)
        tempdir.exists() | should.be.true
        try:
            chrome_p = psutil.Process(chrome.process.pid)
            chrome_p.name() | should.be.equal.to("chrome")
            chrome_p.is_running() | should.be.true
            cline = chrome_p.cmdline()
            cline[0] | should.be.equal.to(" ".join(l.cmd))
        except Exception:
            await chrome.close()
            raise
        else:
            async with timeout(10) as to:
                await chrome.close()
            to.expired | should.be.false
            chrome_p.is_running() | should.be.false
            tempdir.exists() | should.be.false

    @pytest.mark.asyncio
    async def test_launch_fn_no_args(self):
        async with timeout(10) as to:
            chrome = await launch()
        to.expired | should.be.false
        try:
            chrome_p = psutil.Process(chrome.process.pid)
            chrome_p.name() | should.be.equal.to("chrome")
            chrome_p.is_running() | should.be.true
        except Exception:
            await chrome.close()
            raise
        else:
            async with timeout(10) as to:
                await chrome.close()
            to.expired | should.be.false
            chrome_p.is_running() | should.be.false

    @pytest.mark.asyncio
    async def test_await_after_close(self):
        browser = await launch()
        page = await browser.newPage()
        promise = page.evaluate("() => new Promise(r => {})")
        await browser.close()
        with pytest.raises(NetworkError):
            await promise

    @pytest.mark.asyncio
    async def test_invalid_executable_path(self):
        with pytest.raises(FileNotFoundError):
            await launch(executablePath="not-a-path")
