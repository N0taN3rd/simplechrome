# Simplechrome
A fork of [pypuppeteer](https://github.com/miyakogi/pyppeteer) used by Webrecorder for QA automation that has been modified to meet our needs.

Simplechrome contains a subset of the full api provided by pypuppeteer and puppeteer, in particular Simplechrome does not support the `Security domain` or `Request interception` 

Notable Additions to the API / code base per our own use-case:
- Changes to allow control of latests revisions of both Chrome and Chromium
- Changes to facilitate using the [uvloop](https://github.com/MagicStack/uvloop) event loop 
- Changes to input handling for `evaluateOnNewDocument`
- Tracking child frame life cyles individually 
- Less strict application defaults

## Installation

Simplechrome requires python 3.6+.

Install latest version from [github](https://github.com/webrecorder/simplechrome):

```
pip install -U git+https://github.com/webrecorder/simplechrome.git@master
```

## Usage

> **Note**: When you run simplechrome first time (if you do not supply an `executablePath`), it will download a recent version of Chromium (~100MB).

**Example**: Go to a web page and take a screenshot.

```py
import asyncio
import uvloop
from simplechrome import launch

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


async def main():
    browser = await launch()
    page = await browser.newPage()
    await page.goto('http://example.com')
    await page.screenshot({'path': 'example.png'})
    await browser.close()
    
if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
```
