"""Launcher module"""

import asyncio
import atexit
import logging
import os
import os.path
import signal
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin

from aiohttp import ClientSession, ClientConnectorError

from .browser_fetcher import BF
from .chrome import Chrome
from .connection import Connection
from .errors import LauncherError
from .util import merge_dict

__all__ = ["Launcher", "launch", "connect", "DEFAULT_ARGS"]

logger = logging.getLogger(__name__)

# https://peter.sh/experiments/chromium-command-line-switches/
# https://cs.chromium.org/chromium/src/chrome/common/chrome_switches.cc
DEFAULT_ARGS = [
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-client-side-phishing-detection",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-hang-monitor",
    "--disable-prompt-on-repost",
    "--disable-sync",
    "--disable-translate",
    "--metrics-recording-only",
    "--no-first-run",
    "--safebrowsing-disable-auto-update",
    "--password-store=basic",
    "--disable-features=site-per-process",
    "--use-mock-keychain",
    "--mute-audio",
    "--disable-domain-reliability",  # no Domain Reliability Monitoring
    "--disable-renderer-backgrounding",
    "--disable-infobars",
    "--disable-translate",
    "--autoplay-policy=no-user-gesture-required"
]

DOT_DIR = Path.home() / ".simplechrome"
TEMP_PROFILE = DOT_DIR / "simplechrome_temp_profile"

Options = Dict[str, Union[int, str, bool, List[str]]]


class Launcher(object):
    def __init__(self, options: Optional[Options] = None, **kwargs: Any) -> None:
        self.options: Options = merge_dict(options, kwargs)
        self.chrome_dead: bool = True
        self.headless: bool = self.options.get("headless", False)
        self._tmp_user_data_dir: Optional[TemporaryDirectory] = None
        self.args: List[str] = []
        self.port: int = 9222
        self.exec: str = ""
        self._args_setup()
        self.chrome: Optional[Chrome] = None
        self._connection: Optional[Connection] = None
        self.proc: Optional[subprocess.Popen] = None
        self.cmd: List[str] = [self.exec] + self.args

    def _check_supplied_userdd(self) -> bool:
        args = self.options.get("args")
        if not isinstance(args, list):
            return False
        for arg in args:
            if arg.startswith("--user-data-dir"):
                return True
        return False

    def _check_starting_page(self) -> bool:
        args = self.options.get("args")
        if not isinstance(args, list):
            return False
        for arg in args:
            if not arg.startswith("-"):
                return True
        return False

    def _args_setup(self) -> None:
        if "port" in self.options:
            self.port = self.options.get("port")  # type: ignore
        if "url" not in self.options:
            self.url = f"http://localhost:{self.port}"
        else:
            self.url = self.options.get("url")  # type: ignore
        if "executablePath" in self.options:
            self.exec = self.options["executablePath"]  # type: ignore
        else:
            cr = self.options.get("chromium_revision", None)  # type: ignore
            if not BF.check_chromium(cr):
                BF.download_chromium()
            self.exec = str(BF.chromium_excutable())
        if isinstance(self.options.get("args"), list):
            self.args.extend(self.options["args"])  # type: ignore

        if not self.options.get("ignoreDefaultArgs", False):
            self.args.extend(DEFAULT_ARGS)
            self.args.append(f"--remote-debugging-port={self.port}")

        if self.options.get("appMode", False):
            self.options["headless"] = False
        if "headless" not in self.options or self.options.get("headless"):
            self.args.extend(["--headless", "--disable-gpu"])

        if not self._check_supplied_userdd():
            if "userDataDir" not in self.options:
                self._tmp_user_data_dir = TemporaryDirectory()
            self.args.append(
                "--user-data-dir={}".format(
                    self.options.get("userDataDir", self._tmp_user_data_dir.name)
                )
            )
        if not self._check_starting_page():
            self.args.append("about:blank")

    async def _get_ws_endpoint(self) -> str:
        async with ClientSession() as session:
            for i in range(100):
                await asyncio.sleep(0.1)
                try:
                    res = await session.get(urljoin(self.url, "json"))
                    data = await res.json()
                    break
                except ClientConnectorError as e:
                    continue
            else:
                # cannot connet to browser for 10 seconds
                raise LauncherError(f"Failed to connect to browser port: {self.url}")
            for d in data:
                if d["type"] == "page":
                    return d["webSocketDebuggerUrl"]
        raise LauncherError("Could not find a page to connect to")

    async def launch(self) -> Chrome:
        self.chrome_dead = False
        self.proc = subprocess.Popen(
            self.cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        myself = self

        def _close_process(*args: Any, **kwargs: Any) -> None:
            if not myself.chrome_dead:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(myself.kill_chrome())
                else:
                    loop.run_until_complete(myself.kill_chrome())

        atexit.register(_close_process)
        if self.options.get("handleSIGINT", True):
            signal.signal(signal.SIGINT, _close_process)
        if self.options.get("handleSIGTERM", True):
            signal.signal(signal.SIGTERM, _close_process)
        if not sys.platform.startswith("win"):
            # SIGHUP is not defined on windows
            if self.options.get("handleSIGHUP", True):
                signal.signal(signal.SIGHUP, _close_process)

        wsurl = await self._get_ws_endpoint()
        logger.info(f"Browser listening on: {wsurl}")
        con = await Connection.createForWebSocket(wsurl)
        self._connection = con
        self.chrome = await Chrome.create(
            con,
            [],
            self.options.get("ignoreHTTPSErrors", False),
            self.options.get("setDefaultViewport", False),
            self.proc,
            self.kill_chrome,
        )
        return self.chrome

    async def kill_chrome(self) -> None:
        """Terminate chromium process."""
        if (
            self.chrome is not None
            and not self.chrome_dead
            and self._connection.connected
        ):
            try:
                await self.chrome._connection.send("Browser.close")
            except Exception:
                # ignore errors on browser termination process
                pass
        if self._tmp_user_data_dir and os.path.exists(self._tmp_user_data_dir.name):
            # Force kill chrome only when using temporary userDataDir
            self.wait_for_chrome_death()
            self._cleanup_tmp_user_data_dir()

    def wait_for_chrome_death(self) -> None:
        """Terminate chrome."""
        if self.proc is not None and self.proc.poll() is None and not self.chrome_dead:
            self.chrome_dead = True
            self.proc.terminate()
            self.proc.wait()

    def _cleanup_tmp_user_data_dir(self) -> None:
        for retry in range(100):
            if self._tmp_user_data_dir and os.path.exists(self._tmp_user_data_dir.name):
                self._tmp_user_data_dir.cleanup()
                # shutil.rmtree(self._tmp_user_data_dir, ignore_errors=True)
            else:
                break
        else:
            raise IOError("Unable to remove Temporary User Data")


async def launch(options: dict = None, **kwargs: Any) -> Chrome:
    return await Launcher(options, **kwargs).launch()


async def connect(options: dict = None, **kwargs: Any) -> Chrome:
    options = merge_dict(options, kwargs)
    browserWSEndpoint = options.get("browserWSEndpoint")
    if not browserWSEndpoint:
        raise LauncherError("Need `browserWSEndpoint` option.")
    connectionDelay = options.get("slowMo", 0)
    connection = await Connection.createForWebSocket(browserWSEndpoint, connectionDelay)
    return await Chrome.create(
        connection,
        contextIds=[],
        ignoreHTTPSErrors=options.get("ignoreHTTPSErrors", False),
        appMode=options.get("appMode", False),
        process=None,
        closeCallback=lambda: connection.send("Browser.close"),
    )
