import asyncio

import pytest
import uvloop

from simplechrome.launcher import launch


@pytest.yield_fixture()
def eloop():
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()
