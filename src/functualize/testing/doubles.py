"""Test doubles for functualize capability types.

Provides lightweight, predictable replacements for framework capabilities
that can be used in unit tests without requiring the full runtime:

- CapturingLog: Records (level, message) tuples in insertion order.
- MockInvoke: Returns pre-configured results by job name.
- AutoPrompt: Returns pre-configured responses in FIFO order.
- NoopPerf: Silently accepts all performance measurement calls.

Requirements: 8.3, 8.4, 8.5
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from functualize._engine.capabilities.invoke import Invoke
from functualize._engine.capabilities.log import Log
from functualize._engine.capabilities.perf import Perf
from functualize._engine.capabilities.prompt import Prompt


class CapturingLog(Log):
    """Test double for the Log capability that records all log calls.

    Each call is stored as a (level, message) tuple in insertion order.
    Supports both the __call__ syntax and named level methods.

    Example:
        log = CapturingLog()
        log("hello")
        log.warning("watch out")
        assert log.calls == [("info", "hello"), ("warning", "watch out")]
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, object]] = []

    def __call__(self, message: object, level: str = "info") -> None:
        """Record a log call as (level, message)."""
        self.calls.append((level, message))

    def info(self, msg: object) -> None:
        """Record an info-level log call."""
        self(msg, level="info")

    def warning(self, msg: object) -> None:
        """Record a warning-level log call."""
        self(msg, level="warning")

    def error(self, msg: object) -> None:
        """Record an error-level log call."""
        self(msg, level="error")

    def debug(self, msg: object) -> None:
        """Record a debug-level log call."""
        self(msg, level="debug")


class MockInvoke(Invoke):
    """Test double for the Invoke capability with pre-configured results.

    Accepts a mapping of job names to result values at construction.
    Returns the mapped result when invoked; raises KeyError on unknown job names.

    Example:
        invoke = MockInvoke({"deploy": result_obj})
        result = invoke("deploy")  # returns result_obj
        invoke("unknown")          # raises KeyError
    """

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self._results: dict[str, Any] = results or {}

    @staticmethod
    def _name_of(job_or_fn: str | Callable[..., Any]) -> str:
        """Reduce a job reference to the name used as the mapping key."""
        return job_or_fn if isinstance(job_or_fn, str) else job_or_fn.__name__

    def __call__(self, job_or_fn: str | Callable[..., Any], **kwargs: Any) -> Any:
        """Return the pre-configured result for the given job.

        Every keyword the real Invoke accepts is absorbed and ignored, so a job
        that passes ``config=``, ``timeout=``, or a gate option behaves the same
        under test as it does in production.

        Raises:
            KeyError: If the job has no configured result.
        """
        job_name = self._name_of(job_or_fn)
        if job_name not in self._results:
            raise KeyError(
                f"MockInvoke has no configured result for job '{job_name}'. "
                f"Available: {sorted(self._results.keys())}"
            )
        return self._results[job_name]

    def parallel(
        self,
        jobs: Sequence[tuple[str | Callable[..., Any], dict[str, Any]]],
        **kwargs: Any,
    ) -> list[Any]:
        """Return pre-configured results for each job in order.

        Raises:
            KeyError: If any job has no configured result.
        """
        return [self(job_or_fn, **job_kwargs) for job_or_fn, job_kwargs in jobs]

    def schema(self, job_or_fn: str | Callable[..., Any]) -> Any:
        """Return the pre-configured result for the given job as schema.

        For testing purposes, this returns whatever is mapped for the job name.

        Raises:
            KeyError: If the job has no configured result.
        """
        job_name = self._name_of(job_or_fn)
        if job_name not in self._results:
            raise KeyError(
                f"MockInvoke.schema has no configured result for job '{job_name}'. "
                f"Available: {sorted(self._results.keys())}"
            )
        return self._results[job_name]


class AutoPrompt(Prompt):
    """Test double for the Prompt capability with FIFO responses.

    Accepts a sequence of responses at construction and returns them
    one at a time in order. Raises IndexError when exhausted.

    Example:
        prompt = AutoPrompt(["yes", True, "choice_a"])
        prompt.text("Name?")       # returns "yes"
        prompt.confirm("Sure?")    # returns True
        prompt.text("Pick one?")   # returns "choice_a"
        prompt.text("Another?")    # raises IndexError
    """

    def __init__(self, responses: list[Any] | None = None) -> None:
        super().__init__()
        self._responses: list[Any] = list(responses) if responses else []
        self._index: int = 0

    def _next_response(self) -> Any:
        """Return the next response in FIFO order.

        Raises:
            IndexError: If all pre-configured responses have been consumed.
        """
        if self._index >= len(self._responses):
            raise IndexError(
                f"AutoPrompt exhausted: all {len(self._responses)} "
                f"pre-configured responses have been consumed."
            )
        response = self._responses[self._index]
        self._index += 1
        return response

    def ask(self, request: Any) -> Any:
        """Return the next pre-configured response.

        Raises:
            IndexError: When exhausted.
        """
        return self._next_response()

    # Parameter names below mirror Prompt exactly. A job calling
    # prompt.text(message="...") by keyword must bind against the double the
    # same way it binds against the real capability.
    def confirm(self, message: str, *, default: bool = False, **kwargs: Any) -> Any:
        """Return the next pre-configured response.

        Raises:
            IndexError: When exhausted.
        """
        return self._next_response()

    def choice(self, message: str, options: list[Any], **kwargs: Any) -> Any:
        """Return the next pre-configured response.

        Raises:
            IndexError: When exhausted.
        """
        return self._next_response()

    def text(self, message: str, *, default: str = "", **kwargs: Any) -> Any:
        """Return the next pre-configured response.

        Raises:
            IndexError: When exhausted.
        """
        return self._next_response()


class NoopPerf(Perf):
    """Test double for the Perf capability that silently accepts all calls.

    All mark, mark_start, and mark_end calls are accepted without
    recording or raising. phases() returns an empty list.

    Example:
        perf = NoopPerf()
        perf.mark("init")            # no-op
        perf.mark_start("phase_1")   # no-op
        perf.mark_end("phase_1")     # no-op
        perf.phases()                # returns []
    """

    def mark(self, name: str) -> None:
        """Accept a mark call silently."""

    def mark_start(self, name: str) -> None:
        """Accept a mark_start call silently."""

    def mark_end(self, name: str) -> None:
        """Accept a mark_end call silently."""

    def phases(
        self, include: str | None = None, exclude: str | None = None
    ) -> list[Any]:
        """Return an empty list of phases."""
        return []
