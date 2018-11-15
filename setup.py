from setuptools import setup, find_packages

requirements = [
    "aiohttp",
    "aiodns",
    "cchardet",
    "pyee",
    "ujson",
    "async-timeout",
    "aiofiles",
    "urllib3",
    "attrs",
    "cripy"
]

test_requirements = ["pytest", "pytest-asyncio", "psutil", "grappa", "vibora", "uvloop"]

setup(
    name="simplechrome",
    version="1.3.3",
    description=(
        "Headless chrome/chromium automation library"
        "(unofficial fork of pypuppeteer that stays more up to date with puppeteer)"
    ),
    author="Webrecorder",
    author_email="Webrecorder.Webrecorder@Webrecorder.com",
    packages=find_packages(exclude=['tests']),
    include_package_data=True,
    install_requires=requirements,
    dependency_links=[
        "git+https://github.com/webrecorder/chrome-remote-interface-py.git@master#egg=cripy"
    ],
    zip_safe=False,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
    ],
    python_requires=">=3.6",
    test_suite="tests",
    tests_require=test_requirements,
)
