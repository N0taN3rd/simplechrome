from typing import Optional, Union
import attr

__all__ = ["DEFAULT_TIMEOUT", "TimeoutSettings"]

DEFAULT_TIMEOUT: int = 30
DEFAULT_JS_TIMEOUT: int = 30000


@attr.dataclass(slots=True, str=False)
class TimeoutSettings(object):
    _defaultJSTimeout: Optional[Union[int, float]] = attr.ib(init=False, default=None)
    _defaultNavigationTimeout: Optional[Union[int, float]] = attr.ib(init=False, default=None)
    _defaultTimeout: Optional[Union[int, float]] = attr.ib(init=False, default=None)

    def setDefaultJSTimeout(self, timeout: Union[int, float]) -> None:
        self._defaultTimeout = timeout

    def setDefaultNavigationTimeout(self, timeout: Union[int, float]) -> None:
        self._defaultNavigationTimeout = timeout

    def setDefaultTimeout(self, timeout: Union[int, float]) -> None:
        self._defaultTimeout = timeout

    @property
    def js_timeout(self) -> Union[int, float]:
        if self._defaultJSTimeout is not None:
            return self._defaultJSTimeout
        return DEFAULT_JS_TIMEOUT

    @property
    def navigationTimeout(self) -> Union[int, float]:
        if self._defaultNavigationTimeout is not None:
            return self._defaultNavigationTimeout
        if self._defaultTimeout is not None:
            return self._defaultTimeout
        return DEFAULT_TIMEOUT

    @property
    def timeout(self) -> Union[int, float]:
        if self._defaultTimeout is not None:
            return self._defaultTimeout
        return DEFAULT_TIMEOUT

    def __str__(self) -> str:
        return f"TimeoutSettings(js_timeout={self.js_timeout}, navigationTimeout={self.navigationTimeout}, timeout={self.timeout})"
