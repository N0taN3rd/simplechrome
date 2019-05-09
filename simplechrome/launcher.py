"""Launcher module"""

import asyncio
import atexit
import logging
import os
import os.path
import re
import shutil
import signal
import sys
from asyncio import AbstractEventLoop
from pathlib import Path
from subprocess import DEVNULL, PIPE, Popen
from tempfile import mkdtemp
from typing import Any, Dict, List, Optional, Union

from appdirs import AppDirs

from ._typings import Loop, OptionalLoop
from .browser_fetcher import BrowserFetcher
from .chrome import Chrome
from .connection import Connection, createForWebSocket
from .errors import LauncherError
from .helper import Helper

__all__ = ["Launcher", "launch", "connect", "DEFAULT_ARGS"]

DEFAULT_CHROMIUM_REVISION: str = "656675"
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
    "--no-first-run",
    "--safebrowsing-disable-auto-update",
]

Options = Dict[str, Union[int, str, bool, List[str]]]


def args_include(args: List[str], needle: str) -> bool:
    for arg in args:
        if needle in arg:
            return True
    return False


def includes_starting_page(args: List[str]) -> bool:
    for arg in args:
        if not arg.startswith("-"):
            return True
    return False


def default_args(opts: Dict) -> List[str]:
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


class Launcher:
    __slots__ = [
        "projectRoot",
        "preferredRevision",
        "chrome_dead",
        "_temp_udata",
        "_chrome_process",
    ]

    def __init__(
        self,
        projectRoot: str = SIMPLECHROME_HOME,
        preferredRevision: str = DEFAULT_CHROMIUM_REVISION,
    ) -> None:
        self.projectRoot: str = projectRoot
        self.preferredRevision: str = preferredRevision
        self.chrome_dead: bool = False
        self._temp_udata: Optional[str] = None
        self._chrome_process: Optional[Popen] = None

    async def build_args(self, opts: Dict, loop: Loop) -> List[str]:
        executable = opts.get("executablePath", None)
        if executable is None:
            executable = await self.resolveExecutablePath(opts, loop=loop)
        ignoreDefaultArgs = opts.get("ignoreDefaultArgs", False)
        chromeArguments = [executable]
        if not ignoreDefaultArgs:
            chromeArguments.extend(default_args(opts))
        elif isinstance(ignoreDefaultArgs, list):
            chromeArguments.extend(
                [arg for arg in default_args(opts) if arg not in ignoreDefaultArgs]
            )
        else:
            chromeArguments.extend(opts.get("args", []))

        port = opts.get("port", "0")
        if not args_include(chromeArguments, "--remote-debugging-"):
            chromeArguments.append(f"--remote-debugging-port={port}")

        if not args_include(chromeArguments, "--user-data-dir"):
            self._temp_udata = mkdtemp()
            chromeArguments.append(f"--user-data-dir={self._temp_udata}")
            if "--password-store=basic" not in chromeArguments:
                chromeArguments.append("--password-store=basic")
            if "--use-mock-keychain" not in chromeArguments:
                chromeArguments.append("--use-mock-keychain")

        if not includes_starting_page(chromeArguments):
            chromeArguments.append("about:blank")

        return chromeArguments

    async def launch(
        self, options: Optional[Dict] = None, loop: OptionalLoop = None, **kwargs: Any
    ) -> Chrome:
        loop_ = Helper.ensure_loop(loop)
        opts = Helper.merge_dict(options, kwargs)
        chromeArguments = await self.build_args(opts, loop=loop_)
        browser_ws_re = re.compile("DevTools listening on (?P<websocket>ws:[^\n]+)$")
        chrome_process: Popen = Popen(chromeArguments, stdout=DEVNULL, stderr=PIPE)
        browser_ws = None
        while 1:
            line = chrome_process.stderr.readline()
            m = browser_ws_re.match(line.decode("utf-8"))
            if m:
                browser_ws = m.group("websocket")
                break
            if chrome_process.stderr.closed or chrome_process.returncode is not None:
                break
        chrome_process.stderr.close()
        if browser_ws is None or chrome_process.returncode is not None:
            raise LauncherError("Could not launch chrome")

        self._chrome_process = chrome_process
        atexit.register(self.__kill_chrome)

        if opts.get("handleSIGINT", True):
            loop_.add_signal_handler(signal.SIGINT, self.__kill_chrome)
        if opts.get("handleSIGTERM", True):
            loop_.add_signal_handler(signal.SIGTERM, self.__kill_chrome)
        if opts.get("handleSIGHUP", True):
            loop_.add_signal_handler(signal.SIGHUP, self.__kill_chrome)

        try:
            connection: Connection = await createForWebSocket(browser_ws, loop=loop_)
            targets = await connection.send("Target.getTargets", {})
            chrome = await Chrome.create(
                connection,
                [],
                opts.get("ignoreHTTPSErrors", False),
                opts.get("defaultViewPort"),
                chrome_process,
                self.__kill_chrome,
                targetInfo=targets.get("targetInfos", [None])[0],
                loop=loop_,
            )
            await chrome.waitForTarget(lambda t: t.type == "page")
            return chrome
        except Exception:
            self.__kill_chrome()
            raise

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
            opts = {}
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

    def __kill_chrome(self, *args: Any, **kwargs: Any) -> None:
        try:
            if self._temp_udata is not None and os.path.exists(self._temp_udata):
                shutil.rmtree(self._temp_udata)
        except Exception:
            pass
        if self.chrome_dead:
            return
        try:
            self._chrome_process.kill()
        except Exception:
            pass
        try:
            self._chrome_process.wait()
        except Exception:
            pass
        self.chrome_dead = True


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
