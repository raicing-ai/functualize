"""Job-level `Exec` policy: retry and run-mode dedup (§A.5).

`Exec` was accepted by `@job`, validated, and serialized into the cache while
none of its fields did anything except `platforms` (which the guard pipeline
reads). This module is the behavior.

**There is no job-level timeout, by research rather than omission.** A first
version ran the body in a daemon thread and reported ``TIMEOUT`` on overrun —
but Python cannot preempt a running function, so the work simply continued in
the background. That is a worse failure than no timeout: a caller that believes
the job stopped may release a lock or delete a file the still-live job is
using. A signal-based version (``SIGALRM``) would work only on POSIX *and* only
on the main thread, so it would silently do nothing in the TUI, which runs jobs
via ``run_worker(thread=True)`` — a bound whose enforcement depends on which
surface you launched from.

The two mature runners in this space agree: `invoke` has no task-level timeout
at all (only ``run(cmd, timeout=)``, a ``threading.Timer`` that ``SIGKILL``s a
subprocess), and `doit` has none either — its ``doit.tools.timeout`` is an
``uptodate`` checker, a freshness TTL, which is `Fingerprint`'s job here. Bound
work where the OS can enforce it: ``sh(..., timeout=N)`` kills the process
group (§B.4).

**Retry reuses the shell's backoff policy** rather than defining a second one,
so ``Retry(backoff="exponential")`` means the same thing at both levels.

**Run modes are session-scoped**, per §A.5: ``"once"`` collapses every
invocation in this process to the first, ``"when_changed"`` collapses
invocations with identical resolved arguments. Both are in-memory by design —
they say "not twice in this run", not "not twice ever", which is what the
fingerprint is for.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["ExecPolicy", "RunModeCache"]

logger = logging.getLogger(__name__)


class RunModeCache:
    """Remembers what ran this session, for ``Exec.run`` dedup.

    In-memory and per-engine: "once" means once per process, not once ever.
    A persistent version of this is what `Fingerprint` already provides, and
    conflating the two would make a debugging re-run impossible without
    clearing state that also governs caching.
    """

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def seen(self, job_name: str, mode: str, args_hash: str) -> bool:
        """True when this job already ran under ``mode`` this session."""
        key = self._key(job_name, mode, args_hash)
        return key is not None and key in self._seen

    def remember(self, job_name: str, mode: str, args_hash: str) -> None:
        key = self._key(job_name, mode, args_hash)
        if key is not None:
            self._seen.add(key)

    @staticmethod
    def _key(job_name: str, mode: str, args_hash: str) -> tuple[str, str] | None:
        if mode == "once":
            return (job_name, "")  # args ignored — once is once
        if mode == "when_changed":
            return (job_name, args_hash)
        return None


class ExecPolicy:
    """Applies `Exec` to one invocation.

    Args:
        run_mode_cache: Session dedup store, shared across invocations.
    """

    def __init__(self, run_mode_cache: RunModeCache | None = None) -> None:
        self._run_modes = run_mode_cache or RunModeCache()

    @property
    def run_modes(self) -> RunModeCache:
        return self._run_modes

    def call(
        self,
        body: Callable[[], Any],
        exec_decl: Any,
        *,
        job_name: str = "",
        failure_of: Callable[[Any], BaseException | None] | None = None,
    ) -> Any:
        """Run ``body`` under ``exec_decl``, retrying per its policy.

        ``failure_of`` maps a returned result to the exception it represents,
        or None if it succeeded. It exists because the executor's lifecycle
        **catches** a job's exception and returns a FAILURE result rather than
        propagating it — so a retry that only watched for raises would never
        fire, which is exactly the bug the first version of this module had.
        """
        retry = getattr(exec_decl, "retry", None) if exec_decl else None
        attempts = max(1, getattr(retry, "attempts", 1) if retry else 1)

        last_error: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                result = body()
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                last_error = exc
                if attempt < attempts and self._retryable(retry, exc):
                    self._sleep(retry, attempt)
                    continue
                raise
            else:
                failure = failure_of(result) if failure_of is not None else None
                if (
                    failure is not None
                    and attempt < attempts
                    and self._retryable(retry, failure)
                ):
                    self._sleep(retry, attempt)
                    continue
                return result
        # Unreachable in practice: the loop either returns or re-raises.
        raise last_error if last_error is not None else RuntimeError("no attempt ran")

    @staticmethod
    def _retryable(retry: Any, exc: BaseException | None) -> bool:
        """Whether this failure is one the policy said to retry."""
        if retry is None:
            return False
        on = tuple(getattr(retry, "on", ()) or ())
        exit_codes = tuple(getattr(retry, "on_exit_codes", ()) or ())
        if not on and not exit_codes:
            return True  # empty means "retry on any failure" (§A.5)
        if exc is not None and on and isinstance(exc, on):
            return True
        code = getattr(exc, "returncode", None)
        return bool(exit_codes and code in exit_codes)

    @staticmethod
    def _sleep(retry: Any, attempt: int) -> None:
        """Back off between attempts, reusing the shell's policy (§A.5)."""
        from functualize._engine.capabilities.shell import _sleep_backoff

        _sleep_backoff(retry, attempt)
