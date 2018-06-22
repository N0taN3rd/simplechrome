from asyncio import TimeoutError
from typing import Tuple, Any

from async_timeout import timeout
from robber.bad_expectation import BadExpectation
from robber.explanation import Explanation
from robber.matchers.base import Base

from ..expected import expect

__all__ = ["ResolvesWithin", "AsyncMatcherWrapper"]


class AsyncBase(Base):
    no_wrap = True

    async def match(self):
        if await self.matches() is not self.is_negative:
            return True

        message = self.message or self.explanation.message
        raise BadExpectation(message)

    async def do_match(self):
        test_pass, results = await self.matches_with_results()
        if test_pass is not self.is_negative:
            return results

        message = self.message or self.explanation.message
        raise BadExpectation(message)


class ResolvesWithin(AsyncBase):
    async def matches_with_results(self) -> Tuple[bool, Any]:
        results = await self.matches()
        return results, getattr(self, "results")

    async def matches(self) -> bool:
        try:
            async with timeout(self.expected) as to:
                if callable(self.actual):
                    self.results = await self.actual()
                else:
                    self.results = await self.actual

                return not to.expired
        except TimeoutError:
            return False

    @property
    def explanation(self):
        return Explanation(
            self.actual, self.is_negative, f"resolve within {self.expected} seconds"
        )


class AsyncMatcherWrapper(AsyncBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._klass = None
        self._other = None
        self._negative_fact = None
        self._args = None
        self._kwargs = None
        self._message = None

    def setup_wrap(self, klass, other, negative_fact, *args, **kwargs):
        self._klass = klass
        self._other = other
        self._negative_fact = negative_fact
        self._args = args
        self._kwargs = kwargs

    def fail_with(self, message):
        self._message = message
        return self

    async def matches(self) -> bool:
        if callable(self.obj):
            obj = await self.obj()
        else:
            obj = await self.obj
        wklass = self._klass(obj, self._other, self._negative_fact, *self._args, **self._kwargs)
        return wklass.fail_with(self.message).match()



expect.register_async("resolves_within", ResolvesWithin)
