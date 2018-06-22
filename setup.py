from setuptools import setup, find_packages

requirements = [
    "aiohttp",
    "uvloop",
    "aiodns",
    "cchardet",
    "pyee",
    "websockets",
    "ujson",
    "yarl",
    "async-timeout",
    "aiofiles",
]

test_requirements = ["syncer", "pytest", "pytest-asyncio", "robber", "psutil"]

setup(
    name="simplechrome",
    version="1.0.0",
    description=(
        "Headless chrome/chromium automation testing library" "(unofficial port of puppeteer)"
    ),
    author="Webrecorder",
    author_email="Webrecorder.Webrecorder@Webrecorder.com",
    packages=find_packages(),
    include_package_data=True,
    install_requires=requirements,
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
