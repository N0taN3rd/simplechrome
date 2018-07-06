from typing import Any, AsyncGenerator, Generator

import os
import psutil
import pytest
import uvloop
from _pytest.fixtures import SubRequest

from simplechrome.chrome import Chrome
from simplechrome.launcher import launch
from simplechrome.page import Page
from .server import get_app


def reaper(oproc):
    def kill_it():
        process = psutil.Process(oproc.pid)
        for proc in process.children(recursive=True):
            proc.kill()
        process.kill()

    return kill_it


@pytest.yield_fixture(scope="class")
def test_server(request: SubRequest) -> Generator[str, Any, None]:
    url = "http://localhost:8888/static/"
    app = get_app()
    if request.cls is not None:
        request.cls.url = url
    yield url
    app.clean_up()


@pytest.yield_fixture(scope="class")
async def chrome_page(request, chrome: Chrome) -> AsyncGenerator[Page, Any]:
    page = await chrome.newPage()
    if request.cls is not None:
        request.cls.page = page
    yield page


@pytest.yield_fixture(scope="class")
def event_loop() -> Generator[uvloop.Loop, Any, None]:
    loop = uvloop.new_event_loop()
    yield loop
    loop.close()


@pytest.yield_fixture
async def chrome() -> AsyncGenerator[Chrome, Any]:
    if os.environ.get('INTRAVIS', None) is not None:
        chrome = await launch(headless=False)
    else:
        chrome = await launch()
    yield chrome
    await chrome.close()


@pytest.yield_fixture(scope="class")
async def chrome() -> AsyncGenerator[Chrome, Any]:
    if os.environ.get('INTRAVIS', None) is not None:
        chrome = await launch(headless=False)
    else:
        chrome = await launch()
    yield chrome
    await chrome.close()
