from collections import defaultdict
from typing import DefaultDict, List

from simplechrome.frame_manager import Frame
from simplechrome.page import Page

__all__ = ["attachFrame", "detachFrame", "dumpFrames", "navigateFrame"]


async def attachFrame(page: Page, frameId: str, url: str) -> None:
    func = """
        (frameId, url) => {
            const frame = document.createElement('iframe');
            frame.src = url;
            frame.id = frameId;
            document.body.appendChild(frame);
            return new Promise(x => frame.onload = x);
        }
    """
    await page.evaluate(func, frameId, url)


async def detachFrame(page: Page, frameId: str) -> None:
    func = """
        (frameId) => {
            const frame = document.getElementById(frameId);
            frame.remove();
        }
    """
    await page.evaluate(func, frameId)


async def navigateFrame(page: Page, frameId: str, url: str) -> None:
    func = """
        (frameId, url) => {
            const frame = document.getElementById(frameId);
            frame.src = url;
            return new Promise(x => frame.onload = x);
        }
    """
    await page.evaluate(func, frameId, url)


def dumpFrames(frame: Frame) -> DefaultDict[str, List[str]]:
    results = defaultdict(list)
    results["0"].append(frame.url)
    depth = 1
    frames = list(map(lambda x: dict(f=x, depth=depth), frame.childFrames))
    while frames:
        cf = frames.pop()
        f = cf.get("f")
        results[f"{cf.get('depth')}"].append(f.url)
        if f.childFrames:
            frames.extend(
                list(map(lambda x: dict(f=x, depth=depth + 1), f.childFrames))
            )
    return results
