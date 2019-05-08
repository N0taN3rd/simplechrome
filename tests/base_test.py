import pytest
from typing import Any, Awaitable, Dict, Union, Optional

from simplechrome.request_response import Response
from simplechrome.page import Page
from .utils import PageCrashState

__all__ = ["BaseChromeTest"]


def handle_page_crash(e) -> None:
    pytest.skip(str(e))


class BaseChromeTest:
    page: Page = None
    base_url: str = ""
    static_url: str = ""
    page_crash_state: PageCrashState = None

    def setup_method(self, method) -> None:
        if self.page_crash_state.crashed:
            pytest.skip("Page Crashed")

    def full_test_url(self, page: str) -> str:
        full_url = f"{self.static_url}{page}"
        return full_url

    def tserver_endpoint_url(self, path: str) -> str:
        endpoint_url = f"{self.base_url}{path}"
        return endpoint_url

    def goto_test(
        self,
        testpage: str,
        options: Dict[str, Union[str, int, bool]] = None,
        reset: bool = False,
        **kwargs: Any,
    ) -> Awaitable[Optional[Response]]:
        if reset:
            return self.reset_and_goto_test(testpage, options, **kwargs)
        return self._goto(self.full_test_url(testpage), options, **kwargs)

    def goto_empty(
        self,
        options: Dict[str, Union[str, int, bool]] = None,
        reset: bool = False,
        **kwargs: Any,
    ) -> Awaitable[Optional[Response]]:
        if reset:
            return self.reset_and_goto_empty(options, **kwargs)
        return self._goto(self.full_test_url("empty.html"), options, **kwargs)

    def goto_never_loads(
        self,
        options: Dict[str, Union[str, int, bool]] = None,
        reset: bool = False,
        **kwargs: Any,
    ) -> Awaitable[Optional[Response]]:
        if reset:
            return self.reset_and_goto_never_loads(options, **kwargs)
        return self._goto(self.tserver_endpoint_url("never-loads"), options, **kwargs)

    def goto_about_blank(self) -> Awaitable[Optional[Response]]:
        return self.page.goto("about:blank", waitUntil="documentloaded")

    async def reset_and_goto_test(
        self,
        testpage: str,
        options: Dict[str, Union[str, int, bool]] = None,
        **kwargs: Any,
    ) -> Optional[Response]:
        await self.goto_about_blank()
        result = await self._goto(self.full_test_url(testpage), options, **kwargs)
        return result

    async def reset_and_goto_empty(
        self, options: Dict[str, Union[str, int, bool]] = None, **kwargs: Any
    ) -> Optional[Response]:
        await self.goto_about_blank()
        result = await self._goto(self.full_test_url("empty.html"), options, **kwargs)
        return result

    async def reset_and_goto_never_loads(
        self, options: Dict[str, Union[str, int, bool]] = None, **kwargs: Any
    ) -> Optional[Response]:
        await self.goto_about_blank()
        result = await self._goto(
            self.tserver_endpoint_url("never-loads"), options, **kwargs
        )
        return result

    def _goto(
        self, url: str, options: Dict[str, Union[str, int, bool]] = None, **kwargs: Any
    ) -> Awaitable[Optional[Response]]:
        return self.page.goto(url, options, **kwargs)
