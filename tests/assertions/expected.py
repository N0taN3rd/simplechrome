import asyncio
import inspect

from syncer import sync
from robber import expect as Expect

__all__ = ["expect"]


def make_async_wrapper(klass, is_negative):
    async def wrapper(self, other=None, *args, **kwargs):
        if callable(self.obj):
            obj = await self.obj()
        else:
            obj = await self.obj
        if self.not_to_flag:
            negative_fact = not is_negative
        else:
            negative_fact = is_negative
        instance = klass(obj, other, negative_fact, *args, **kwargs)
        return (
            instance
            .fail_with(self.message)
            .match()
        )

    return wrapper


class expect(Expect):
    monkey_patched = False

    def __setup_chaining(self):
        super().__setup_chaining()
        self.that = self
        self.Is = self
        self.it = self


    @staticmethod
    def expect_sync(obj):
        return expect(sync(obj))

    @classmethod
    def register_async(cls, name, klass, is_negative=False):
        cls.matchers[name] = klass

        def method(self, other=None, *args, **kwargs):
            if self.not_to_flag:
                negative_fact = not is_negative
            else:
                negative_fact = is_negative
            return (
                klass(self.obj, other, negative_fact, *args, **kwargs)
                .fail_with(self.message)
                .do_match()
            )

        setattr(cls, name, method)

    @classmethod
    def make_existing_async(cls):
        if cls.monkey_patched:
            return
        cls.monkey_patched = True
        for name, m in list(cls.matchers.items()):
            if hasattr(m, "no_wrap") or name.startswith("__"):
                continue
            nn = f"{name}_async"
            closure_vars = inspect.getclosurevars(getattr(cls, name))
            is_negative = closure_vars.nonlocals.get("is_negative")
            klass = closure_vars.nonlocals.get("klass")
            setattr(cls, nn, make_async_wrapper(klass, is_negative))

    @property
    def eventually(self):
        loop = asyncio.get_event_loop()
        future = asyncio.ensure_future(self.obj, loop=loop)
        loop.run_until_complete(future)
        self.obj = future.result()
        return self
