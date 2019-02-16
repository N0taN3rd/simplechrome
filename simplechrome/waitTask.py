from asyncio import AbstractEventLoop, Future, Task, sleep as aio_sleep
from typing import Any, Awaitable, Generator, List, Optional, Union, TYPE_CHECKING

from .errors import WaitTimeoutError
from .helper import Helper
from .jsHandle import JSHandle

if TYPE_CHECKING:
    from .domWorld import DOMWorld  # noqa: F401

__all__ = ["WaitTask"]

ACCEPTABLE_POLLING_STRINGS: List[str] = ["raf", "mutation"]


class WaitTask:
    def __init__(
        self,
        domWorld: "DOMWorld",
        predicateBody: str,
        title: str,
        polling: Union[str, int, float],
        timeout: Union[float, int],
        js_timeout: Union[float, int],
        *args: Any,
    ) -> None:
        if Helper.is_string(polling):
            if polling not in ACCEPTABLE_POLLING_STRINGS:
                raise ValueError(f"Unknown polling: {polling}")
        elif Helper.is_number(polling):
            if polling < 0:
                raise ValueError(f"Cannot poll with non-positive interval: {polling}")
        else:
            raise ValueError(f"Unknown polling option: {polling}")

        self._domWorld: "DOMWorld" = domWorld
        self._title: str = title
        self._loop: AbstractEventLoop = self._domWorld.loop
        self._polling: Union[str, int, float] = polling
        self._timeout: Union[float, int] = timeout
        self._js_timeout: Union[float, int] = js_timeout
        self._predicateBody: str = f"return ({predicateBody})(...args);" if Helper.is_jsfunc(
            predicateBody
        ) else f"return {predicateBody}"

        self._args: Any = args
        self._runCount: int = 0
        self._terminated: bool = False
        self._timeoutError: bool = False
        self._promise: Future = self._loop.create_future()
        self._timeoutTimer: Optional[Task] = self._loop.create_task(
            self._timeout_timer(self._timeout)
        ) if timeout is not None else None
        self._domWorld.add_wait_task(self)
        self._loop.create_task(self.rerun())

    @property
    def promise(self) -> Awaitable[JSHandle]:
        return self._promise

    def terminate(self, error: Exception) -> None:
        """Terminate this task."""
        self._terminated = True
        if self._promise is not None and not self._promise.done():
            self._promise.set_exception(error)
        self._cleanup()

    async def rerun(self) -> None:  # noqa: C901
        """Start polling."""
        runCount = self._runCount = self._runCount + 1
        success: Optional[JSHandle] = None
        error = None

        try:
            context = await self._domWorld.executionContext()
            if context is None:
                error = Exception("No execution context.")
            else:
                success = await context.evaluateHandle(
                    waitForPredicatePageFunction,
                    self._predicateBody,
                    self._polling,
                    self._js_timeout,
                    *self._args,
                )
        except Exception as e:
            error = e

        if self._promise.done():
            return

        if self._terminated or runCount != self._runCount:
            if success:
                await success.dispose()
            return

        # Ignore timeouts in pageScript - we track timeouts ourselves.
        # If the frame's execution context has already changed, `frame.evaluate` will
        # throw an error - ignore this predicate run altogether.
        try:
            ignore_based_on_frame_execution_context = await self._domWorld.evaluate(
                "s => !s", success
            )
        except Exception:
            ignore_based_on_frame_execution_context = True

        if error is None and ignore_based_on_frame_execution_context:
            await success.dispose()
            return

        # When the page is navigated, the promise is rejected
        # We will try again in the new execution context.
        if (
            isinstance(error, Exception)
            and "Execution context was destroyed" in error.args[0]
        ):
            return

        # We could have tried to evaluate in a context which was already
        # destroyed
        if (
            isinstance(error, Exception)
            and "Cannot find context with specified id" in error.args[0]
        ):
            return

        if error:
            self._promise.set_exception(error)
        else:
            self._promise.set_result(success)

        self._cleanup()

    def _cleanup(self) -> None:
        if self._timeoutTimer and not self._timeoutTimer.done():
            self._timeoutTimer.cancel()
        self._domWorld.remove_wait_task(self)

    async def _timeout_timer(self, to: Union[int, float]) -> None:
        await aio_sleep(to, loop=self._loop)
        self._timeoutError = True
        self.terminate(
            WaitTimeoutError(
                f"Waiting for {self._title} failed: timeout {to}s exceeds."
            )
        )

    def __await__(self) -> Generator[Any, Any, JSHandle]:
        yield from self._promise.__await__()
        return self._promise.result()


waitForPredicatePageFunction: str = """async function waitForPredicatePageFunction(predicateBody, polling, timeout, ...args) {
  const predicate = new Function('...args', predicateBody);
  let timedOut = false;
  if (timeout)
    setTimeout(() => timedOut = true, timeout);
  if (polling === 'raf')
    return await pollRaf();
  if (polling === 'mutation')
    return await pollMutation();
  if (typeof polling === 'number')
    return await pollInterval(polling);

  /**
   * @return {!Promise<*>}
   */
  function pollMutation() {
    const success = predicate.apply(null, args);
    if (success)
      return Promise.resolve(success);

    let fulfill;
    const result = new Promise(x => fulfill = x);
    const observer = new MutationObserver(mutations => {
      if (timedOut) {
        observer.disconnect();
        fulfill();
      }
      const success = predicate.apply(null, args);
      if (success) {
        observer.disconnect();
        fulfill(success);
      }
    });
    observer.observe(document, {
      childList: true,
      subtree: true,
      attributes: true
    });
    return result;
  }

  /**
   * @return {!Promise<*>}
   */
  function pollRaf() {
    let fulfill;
    const result = new Promise(x => fulfill = x);
    onRaf();
    return result;

    function onRaf() {
      if (timedOut) {
        fulfill();
        return;
      }
      const success = predicate.apply(null, args);
      if (success)
        fulfill(success);
      else
        requestAnimationFrame(onRaf);
    }
  }

  /**
   * @param {number} pollInterval
   * @return {!Promise<*>}
   */
  function pollInterval(pollInterval) {
    let fulfill;
    const result = new Promise(x => fulfill = x);
    onTimeout();
    return result;

    function onTimeout() {
      if (timedOut) {
        fulfill();
        return;
      }
      const success = predicate.apply(null, args);
      if (success)
        fulfill(success);
      else
        setTimeout(onTimeout, pollInterval);
    }
  }
}"""
