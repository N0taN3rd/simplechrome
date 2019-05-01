import asyncio
import logging
import os
import shutil
import sys
from asyncio import AbstractEventLoop
from pathlib import Path
from typing import Any, Dict, List, Optional
from zipfile import ZipFile

import attr
from tqdm import tqdm

from .errors import BrowserFetcherError
from .helper import Helper

__all__ = ["BrowserFetcher", "RevisionInfo"]

logger = logging.getLogger(__name__)

DEFAULT_DOWNLOAD_HOST: str = "https://storage.googleapis.com"
DOWNLOAD_HOST: str = os.getenv("CHROMIUM_DOWNLOAD_HOST", DEFAULT_DOWNLOAD_HOST)
DOWNLOAD_URLS: Dict[str, str] = dict(
    linux="%s/chromium-browser-snapshots/Linux_x64/%s/%s.zip",
    mac="%s/chromium-browser-snapshots/Mac/%s/%s.zip",
    win32="%s/chromium-browser-snapshots/Win/%s/%s.zip",
    win64="%s/chromium-browser-snapshots/Win_x64/%s/%s.zip",
)
SUPPORTED_PLATFORMS = ["mac", "linux", "win32", "win64"]

NO_PROGRESS_BAR: bool = False
if os.getenv("SIMPLECHROME_NO_PROGRESS_BAR", "").lower() in ("1", "true"):
    NO_PROGRESS_BAR = True


def platform_short_name(pltfrm: Optional[str] = None) -> str:
    """Get the current platform short name"""
    platform: str = pltfrm or sys.platform
    if platform.startswith("linux"):
        return "linux"
    elif platform.startswith("darwin"):
        return "mac"
    elif (
        platform.startswith("win")
        or platform.startswith("msys")
        or platform.startswith("cyg")
    ):
        if sys.maxsize > 2 ** 32:
            return "win64"
        return "win32"
    raise BrowserFetcherError(f"Unsupported platform: {platform}")


def archive_name(platform: str, revision: str) -> str:
    if platform == "linux":
        return "chrome-linux"
    elif platform == "mac":
        return "chrome-mac"
    elif platform in ("win64", "win32"):
        if int(revision) > 591_479:
            return "chrome-win"
        return "chrome-win32"
    raise BrowserFetcherError(f"Unsupported platform: {platform}")


def download_url(platform: str, host: str, revision: str) -> str:
    return DOWNLOAD_URLS[platform] % (host, revision, archive_name(platform, revision))


@attr.dataclass(slots=True)
class RevisionInfo:
    revision: str = attr.ib()
    url: str = attr.ib()
    executablePath: Path = attr.ib()
    folderPath: Path = attr.ib()
    local: bool = attr.ib()


class BrowserFetcher:
    __slots__ = ["_downloads_folder", "_download_host", "_platform"]

    def __init__(
        self, rootDir: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> None:
        opts = Helper.merge_dict(options, kwargs)
        dlfp = opts.get("path", Path(rootDir) / "local-chromium")
        self._downloads_folder: Path = dlfp if isinstance(dlfp, Path) else Path(dlfp)
        self._download_host: str = opts.get("host", DEFAULT_DOWNLOAD_HOST)
        self._platform: str = platform_short_name(opts.get("platform"))

    @property
    def download_host(self) -> str:
        return self._download_host

    @property
    def downloads_folder(self) -> Path:
        return self._downloads_folder

    @property
    def platform(self) -> str:
        return self.platform

    async def can_download(
        self, revision: str, loop: Optional[AbstractEventLoop] = None
    ) -> bool:
        url: str = download_url(self._platform, self._download_host, revision)
        try:
            async with Helper.make_aiohttp_session(loop=loop) as sesh:
                async with sesh.head(url=url, allow_redirects=True) as res:
                    return res.status == 200
        except Exception:
            return False

    async def download(
        self, revision: str, loop: Optional[AbstractEventLoop] = None
    ) -> RevisionInfo:
        folder_path: Path = self._getFolderPath(revision)
        if folder_path.exists():
            return self.revision_info(revision)
        url: str = download_url(self._platform, self._download_host, revision)
        zip_path: Path = self._downloads_folder / f"download-{self._platform}-{revision}.zip"
        folder_path.mkdir(parents=True)
        try:
            await download_revision(url, revision, zip_path, loop=loop)
            with ZipFile(zip_path) as zf:
                zf.extractall(path=folder_path)
        finally:
            if zip_path.exists():
                zip_path.unlink()
        revision_info = self.revision_info(revision)
        if not revision_info.local:
            raise BrowserFetcherError(f"Failed to extract Chromium r{revision}")
        revision_info.executablePath.chmod(0o755)
        for subexe in ["nacl_helper", "chrome_sandbox", "nacl_helper_bootstrap"]:
            sexe = revision_info.executablePath.parent / subexe
            if sexe.exists():
                sexe.chmod(0o755)
        return revision_info

    def revision_exe_path(self, revision: str) -> Path:
        folderPath: Path = self._getFolderPath(revision)
        return self._revision_exe(folderPath, revision)

    def revision_info(self, revision: str) -> RevisionInfo:
        folderPath: Path = self._getFolderPath(revision)
        executablePath = self._revision_exe(folderPath, revision)
        return RevisionInfo(
            revision=revision,
            executablePath=executablePath,
            folderPath=folderPath,
            local=folderPath.exists(),
            url=download_url(self._platform, self._download_host, revision),
        )

    def local_revisions(self) -> List[RevisionInfo]:
        revisions: List[RevisionInfo] = []
        if not self._downloads_folder.exists():
            return revisions
        for revision in self._downloads_folder.iterdir():
            if revision.is_dir():
                rname_split = revision.name.split("-")
                if len(rname_split) == 2:
                    plat, r = rname_split
                    if plat in SUPPORTED_PLATFORMS and plat == self._platform:
                        revisions.append(self.revision_info(r))
        return revisions

    def remove(self, revision: str) -> None:
        folder_path = self._getFolderPath(revision)
        if folder_path.exists():
            shutil.rmtree(str(folder_path), ignore_errors=True)
        else:
            raise BrowserFetcherError(
                f"Failed to remove: revision {revision} is not downloaded"
            )

    def _getFolderPath(self, revision: str) -> Path:
        return self._downloads_folder / f"{self._platform}-{revision}"

    def _revision_exe(self, folder_path: Path, revision: str) -> Path:
        if self._platform == "mac":
            executablePath = (
                folder_path
                / archive_name(self._platform, revision)
                / "Chromium.app"
                / "Contents"
                / "MacOS"
                / "Chromium"
            )
        elif self._platform == "linux":
            executablePath = (
                folder_path / archive_name(self._platform, revision) / "chrome"
            )

        elif self._platform == "win32" or self._platform == "win64":
            executablePath = (
                folder_path / archive_name(self._platform, revision) / "chrome.exe"
            )
        else:
            raise BrowserFetcherError(f"Unsupported platform: {self._platform}")
        return executablePath

    def __str__(self) -> str:
        return f"BrowserFetcher(platform={self._platform}, downloads_folder={self._downloads_folder}, download_host={self._download_host})"

    def __repr__(self) -> str:
        return self.__str__()


def get_progress_bar(revision: str, total_length: int) -> Optional[tqdm]:
    if NO_PROGRESS_BAR:
        return None
    return tqdm(
        desc=f"Downloading Chromium r{revision}",
        total=total_length,
        unit="bytes",
        unit_scale=True,
        file=None,
    )


async def download_revision(
    url: str, revision: str, zip_path: Path, loop: Optional[AbstractEventLoop] = None
) -> None:
    if loop is None:
        loop = asyncio.get_event_loop()
    chunk_size: int = 10240
    async with Helper.make_aiohttp_session(loop=loop) as sesh:
        async with sesh.get(url=url) as res:
            try:
                total_length = int(res.headers["content-length"])
            except (KeyError, ValueError, AttributeError):
                total_length = 0

            progress = get_progress_bar(revision, total_length)
            try:
                with zip_path.open("wb") as fd:
                    while True:
                        chunk = await res.content.read(chunk_size)
                        if not chunk:
                            break
                        if progress:
                            progress.update(len(chunk))
                        fd.write(chunk)
            finally:
                if progress:
                    progress.close()
