import asyncio

import pytest
import uvloop

from simplechrome.launcher import launch


@pytest.yield_fixture()
def event_loop():
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def create_browser(request, event_loop):
    browser = await launch()

    def finalizer():
        event_loop.run_until_complete(browser.close())

    request.addfinalizer(finalizer)

    return browser

