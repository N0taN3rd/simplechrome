from asyncio import (
    AbstractEventLoop,
    Event,
    Future,
    wait as aio_wait,
    FIRST_COMPLETED as aio_wait_until_first_completed,
)
from typing import Any, Awaitable, Dict, List, Optional, Set, TYPE_CHECKING

from aiofiles import open as aio_file_open
import attr


from .lifecycle_watcher import LifecycleWatcher
from .helper import Helper
from .jsHandle import ElementHandle, JSHandle
from .timeoutSettings import TimeoutSettings
from .waitTask import WaitTask

if TYPE_CHECKING:
    from .execution_context import ExecutionContext
    from .frame_manager import FrameManager, Frame


@attr.dataclass(slots=True, cmp=False)
class DOMWorld:
    _frameManager: "FrameManager" = attr.ib()
    _frame: "Frame" = attr.ib()
    _timeoutSettings: TimeoutSettings = attr.ib()
    _loop: Optional[AbstractEventLoop] = attr.ib(
        default=None, converter=Helper.ensure_loop
    )
    _documentPromise: Future = attr.ib(init=False, default=None, repr=False)
    _executionContext: "ExecutionContext" = attr.ib(init=False, default=None)
    _hasContextEvent: Event = attr.ib(init=False, default=None, repr=False)
    _contextResolveCallback: Future = attr.ib(init=False, default=None, repr=False)
    _waitTasks: Set[WaitTask] = attr.ib(init=False, factory=set, repr=False)
    _detached: bool = attr.ib(init=False, default=False)

    @property
    def frame(self) -> "Frame":
        return self._frame

    @property
    def timeout_settings(self) -> TimeoutSettings:
        return self._timeoutSettings

    @property
    def loop(self) -> AbstractEventLoop:
        return self._loop

    async def executionContext(self) -> "ExecutionContext":
        if self._detached:
            raise Exception(
                f"Execution Context is not available in detached frame '{self._frame.url}' (are you trying to evaluate?)"
            )
        await self._hasContextEvent.wait()
        return self._executionContext

    def add_wait_task(self, wait_task: WaitTask) -> None:
        self._waitTasks.add(wait_task)

    def remove_wait_task(self, wait_task: WaitTask) -> None:
        try:
            self._waitTasks.remove(wait_task)
        except KeyError:
            pass

    async def evaluateHandle(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> JSHandle:
        """Evaluates the js-function or js-expression in the current frame retrieving the results
        as a JSHandle.

        :param str pageFunction: String of js-function/expression to be executed
                               in the browser.
        :param bool withCliAPI:  Determines whether Command Line API should be available during the evaluation.
        If this keyword argument is true args are ignored
        """
        context = await self.executionContext()
        return await context.evaluateHandle(pageFunction, *args, withCliAPI=withCliAPI)

    async def evaluate(
        self, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> Any:
        """Evaluates the js-function or js-expression in the current frame retrieving the results
        of the evaluation.

        :param str pageFunction: String of js-function/expression to be executed
                               in the browser.
        :param bool withCliAPI:  Determines whether Command Line API should be available during the evaluation.
        If this keyword argument is true args are ignored
        """
        context = await self.executionContext()
        return await context.evaluate(pageFunction, *args, withCliAPI=withCliAPI)

    async def evaluate_expression(
        self, expression: str, withCliAPI: bool = False
    ) -> Any:
        """Evaluates the js expression in the frame returning the results by value.

        :param str expression: The js expression to be evaluated in the main frame.
        :param bool withCliAPI:  Determines whether Command Line API should be available during the evaluation.
        """
        context = await self.executionContext()
        return await context.evaluate_expression(expression, withCliAPI=withCliAPI)

    async def querySelector(self, selector: str) -> Optional[ElementHandle]:
        """Get element which matches `selector` string.

        Details see :meth:`simplechrome.page.Page.querySelector`.
        """
        document = await self._document()
        value = await document.querySelector(selector)
        return value

    async def querySelectorEval(
        self, selector: str, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> Any:
        document = await self._document()
        return await document.querySelectorEval(
            selector, pageFunction, *args, withCliAPI=withCliAPI
        )

    async def querySelectorAll(self, selector: str) -> List[ElementHandle]:
        document = await self._document()
        value = await document.querySelectorAll(selector)
        return value

    async def querySelectorAllEval(
        self, selector: str, pageFunction: str, *args: Any, withCliAPI: bool = False
    ) -> List[Any]:
        document = await self._document()
        value = await document.querySelectorAllEval(
            selector, pageFunction, *args, withCliAPI
        )
        return value

    async def xpath(self, expression: str) -> List[ElementHandle]:
        document = await self._document()
        value = await document.xpath(expression)
        return value

    async def content(self) -> str:
        return await self.evaluate(GET_DOCUMENT_HTML_JS)

    async def setContent(
        self, html: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> None:
        """Set content to this page."""
        opts = Helper.merge_dict(options, kwargs)
        timeout = opts.get("timeout", self._timeoutSettings.timeout)
        waitUnitl = opts.get("waitUntil", ["load"])
        all_frames = opts.get("all_frames", True)
        await self.evaluate(SET_DOCUMENT_HTML_JS, html)
        watcher = LifecycleWatcher(
            self._frameManager, self._frame, waitUnitl, timeout, all_frames, self._loop
        )
        done, pending = await aio_wait(
            {
                watcher.timeoutPromise,
                watcher.terminationPromise,
                watcher.lifecyclePromise,
            },
            return_when=aio_wait_until_first_completed,
            loop=self._loop,
        )
        watcher.dispose()
        error = done.pop().result()
        if error is not None:
            raise error

    async def addScriptTag(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> ElementHandle:
        opts = Helper.merge_dict(options, kwargs)
        url = opts.get("url")
        type_ = opts.get("type")
        if url is not None:
            try:
                context = await self.executionContext()
                result = await context.evaluate(ADD_SCRIPT_URL_JS, url, type_)
                return result.asElement()
            except Exception:
                raise Exception(f"Loading script from {url} failed")

        path = opts.get("path")
        if path is not None:
            async with aio_file_open(path, "r") as contents_in:
                contents = await contents_in.read()
            context = await self.executionContext()
            result = await context.evaluateHandle(
                ADD_SCRIPT_CONTENT_JS, contents, type_
            )
            return result.asElement()

        content = opts.get("content")
        if content is not None:
            context = await self.executionContext()
            result = await context.evaluateHandle(ADD_SCRIPT_CONTENT_JS, content, type_)
            return result.asElement()

        raise Exception("Provide an object with a `url`, `path` or `content` property")

    async def addStyleTag(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> ElementHandle:
        opts = Helper.merge_dict(options, kwargs)
        url = opts.get("url")
        type_ = opts.get("type")
        if url is not None:
            try:
                context = await self.executionContext()
                result = await context.evaluate(ADD_STYLE_URL_JS, url, type_)
                return result.asElement()
            except Exception:
                raise Exception(f"Loading style from {url} failed")

        path = opts.get("path")
        if path is not None:
            async with aio_file_open(path, "r") as contents_in:
                contents = await contents_in.read()
            context = await self.executionContext()
            result = await context.evaluateHandle(ADD_STYLE_CONTENT_JS, contents, type_)
            return result.asElement()

        content = opts.get("content")
        if content is not None:
            context = await self.executionContext()
            result = await context.evaluateHandle(ADD_STYLE_CONTENT_JS, content, type_)
            return result.asElement()

        raise Exception("Provide an object with a `url`, `path` or `content` property")

    async def click(self, selector: str, options: dict = None, **kwargs: Any) -> None:
        options = Helper.merge_dict(options, kwargs)
        handle = await self.querySelector(selector)
        if not handle:
            raise Exception("No node found for selector: " + selector)
        await handle.click(options)
        await handle.dispose()

    async def focus(self, selector: str) -> None:
        handle = await self.querySelector(selector)
        if not handle:
            raise Exception("No node found for selector: " + selector)
        await self.evaluate("element => element.focus()", handle)
        await handle.dispose()

    async def hover(self, selector: str) -> None:
        handle = await self.querySelector(selector)
        if not handle:
            raise Exception("No node found for selector: " + selector)
        await handle.hover()
        await handle.dispose()

    async def select(self, selector: str, *values: str) -> List[str]:
        for value in values:
            if not isinstance(value, str):
                emsg = f"Values must be string. Found {value} of type {type(value)}"
                raise TypeError(emsg)
        result = await self.querySelectorEval(selector, SELECT_JS, values)
        return result

    async def tap(self, selector: str) -> None:
        handle = await self.querySelector(selector)
        if not handle:
            raise Exception("No node found for selector: " + selector)
        await handle.tap()
        await handle.dispose()

    async def type(
        self, selector: str, text: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> None:
        options = Helper.merge_dict(options, kwargs)
        handle = await self.querySelector(selector)
        if handle is None:
            raise Exception("Cannot find {} on this page".format(selector))
        await handle.type(text, options)
        await handle.dispose()

    async def title(self) -> str:
        doc_title: str = await self.evaluate("() => document.title")
        return doc_title

    def waitForSelector(
        self, selector: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> Awaitable[Optional[ElementHandle]]:
        return self._waitForSelectorOrXPath(
            selector, False, Helper.merge_dict(options, kwargs)
        )

    def waitForXPath(
        self, xpath: str, options: Optional[Dict] = None, **kwargs: Any
    ) -> Awaitable[Optional[ElementHandle]]:
        return self._waitForSelectorOrXPath(
            xpath, True, Helper.merge_dict(options, kwargs)
        )

    def waitForFunction(
        self,
        pageFunction: str,
        options: Optional[Dict] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Awaitable[JSHandle]:
        options = Helper.merge_dict(options, kwargs)
        timeout = options.get("timeout", self._timeoutSettings.timeout)
        js_timeout = options.get("js_timeout", self._timeoutSettings.js_timeout)
        polling = options.get("polling", "raf")
        return WaitTask(
            self, pageFunction, "function", polling, timeout, js_timeout, *args
        ).promise

    #: alias to :meth:`xpath`
    Jx = xpath
    #: alias to :meth:`querySelector`
    J = querySelector
    #: alias to :meth:`querySelectorEval`
    Jeval = querySelectorEval
    #: alias to :meth:`querySelectorAll`
    JJ = querySelectorAll
    #: alias to :meth:`querySelectorAllEval`
    JJeval = querySelectorAllEval

    async def _document(self) -> ElementHandle:
        if self._documentPromise:
            return await self._documentPromise
        context = await self.executionContext()
        doc_handle = await context.evaluateHandle("document")
        return doc_handle.asElement()

    async def _waitForSelectorOrXPath(
        self, selectorOrXPath: str, isXPath: bool, options: Dict
    ) -> Optional[ElementHandle]:
        waitForVisible: bool = options.get("visible", False)
        waitForHidden: bool = options.get("hidden", False)
        timeout = options.get("timeout", self._timeoutSettings.timeout)
        js_timeout = options.get("js_timeout", self._timeoutSettings.js_timeout)
        polling = "raf" if waitForVisible or waitForHidden else "mutation"
        title_which = "XPath" if isXPath else "selector"
        to_be_what = " to be hidden" if waitForHidden else ""
        title = f'{title_which} "{selectorOrXPath}"{to_be_what}'
        wait_task = WaitTask(
            self,
            WAIT_FOR_SELECTOR_OR_XPATH_JS,
            title,
            polling,
            timeout,
            js_timeout,
            selectorOrXPath,
            isXPath,
            waitForVisible,
            waitForHidden,
        )
        handle = await wait_task.promise
        element_handle = handle.asElement()
        if not element_handle:
            await handle.dispose()
            return None
        return element_handle

    def _setContext(self, context: Optional["ExecutionContext"] = None) -> None:
        if context is not None:
            self._executionContext = context
            self._hasContextEvent.set()
            for wait_task in self._waitTasks:
                wait_task.rerun()
        else:
            self._documentPromise = None
            self._executionContext = None
            self._hasContextEvent.clear()

    def _detach(self) -> None:
        self._detached = True
        for wait_task in self._waitTasks:
            wait_task.terminate(
                Exception("waitForFunction failed: frame got detached.")
            )

    def __attrs_post_init__(self) -> None:
        self._hasContextEvent = Event(loop=self._loop)


GET_DOCUMENT_HTML_JS: str = """() => {
  let result = ['', ''];
  if (document.doctype) {
    result[0] = new XMLSerializer().serializeToString(document.doctype);
  }
  if (document.documentElement) {
    result[1] = document.documentElement.outerHTML;
  }
  return result.join('');
}"""

SET_DOCUMENT_HTML_JS: str = """function (html) {
  document.open();
  document.write(html);
  document.close();
}"""

ADD_SCRIPT_URL_JS: str = """async function addScriptUrl(url, type) {
  const script = document.createElement('script');
  script.src = url;
  if (type) {
    script.type = type;
  }
  const promise = new Promise((resolve, reject) => {
    script.onload = resolve;
    script.onerror = reject;
  });
  document.head.appendChild(script);
  await promise;
  return script;
}"""

ADD_SCRIPT_CONTENT_JS: str = """function addScriptContent(content, type = 'text/javascript') {
  const script = document.createElement('script');
  script.type = type;
  script.text = content;
  let error = null;
  script.onerror = e => error = e;
  document.head.appendChild(script);
  if (error) {
    throw error;
  }
  return script;
}"""

ADD_STYLE_URL_JS: str = """async function addStyleUrl(url) {
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = url;
  const promise = new Promise((resolve, reject) => {
    link.onload = resolve;
    link.onerror = reject;
  });
  document.head.appendChild(link);
  await promise;
  return link;
}"""

ADD_STYLE_CONTENT_JS: str = """async function addStyleContent(content) {
  const style = document.createElement('style');
  style.type = 'text/css';
  style.appendChild(document.createTextNode(content));
  const promise = new Promise((resolve, reject) => {
    style.onload = resolve;
    style.onerror = reject;
  });
  document.head.appendChild(style);
  await promise;
  return style;
}"""

SELECT_JS: str = """function selectOptions (element, values) {
  if (element.nodeName.toLowerCase() !== 'select'){
    throw new Error('Element is not a <select> element.');
  }
  const options = Array.from(element.options);
  element.value = undefined;
  let i = 0;
  let len = options.length;
  let option;
  for (; i < len; i++) {
    option = options[i];
    option.selected = values.includes(option.value);
    if (option.selected && !element.multiple) {
      break;
    }
  }
  element.dispatchEvent(new Event('input', { 'bubbles': true }));
  element.dispatchEvent(new Event('change', { 'bubbles': true }));
  let results = [];
  for (i = 0; i < len; i++) {
    option = options[i];
    if (option.selected) {
      results.push(option.value)
    }
  }
  return results;
}"""

WAIT_FOR_SELECTOR_OR_XPATH_JS: str = """function predicate(selectorOrXPath, isXPath, waitForVisible, waitForHidden) {
  const node = isXPath
    ? document.evaluate(selectorOrXPath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue
    : document.querySelector(selectorOrXPath);
  if (!node)
    return waitForHidden;
  if (!waitForVisible && !waitForHidden)
    return node;
  const element = /** @type {Element} */ (node.nodeType === Node.TEXT_NODE ? node.parentElement : node);

  const style = window.getComputedStyle(element);
  const isVisible = style && style.visibility !== 'hidden' && hasVisibleBoundingBox();
  const success = (waitForVisible === isVisible || waitForHidden === !isVisible);
  return success ? node : null;

  /**
   * @return {boolean}
   */
  function hasVisibleBoundingBox() {
    const rect = element.getBoundingClientRect();
    return !!(rect.top || rect.bottom || rect.width || rect.height);
  }
}"""
