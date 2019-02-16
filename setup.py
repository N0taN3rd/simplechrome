import re
from os import path
from pathlib import Path

from setuptools import setup, find_packages

BASE_DIR = Path(path.dirname(path.abspath(__file__)))


def find_version():
    version_file = BASE_DIR.joinpath("simplechrome", "__init__.py").read_text()
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", version_file, re.M)
    if version_match:
        return version_match.group(1)

    raise RuntimeError("Unable to find version string.")


def get_requirements():
    reqs = []
    with BASE_DIR.joinpath("requirements.txt").open("r") as rin:
        for line in rin:
            if "git#egg=cripy" in line:
                reqs.append("cripy")
            else:
                reqs.append(line.rstrip())
    return reqs


test_requirements = ["pytest", "pytest-asyncio", "psutil", "grappa", "sanic", "uvloop"]

setup(
    name="simplechrome",
    version=find_version(),
    description=(
        "Headless chrome/chromium automation library"
        "(unofficial fork of pypuppeteer that stays more up to date with puppeteer)"
    ),
    author="Webrecorder",
    author_email="Webrecorder.Webrecorder@Webrecorder.com",
    packages=find_packages(exclude=["tests"]),
    include_package_data=True,
    install_requires=get_requirements(),
    dependency_links=[
        "git+https://github.com/webrecorder/chrome-remote-interface-py.git@master#egg=cripy"
    ],
    zip_safe=False,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    python_requires=">=3.6",
    test_suite="tests",
    tests_require=test_requirements,
)
