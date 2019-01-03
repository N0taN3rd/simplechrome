import os

import psutil
import pytest
from async_timeout import timeout
from grappa import should

from simplechrome.errors import NetworkError
from simplechrome.launcher import Launcher, launch


class TestLauncher(object):
    def test_create_argless_no_throw(self):
        Launcher | should.do_not.raise_error(Exception)

    @pytest.mark.asyncio
    async def test_launches_chrome_no_args(self):
        async with timeout(10) as to:
            if os.environ.get("INTRAVIS", None) is not None:
                chrome = await Launcher().launch(
                    headless=False, executablePath="google-chrome-beta"
                )
            else:
                chrome = await launch()
        to.expired | should.be.false
        try:
            chrome_p = psutil.Process(chrome.process.pid)
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
    async def test_launch_fn_no_args(self):
        async with timeout(10) as to:
            if os.environ.get("INTRAVIS", None) is not None:
                chrome = await Launcher().launch(
                    headless=False, executablePath="google-chrome-beta"
                )
            else:
                chrome = await launch()
        to.expired | should.be.false
        try:
            chrome_p = psutil.Process(chrome.process.pid)
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
        if os.environ.get("INTRAVIS", None) is not None:
            chrome = await Launcher().launch(
                headless=False, executablePath="google-chrome-beta"
            )
        else:
            chrome = await launch()
        page = await chrome.newPage()
        promise = page.evaluate("() => new Promise(r => {})")
        await chrome.close()
        with pytest.raises(NetworkError):
            await promise

    @pytest.mark.asyncio
    async def test_invalid_executable_path(self):
        with pytest.raises(FileNotFoundError):
            await launch(executablePath="not-a-path")
