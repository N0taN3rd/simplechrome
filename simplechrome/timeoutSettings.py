from ._typings import Number, OptionalNumber, SlotsT

__all__ = ["DEFAULT_TIMEOUT", "TimeoutSettings"]

DEFAULT_TIMEOUT: int = 30
DEFAULT_JS_TIMEOUT: int = 30000


class TimeoutSettings:
    __slots__: SlotsT = [
        "_defaultJSTimeout",
        "_defaultNavigationTimeout",
        "_defaultTimeout",
    ]

    def __init__(
        self,
        jsTimeout: OptionalNumber = None,
        navigationTimeout: OptionalNumber = None,
        defaultTimeout: OptionalNumber = None,
    ) -> None:
        self._defaultJSTimeout: OptionalNumber = jsTimeout
        self._defaultNavigationTimeout: OptionalNumber = navigationTimeout
        self._defaultTimeout: OptionalNumber = defaultTimeout

    def setDefaultJSTimeout(self, timeout: Number) -> None:
        self._defaultTimeout = timeout

    def setDefaultNavigationTimeout(self, timeout: Number) -> None:
        self._defaultNavigationTimeout = timeout

    def setDefaultTimeout(self, timeout: Number) -> None:
        self._defaultTimeout = timeout

    @property
    def js_timeout(self) -> Number:
        if self._defaultJSTimeout is not None:
            return self._defaultJSTimeout
        return DEFAULT_JS_TIMEOUT

    @property
    def navigationTimeout(self) -> Number:
        if self._defaultNavigationTimeout is not None:
            return self._defaultNavigationTimeout
        if self._defaultTimeout is not None:
            return self._defaultTimeout
        return DEFAULT_TIMEOUT

    @property
    def timeout(self) -> Number:
        if self._defaultTimeout is not None:
            return self._defaultTimeout
        return DEFAULT_TIMEOUT

    def __str__(self) -> str:
        return f"TimeoutSettings(js_timeout={self.js_timeout}, navigationTimeout={self.navigationTimeout}, timeout={self.timeout})"

    def __repr__(self) -> str:
        return self.__str__()
