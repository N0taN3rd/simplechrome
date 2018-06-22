import asyncio
import uvloop
import pytest

from simplechrome.launcher import launch

@pytest.yield_fixture()
def ___event_loop():
    loop = uvloop.new_event_loop()
    yield loop
    loop.close()


class Context(object):
    pass
