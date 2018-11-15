import asyncio
from typing import Any, Optional, Union, TYPE_CHECKING

from .errors import PageError, WaitTimeoutError
from .execution_context import JSHandle
from .helper import Helper

if TYPE_CHECKING:
    from .frame_manager import Frame  # noqa: F401

__all__ = ["WaitTask"]


class WaitTask(object):
    """WaitTask class.

    Instance of this class is awaitable.
    """

    def __init__(
        self,
        frame: "Frame",
        predicateBody: str,
        polling: Union[str, int, float],
        timeout: Union[float, int],
        *args: Any,
    ) -> None:
        if isinstance(polling, str):
            if polling not in ["raf", "mutation"]:
                raise ValueError(f"Unknown polling: {polling}")
        elif isinstance(polling, (int, float)):
            if polling <= 0:
                raise ValueError(f"Cannot poll with non-positive interval: {polling}")
        else:
            raise ValueError(f"Unknown polling option: {polling}")

        self._frame: "Frame" = frame
        self._polling: Union[str, int, float] = polling
        self._timeout: Union[float, int] = timeout
        if args or Helper.is_jsfunc(predicateBody):
            self._predicateBody = f"return ({predicateBody})(...args)"
        else:
            self._predicateBody = f"return {predicateBody}"
        self._args = args
        self._runCount = 0
        self._terminated = False
        self._timeoutError = False
        frame._waitTasks.add(self)

        loop = asyncio.get_event_loop()
        self.promise = loop.create_future()
        if timeout:
            self._timeoutTimer = loop.create_task(self.timeout_timer(self._timeout))
        loop.create_task(self.rerun())

    async def timeout_timer(self, to: Union[int, float]) -> None:
        await asyncio.sleep(to / 1000)
        self._timeoutError = True
        self.terminate(WaitTimeoutError(f"Waiting failed: timeout {to}ms exceeds."))

    def __await__(self) -> Any:
        """Make this class **awaitable**."""
        yield from self.promise
        return self.promise.result()

    def terminate(self, error: Exception) -> None:
        """Terminate this task."""
        self._terminated = True
        if self.promise and not self.promise.done():
            self.promise.set_exception(error)
        self._cleanup()

    async def rerun(self) -> None:  # noqa: C901
        """Start polling."""
        runCount = self._runCount = self._runCount + 1
        success: Optional[JSHandle] = None
        error = None

        try:
            context = await self._frame.executionContext()
            if context is None:
                raise PageError("No execution context.")
            success = await context.evaluateHandle(
                waitForPredicatePageFunction,
                self._predicateBody,
                self._polling,
                self._timeout,
                *self._args,
            )
        except Exception as e:
            error = e

        if self.promise.done():
            return

        if self._terminated or runCount != self._runCount:
            if success:
                await success.dispose()
            return

        if (
            error is None
            and success
            and (await self._frame.evaluate("s => !s", success))
        ):
            await success.dispose()
            return

        # page is navigated and context is destroyed.
        # Try again in the new execution context.
        if (
            isinstance(error, Exception)
            and "Execution context was destroyed" in error.args[0]
        ):
            return

        # Try again in the new execution context.
        if (
            isinstance(error, Exception)
            and "Cannot find context with specified id" in error.args[0]
        ):
            return

        if error:
            self.promise.set_exception(error)
        else:
            self.promise.set_result(success)

        self._cleanup()

    def _cleanup(self) -> None:
        if self._timeout and self._timeoutTimer and not self._timeoutTimer.done():
            self._timeoutTimer.cancel()
        self._frame._waitTasks.remove(self)


waitForPredicatePageFunction: str = """
async function waitForPredicatePageFunction(predicateBody, polling, timeout, ...args) {
  const predicate = new Function('...args', predicateBody);
  let timedOut = false;
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
}
"""
