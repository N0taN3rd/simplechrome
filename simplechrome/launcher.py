"""Launcher module"""

import asyncio
import atexit
import logging
import os
import os.path
import shutil
import signal
import subprocess
import sys
from asyncio import AbstractEventLoop, sleep as aio_sleep
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin

import attr
from aiohttp import ClientConnectorError
from appdirs import AppDirs

from .browser_fetcher import BrowserFetcher
from .chrome import Chrome
from .connection import Connection, createForWebSocket
from .errors import LauncherError
from .helper import Helper

__all__ = ["Launcher", "launch", "connect", "DEFAULT_ARGS"]

DEFAULT_CHROMIUM_REVISION: str = "654752"
CHROMIUM_REVISION: str = os.getenv(
    "SIMPLECHROME_CHROMIUM_REVISION", DEFAULT_CHROMIUM_REVISION
)
SIMPLECHROME_HOME: str = os.getenv(
    "SIMPLECHROME_HOME", AppDirs("simplechrome").user_data_dir
)

logger = logging.getLogger(__name__)

# https://peter.sh/experiments/chromium-command-line-switches/
# https://cs.chromium.org/chromium/src/chrome/common/chrome_switches.cc
DEFAULT_ARGS = [
    "--autoplay-policy=no-user-gesture-required",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-backing-store-limit",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-default-apps",
    "--disable-domain-reliability",
    "--disable-extensions",
    "--disable-features=site-per-process,TranslateUI,LazyFrameLoading,BlinkGenPropertyTrees",
    "--disable-hang-monitor",
    "--disable-infobars",
    "--disable-ipc-flooding-protection",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-renderer-backgrounding",
    "--disable-sync",
    "--enable-features=NetworkService,NetworkServiceInProcess",
    "--force-color-profile=srgb",
    "--metrics-recording-only",
    "--mute-audio",
    "--no-first-run",
    "--safebrowsing-disable-auto-update",
]

Options = Dict[str, Union[int, str, bool, List[str]]]


async def ensureInitialPage(browser: Chrome) -> None:
    for target in browser.targets():
        if target.type == "page":
            return None
    initialPagePromise = asyncio.get_event_loop().create_future()

    def onTargetCreated(newTarget: Any) -> None:
        if newTarget.type == "page":
            initialPagePromise.set_result(True)

    listeners = [Helper.addEventListener(browser, "targetcreated", onTargetCreated)]
    await initialPagePromise
    Helper.removeEventListeners(listeners)


async def get_ws_endpoint(url: str, loop: Optional[AbstractEventLoop] = None) -> str:
    loop_ = Helper.ensure_loop(loop)
    data: Optional[List[Dict[str, str]]] = None
    async with Helper.make_aiohttp_session(loop=loop_) as session:
        session_get = session.get
        for _ in range(100):
            try:
                async with session_get(urljoin(url, "json")) as res:
                    data = await res.json()
                break
            except ClientConnectorError:
                await aio_sleep(0.1, loop=loop_)
                continue
        else:
            # cannot connet to browser for 10 seconds
            raise LauncherError(f"Failed to connect to browser port: {url}")
    if data is not None:
        for d in data:
            if d["type"] == "page":
                return d["webSocketDebuggerUrl"]
    raise LauncherError("Could not find a page to connect to")


async def find_target(url: str, loop: Optional[AbstractEventLoop] = None) -> Dict:
    loop_ = Helper.ensure_loop(loop)
    data: Optional[List[Dict[str, str]]] = None
    async with Helper.make_aiohttp_session(loop=loop_) as session:
        session_get = session.get
        for _ in range(150):
            try:
                async with session_get(urljoin(url, "json")) as res:
                    data = await res.json()
                break
            except ClientConnectorError:
                await aio_sleep(0.1, loop=loop_)
                continue
        else:
            # cannot connet to browser for 10 seconds
            raise LauncherError(f"Failed to connect to browser port: {url}")
    if data is not None:
        for d in data:
            if d["type"] == "page":
                return d
    raise LauncherError("Could not find a page to connect to")


@attr.dataclass(slots=True)
class Launcher:
    projectRoot: str = attr.ib(default=SIMPLECHROME_HOME)
    preferredRevision: str = attr.ib(default=CHROMIUM_REVISION)
    chrome_dead: bool = attr.ib(default=False, init=False)

    def default_args(self, opts: Dict) -> List[str]:
        chromeArgs: List[str] = list(DEFAULT_ARGS)
        udata = opts.get("userDataDir", None)
        devtools = opts.get("devtools", False)
        headless = opts.get("headless", not devtools)
        if udata:
            chromeArgs.append(f"--user-data-dir={udata}")
        if devtools:
            chromeArgs.append("--auto-open-devtools-for-tabs")
        if headless:
            chromeArgs.append("--headless")
            chromeArgs.append("--hide-scrollbars")
            if sys.platform.startswith("win"):
                chromeArgs.append("--disable-gpu")
        supplied_chrome_args = opts.get("args", [])
        chromeArgs.extend(supplied_chrome_args)
        return chromeArgs

    async def launch(
        self,
        options: Optional[Dict] = None,
        loop: Optional[AbstractEventLoop] = None,
        **kwargs: Any,
    ) -> Chrome:
        loop_ = Helper.ensure_loop(loop)
        opts = Helper.merge_dict(options, kwargs)
        ignoreDefaultArgs = opts.get("ignoreDefaultArgs", False)
        chromeArguments = []
        if not ignoreDefaultArgs:
            chromeArguments.extend(self.default_args(opts))
        elif isinstance(ignoreDefaultArgs, list):
            chromeArguments.extend(
                [arg for arg in self.default_args(opts) if arg not in ignoreDefaultArgs]
            )
        else:
            chromeArguments.extend(opts.get("args", []))

        executable = opts.get("executablePath", None)
        if executable is None:
            executable = await self.resolveExecutablePath(opts, loop=loop_)

        port = opts.get("port", "9222")
        if not self._args_include(chromeArguments, "--remote-debugging-"):
            chromeArguments.append(f"--remote-debugging-port={port}")

        temp_udata = None
        if not self._args_include(chromeArguments, "--user-data-dir"):
            temp_udata = mkdtemp()
            chromeArguments.append(f"--user-data-dir={temp_udata}")
            if "--password-store=basic" not in chromeArguments:
                chromeArguments.append("--password-store=basic")
            if "--use-mock-keychain" not in chromeArguments:
                chromeArguments.append("--use-mock-keychain")

        if not self._includes_starting_page(chromeArguments):
            chromeArguments.append("about:blank")

        chrome_process: subprocess.Popen = subprocess.Popen(
            [executable] + chromeArguments,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def kill_chrome(*args: Any, **kwargs: Any) -> None:
            try:
                if temp_udata is not None and os.path.exists(temp_udata):
                    shutil.rmtree(temp_udata)
            except Exception:
                pass
            if self.chrome_dead:
                return
            try:
                chrome_process.kill()
            except Exception:
                pass
            try:
                chrome_process.wait()
            except Exception:
                pass
            self.chrome_dead = True

        atexit.register(kill_chrome)

        if opts.get("handleSIGINT", True):
            loop_.add_signal_handler(signal.SIGINT, kill_chrome)
        if opts.get("handleSIGTERM", True):
            loop_.add_signal_handler(signal.SIGTERM, kill_chrome)
        if opts.get("handleSIGHUP", True):
            loop_.add_signal_handler(signal.SIGHUP, kill_chrome)

        await aio_sleep(1, loop=loop_)

        target = await find_target(f"http://localhost:{port}", loop=loop_)
        connection: Connection = await createForWebSocket(
            target["webSocketDebuggerUrl"],
            loop=loop_
        )
        targetInfo = await connection.send(
            "Target.getTargetInfo", dict(targetId=target["id"])
        )
        chrome = await Chrome.create(
            connection,
            [],
            opts.get("ignoreHTTPSErrors", False),
            opts.get("defaultViewPort"),
            chrome_process,
            kill_chrome,
            targetInfo=targetInfo["targetInfo"],
            loop=loop_,
        )
        await ensureInitialPage(chrome)
        return chrome

    async def resolveExecutablePath(
        self, opts: Optional[Dict] = None, loop: Optional[AbstractEventLoop] = None
    ) -> str:
        env_exe = os.getenv("SIMPLECHROME_EXECUTABLE_PATH", None)
        if env_exe is not None:
            if not Path(env_exe).exists():
                raise LauncherError(
                    f"Tried to use SIMPLECHROME_EXECUTABLE_PATH env variable to launch browser but did not find any executable at: {env_exe}"
                )
            return env_exe
        bf = BrowserFetcher(self.projectRoot)
        if opts is None:
            opts = dict()
        revision: Optional[str] = opts.get("chromium_revision")
        if revision is None:
            revision = self.preferredRevision
        if revision is None:
            revision = CHROMIUM_REVISION
        exe_path = bf.revision_exe_path(revision)
        if not exe_path.exists():
            ri = await bf.download(revision, loop=loop)
            return str(ri.executablePath)
        return str(exe_path)

    def _args_include(self, args: List[str], needle: str) -> bool:
        for arg in args:
            if needle in arg:
                return True
        return False

    def _includes_starting_page(self, args: List[str]) -> bool:
        for arg in args:
            if not arg.startswith("-"):
                return True
        return False


async def launch(
    options: Optional[Dict] = None,
    loop: Optional[AbstractEventLoop] = None,
    **kwargs: Any,
) -> Chrome:
    launcher = Launcher()
    return await launcher.launch(options, loop=loop, **kwargs)


async def connect(
    options: Optional[Dict] = None,
    loop: Optional[AbstractEventLoop] = None,
    **kwargs: Any,
) -> Chrome:
    if loop is None:
        loop = asyncio.get_event_loop()
    options = Helper.merge_dict(options, kwargs)
    browserWSEndpoint = options.get("browserWSEndpoint")
    if not browserWSEndpoint:
        raise LauncherError("Need `browserWSEndpoint` option.")
    con = await createForWebSocket(browserWSEndpoint, loop=loop)
    targetInfo = await con.send("Target.getTargetInfo")
    return await Chrome.create(
        con,
        contextIds=[],
        ignoreHTTPSErrors=options.get("ignoreHTTPSErrors", False),
        defaultViewport=options.get("defaultViewPort"),
        process=None,
        targetInfo=targetInfo["targetInfo"],
        loop=loop,
    )
