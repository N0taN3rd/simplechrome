import asyncio
import os
from pathlib import Path

import psutil
import pytest
import uvloop
from _pytest.fixtures import SubRequest

from simplechrome.chrome import Chrome
from simplechrome.launcher import launch
from simplechrome.page import Page
from .server import get_app
from .utils import EEHandler

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


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
    app = get_app()
    yield
    app.clean_up()
    # print('stopping server')


@pytest.fixture(scope="class")
def test_server_url(request: SubRequest) -> str:
    url = "http://localhost:8888/static/"
    if request.cls is not None:
        request.cls.url = url
    yield url


@pytest.fixture(scope="class")
async def chrome_page(request, chrome: Chrome) -> Page:
    page = await chrome.newPage()
    if request.cls is not None:
        request.cls.page = page
    yield page
    await page.close()


@pytest.fixture(scope="class")
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    try:
        loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        loop.close()


@pytest.fixture
def travis_project_root() -> str:
    return str(Path.cwd())


@pytest.fixture(scope="class")
async def chrome() -> Chrome:
    if os.environ.get("INTRAVIS", None) is not None:
        browser = await launch(executablePath="google-chrome-beta", headless=False)
    else:
        browser = await launch()
    yield browser
    await browser.close()
    try:
        browser.process.wait()
    except Exception:
        pass
