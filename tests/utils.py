from asyncio import AbstractEventLoop, Future, get_event_loop as aio_get_event_loop
from collections import defaultdict
from typing import Any, Callable, DefaultDict, List, Optional, Tuple

from pyee2 import EventEmitter

from simplechrome.frame_manager import Frame
from simplechrome.helper import EEListener
from simplechrome.page import Page

__all__ = ["EEHandler", "TestUtil", "PageCrashState"]


def dummy_predicate(*args: Any, **kwargs: Any) -> bool:
    return True


class PageCrashState:
    __slots__ = ["_crashed"]

    def __init__(self, crashed: bool = False) -> None:
        self._crashed: bool = crashed

    @property
    def crashed(self) -> bool:
        return self._crashed

    def _page_crashed(self) -> None:
        self._crashed = True

    def reset(self) -> None:
        self._crashed = False


class EEHandler:
    __slots__ = ["listeners"]

    def __init__(self) -> None:
        self.listeners: List[EEListener] = []

    def addEventListener(
        self, emitter: EventEmitter, eventName: str, handler: Callable
    ) -> None:
        emitter.on(eventName, handler)
        self.listeners.append(
            dict(emitter=emitter, eventName=eventName, handler=handler)
        )

    def addEventListeners(
        self, emitter: EventEmitter, eventsHandlers: List[Tuple[str, Callable]]
    ) -> None:
        for eventName, handler in eventsHandlers:
            self.addEventListener(emitter, eventName, handler)

    def clean_up(self) -> None:
        for listener in self.listeners:
            emitter = listener["emitter"]
            eventName = listener["eventName"]
            handler = listener["handler"]
            emitter.remove_listener(eventName, handler)
        self.listeners.clear()


class TestUtil:
    @staticmethod
    async def attachFrame(page: Page, frameId: str, url: str) -> Frame:
        func = """async function attachFrame(frameId, url) {
          const frame = document.createElement('iframe');
          frame.src = url;
          frame.id = frameId;
          document.body.appendChild(frame);
          await new Promise(resolve => frame.onload = resolve);
          return frame;
        }"""
        handle = await page.evaluateHandle(func, frameId, url)
        return await handle.asElement().contentFrame()

    @staticmethod
    async def detachFrame(page: Page, frameId: str) -> None:
        func = """function detachFrame(frameId) {
            const frame = document.getElementById(frameId);
            frame.remove();
        }"""
        await page.evaluate(func, frameId)

    @staticmethod
    async def navigateFrame(page: Page, frameId: str, url: str) -> None:
        func = """function navigateFrame(frameId, url) {
          const frame = document.getElementById(frameId);
          frame.src = url;
          return new Promise(resolve => frame.onload = resolve);
        }"""
        await page.evaluate(func, frameId, url)

    @staticmethod
    def dumpFrames(frame: Frame) -> DefaultDict[str, List[str]]:
        results = defaultdict(list)
        results["0"].append(frame.url)
        depth = 1
        frames: List = list(map(lambda x: dict(f=x, depth=depth), frame.childFrames))
        while frames:
            cf = frames.pop()
            f = cf.get("f")
            results[f"{cf.get('depth')}"].append(f.url)
            if f.childFrames:
                frames.extend(
                    list(map(lambda x: dict(f=x, depth=depth + 1), f.childFrames))
                )
        return results

    @staticmethod
    async def waitEvent(
        emitter: EventEmitter,
        eventName: str,
        predicate: Optional[Callable[[Any], bool]] = None,
        loop: Optional[AbstractEventLoop] = None,
    ) -> Future:
        _loop = loop if loop is not None else aio_get_event_loop()
        _predicate = predicate if predicate is not None else dummy_predicate
        promise = _loop.create_future()

        def listener(event: Any = None) -> None:
            if _predicate(event) and not promise.done():
                emitter.remove_listener(eventName, listener)
                promise.set_result(event)

        emitter.on(eventName, listener)
        return promise
