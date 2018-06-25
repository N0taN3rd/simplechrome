import os
import subprocess
import sys
import time
from typing import Any, AsyncGenerator, Generator
from urllib.error import URLError
from urllib.request import urlopen

import psutil
import pytest
import uvloop
from _pytest.fixtures import SubRequest

from simplechrome.chrome import Chrome
from simplechrome.launcher import launch
from simplechrome.page import Page


def reaper(oproc):
    def kill_it():
        process = psutil.Process(oproc.pid)
        for proc in process.children(recursive=True):
            proc.kill()
        process.kill()

    return kill_it


@pytest.yield_fixture(scope="class")
def test_server(request: SubRequest) -> Generator[str, Any, None]:
    url = "http://0.0.0.0:8888/static/"
    if "/tests" in os.getcwd():
        exe = "server.py"
    else:
        exe = "tests/server.py"
    proc = subprocess.Popen(
        [sys.executable, exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    request.addfinalizer(reaper(proc))
    for i in range(100):
        time.sleep(0.1)
        try:
            with urlopen("http://0.0.0.0:8888/alive") as f:
                data = f.read().decode()
            break
        except URLError as e:
            continue
    else:
        raise TimeoutError("Could not start server")
    if request.cls is not None:
        request.cls.url = url
    yield url


@pytest.yield_fixture
async def chrome_page(request, chrome: Chrome) -> AsyncGenerator[Page, Any]:
    page = await chrome.newPage()
    if request.cls is not None:
        request.cls.page = page
    yield page


@pytest.yield_fixture
def event_loop() -> Generator[uvloop.Loop, Any, None]:
    loop = uvloop.new_event_loop()
    yield loop
    loop.close()


@pytest.yield_fixture
async def chrome() -> AsyncGenerator[Chrome, Any]:
    chrome = await launch()
    yield chrome
    await chrome.close()
