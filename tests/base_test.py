from typing import Any, Dict, Union, Optional

import pytest

from simplechrome.network_manager import Response

__all__ = ["BaseChromeTest"]


@pytest.mark.usefixtures("test_server_url", "chrome_page")
class BaseChromeTest(object):

    def full_url(self, page: str) -> str:
        return f"{self.url}{page}"

    async def goto_test(
        self,
        testpage: str,
        options: Dict[str, Union[str, int, bool]] = None,
        **kwargs: Any,
    ) -> Optional[Response]:
        return await self.page.goto(f"{self.url}{testpage}", options, **kwargs)

    async def goto_empty(
        self, options: Dict[str, Union[str, int, bool]] = None, **kwargs: Any
    ) -> Optional[Response]:
        return await self.page.goto(f"{self.url}empty.html", options, **kwargs)
