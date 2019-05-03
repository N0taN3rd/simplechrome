import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psutil
import pytest
import shlex
import uvloop

from simplechrome.chrome import Chrome
from simplechrome.events import Events
from simplechrome.launcher import launch
from simplechrome.page import Page
from .utils import EEHandler, PageCrashState

try:
    from _pytest.fixtures import SubRequest
except Exception:
    SubRequest = object()

try:
    uvloop.install()
except Exception:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

try:
    from asyncio.runners import _cancel_all_tasks
except Exception:
    _cancel_all_tasks = lambda loop: None


async def aio_noop(*args: Any, **kwargs: Any) -> None:
    return None


def reaper(oproc):
    def kill_it():
        process = psutil.Process(oproc.pid)
        for proc in process.children(recursive=True):
            proc.kill()
        process.kill()

    return kill_it


@pytest.fixture
def ee_helper(request: SubRequest):
    eeh = EEHandler()
    yield eeh
    eeh.clean_up()


@pytest.fixture(scope="session", autouse=True)
def test_server(request: SubRequest) -> None:
    sys.stdout.write(
        f"\n{sys.executable} {str(Path(__file__).parent / 'server2.py')}\n"
    )
    server_process: subprocess.Popen = subprocess.Popen(
        [
            shlex.quote(sys.executable),
            shlex.quote(str(Path(__file__).parent / "server2.py")),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    yield server_process
    try:
        server_process.kill()
    except Exception:
        pass

    try:
        server_process.wait(10)
    except Exception:
        pass


# print('stopping server')


@pytest.fixture(scope="class")
def test_server_url(request: SubRequest) -> str:
    url = "http://localhost:8888/static/"
    if request.cls is not None:
        request.cls.static_url = url
        request.cls.base_url = "http://localhost:8888/"
    yield url


@pytest.fixture(scope="class")
async def chrome_page(request: SubRequest, chrome: Chrome) -> Page:
    page = await chrome.newPage()
    if request.cls is not None:
        request.cls.page = page
        request.cls.page_crash_state = PageCrashState()
    await page.disableNetworkCache()
    page.setDefaultTimeout(15)
    page.setDefaultJSTimeout(15)
    page.setDefaultNavigationTimeout(15)

    def handle_page_crash(e) -> None:
        if request.cls is not None:
            request.cls.page_crash_state._page_crashed()
        pytest.skip(str(e))

    page.on(Events.Page.Crashed, handle_page_crash)
    yield page
    page.remove_listener(Events.Page.Crashed, handle_page_crash)
    await page.close()


@pytest.fixture(scope="class")
def event_loop(request: SubRequest) -> asyncio.AbstractEventLoop:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    try:
        _cancel_all_tasks(loop)
        loop.run_until_complete(getattr(loop, "shutdown_asyncgens", aio_noop)())
    finally:
        loop.close()


@pytest.fixture
def travis_project_root(request: SubRequest) -> str:
    return str(Path.cwd())


@pytest.fixture(scope="class")
async def chrome(request: SubRequest) -> Chrome:
    if os.environ.get("INTRAVIS", None) is not None:
        browser = await launch(
            executablePath="google-chrome-beta", headless=False, args=["--no-sandbox"]
        )
    else:
        browser = await launch()
    yield browser
    try:
        await browser.close()
    except Exception:
        pass


@pytest.fixture
async def one_off_chrome(request: SubRequest) -> Chrome:
    if os.environ.get("INTRAVIS", None) is not None:
        browser = await launch(executablePath="google-chrome-beta", headless=False)
    else:
        browser = await launch()
    yield browser
    try:
        await browser.close()
    except Exception:
        pass
