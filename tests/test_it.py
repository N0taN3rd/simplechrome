import asyncio
import pytest
from simplechrome.launcher import launch


@pytest.fixture()
async def new_browser(request):
    print("create_browser")
    try:
        browser = await launch(headless=False)
    except Exception as E:
        print(E)
        raise E

    def finalizer():
        asyncio.get_event_loop().run_until_complete(browser.close())

    request.addfinalizer(finalizer)

    return browser


@pytest.mark.asyncio
async def test_one(new_browser):
    print(new_browser)
    assert True
