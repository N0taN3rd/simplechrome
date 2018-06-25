import logging
import os
import stat
import sys
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict
from urllib import request
from zipfile import ZipFile

DEFAULT_REVISION = "568432"
logger = logging.getLogger(__name__)

__all__ = ["BrowserFetcher", "BF"]


class BrowserFetcher(object):
    def __init__(self) -> None:
        self.downloads_folder: Path = Path.home() / ".simplechrome" / "local-chromium"
        self.default_download_host: str = "https://storage.googleapis.com"
        self.download_host: str = os.environ.get(
            "WRBUGS_DOWNLOAD_HOST", self.default_download_host
        )
        self.base_url: str = f"{self.download_host}/chromium-browser-snapshots"
        self.revision: str = DEFAULT_REVISION
        revision = self.revision
        self.downloadURLs: Dict[str, str] = {
            "linux": f"{self.base_url}/Linux_x64/{revision}/chrome-linux.zip",
            "mac": f"{self.base_url}/Mac/{revision}/chrome-mac.zip",
            "win32": f"{self.base_url}/Win/{revision}/chrome-win32.zip",
            "win64": f"{self.base_url}/Win_x64/{revision}/chrome-win32.zip",
        }
        self.chromiumExecutable = {
            "linux": self.downloads_folder / revision / "chrome-linux" / "chrome",
            "mac": (
                self.downloads_folder
                / revision
                / "chrome-mac"
                / "Chromium.app"
                / "Contents"
                / "MacOS"
                / "Chromium"
            ),
            "win32": self.downloads_folder / revision / "chrome-win32" / "chrome.exe",
            "win64": self.downloads_folder / revision / "chrome-win32" / "chrome.exe",
        }

    def update_download_revision(self, revision: str = DEFAULT_REVISION) -> None:
        if self.revision == revision or not isinstance(revision, str):
            return
        self.revision = revision
        self.downloadURLs = {
            "linux": f"{self.base_url}/Linux_x64/{revision}/chrome-linux.zip",
            "mac": f"{self.base_url}/Mac/{revision}/chrome-mac.zip",
            "win32": f"{self.base_url}/Win/{revision}/chrome-win32.zip",
            "win64": f"{self.base_url}/Win_x64/{revision}/chrome-win32.zip",
        }
        self.chromiumExecutable = {
            "linux": self.downloads_folder / revision / "chrome-linux" / "chrome",
            "mac": (
                self.downloads_folder
                / revision
                / "chrome-mac"
                / "Chromium.app"
                / "Contents"
                / "MacOS"
                / "Chromium"
            ),
            "win32": self.downloads_folder / revision / "chrome-win32" / "chrome.exe",
            "win64": self.downloads_folder / revision / "chrome-win32" / "chrome.exe",
        }

    def curret_platform(self) -> str:
        """Get current platform name by short string."""
        if sys.platform.startswith("linux"):
            return "linux"
        elif sys.platform.startswith("darwin"):
            return "mac"
        elif sys.platform.startswith("win"):
            if sys.maxsize > 2 ** 31 - 1:
                return "win64"
            return "win32"
        raise OSError("Unsupported platform: " + sys.platform)

    def get_url(self, cr: Optional[str] = None) -> str:
        """Get chromium download url."""
        if cr is not None:
            self.update_download_revision(cr)
        return self.downloadURLs[self.curret_platform()]

    def download_zip(self, url: str) -> bytes:
        """Download data from url."""
        logger.warning("start chromium download.\n" "Download may take a few minutes.")
        with request.urlopen(url) as f:
            data = f.read()
        logger.warning("chromium download done.")
        return data

    def extract_zip(self, data: bytes, path: Path) -> None:
        """Extract zipped data to path."""
        # On mac zipfile module cannot extract correctly, so use unzip instead.
        if self.curret_platform() == "mac":
            import subprocess
            import shutil

            zip_path = path / "chrome.zip"
            if not path.exists():
                path.mkdir(parents=True)
            with zip_path.open("wb") as f:
                f.write(data)
            if not shutil.which("unzip"):
                raise OSError(
                    "Failed to automatically extract chrome.zip."
                    f"Please unzip {zip_path} manually."
                )
            subprocess.run(["unzip", str(zip_path)], cwd=str(path))
            if self.chromium_excutable().exists() and zip_path.exists():
                zip_path.unlink()
        else:
            with ZipFile(BytesIO(data)) as zf:
                zf.extractall(str(path))
        exec_path = self.chromium_excutable()
        if not exec_path.exists():
            raise IOError("Failed to extract chromium.")
        exec_path.chmod(
            exec_path.stat().st_mode | stat.S_IXOTH | stat.S_IXGRP | stat.S_IXUSR
        )
        logger.warning(f"chromium extracted to: {path}")

    def download_chromium(self, cr: Optional[str] = None) -> None:
        """Downlaod and extract chrmoium."""
        if cr is not None:
            self.update_download_revision(cr)
        self.extract_zip(
            self.download_zip(self.get_url()), self.downloads_folder / self.revision
        )

    def chromium_excutable(self, cr: Optional[str] = None) -> Path:
        """Get path of the chromium executable."""
        if cr is not None:
            self.update_download_revision(cr)
        return self.chromiumExecutable[self.curret_platform()]

    def check_chromium(self, cr: Optional[str] = None) -> bool:
        """Check if chromium is placed at correct path."""
        if cr is not None:
            self.update_download_revision(cr)
        return self.chromium_excutable().exists()


BF = BrowserFetcher()
