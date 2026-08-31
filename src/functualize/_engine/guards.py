"""Guard pipeline: precedence and multi-state skip semantics (§D.2, §D.7b).

The proposal's contract, evaluated per job **before** execution, in this order:

1. ``platforms`` — mismatch → **SKIP_NEUTRAL** ("not applicable here").
2. ``preconditions`` — any failure → **ERROR** ("environment is wrong, a human
   must act").
3. ``status`` — all pass → **SKIP_SATISFIED** ("already done").
4. Fingerprint — up to date → **SKIP_FRESH**.

The states are distinct because CI needs to tell them apart: neutral skips are
invisible, satisfied/fresh skips are reported with a reason, and precondition
failures fail the run. :data:`GuardState.BLOCKED` joins them for gates (§D.7b) —
surface-resolved input acquisition, carrying the model it awaits.

**Companion R10a (adopted).** A truthy ``status`` guard **ANDs with** file
staleness — it never overrides it. A status check saying "already done" must not
mask sources that changed since the last run, which is the failure mode that
makes hand-rolled skip logic untrustworthy. The AND only applies where a file
signal actually exists: with ``method="none"`` or no declared sources there is
nothing to be stale about, so a satisfied status guard skips on its own.

Precondition results are cached per session (§D.2), keyed by command string or
callable identity, so ``docker --version`` runs once per run rather than once
per job.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from functualize._types.job_declaration import Precondition

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from functualize._primitives.fingerprint import FingerprintVerdict


class GuardState(Enum):
    """The outcome of the guard pipeline for one job (§D.2 + §D.7b)."""

    RUN = "run"
    SKIP_NEUTRAL = "skip_neutral"
    SKIP_SATISFIED = "skip_satisfied"
    SKIP_FRESH = "skip_fresh"
    BLOCKED = "blocked"
    ERROR = "error"
    #: The job declared inputs and none of them resolved. It did not run, and
    #: it is emphatically **not** a skip: a skip means "nothing to do", and
    #: this means "I was asked to verify files that are not there". Reporting
    #: it as a skip is the false-clean this state exists to make impossible.
    REFUSED = "refused"

    @property
    def is_skip(self) -> bool:
        """True for the three skip states (neutral, satisfied, fresh).

        REFUSED is not among them, on purpose — see the member's own note.
        """
        return self in (
            GuardState.SKIP_NEUTRAL,
            GuardState.SKIP_SATISFIED,
            GuardState.SKIP_FRESH,
        )


@dataclass(frozen=True)
class GuardVerdict:
    """Why a job will or will not run — the data `func why` renders (§D.6).

    Attributes:
        state: The pipeline outcome.
        reason: Human-readable explanation of that outcome.
        checks: Per-guard trace lines, in evaluation order.
        awaiting: For BLOCKED, the model whose input the job is waiting on.
    """

    state: GuardState
    reason: str
    checks: tuple[str, ...] = field(default=())
    awaiting: Any = None

    @property
    def will_run(self) -> bool:
        return self.state is GuardState.RUN


class PreconditionCache:
    """Session-scoped precondition memo (§D.2).

    Backed by a :class:`~functualize._primitives.state_store.StateStore` when
    one is supplied; otherwise in-memory for the process.
    """

    def __init__(self, store: Any = None) -> None:
        self._store = store
        self._memo: dict[str, bool] = {}

    def get(self, key: str) -> bool | None:
        if self._store is not None:
            return self._store.get_precondition(key)  # type: ignore[no-any-return]
        return self._memo.get(key)

    def set(self, key: str, passed: bool) -> None:
        if self._store is not None:
            self._store.set_precondition(key, passed)
        else:
            self._memo[key] = passed


def guard_key(check: Any) -> str:
    """Stable cache key for a guard: the command string, or callable identity."""
    if isinstance(check, str):
        return check
    name = getattr(check, "__qualname__", None) or getattr(check, "__name__", None)
    module = getattr(check, "__module__", "")
    if name:
        return f"{module}.{name}"
    return f"{type(check).__name__}@{id(check)}"


class GuardEvaluator:
    """Runs the §D.2 pipeline for a job.

    Args:
        shell_runner: Runs a guard's shell string, returning True on exit 0.
            Injected so guards are testable without spawning processes.
        cache: Session precondition cache; a fresh in-memory one by default.
        platform: Platform identifier matched against ``Exec.platforms``.
    """

    def __init__(
        self,
        shell_runner: Callable[[str], bool] | None = None,
        cache: PreconditionCache | None = None,
        platform: str | None = None,
    ) -> None:
        self._shell_runner = shell_runner
        self._cache = cache if cache is not None else PreconditionCache()
        self._platform = platform or sys.platform

    def evaluate(
        self,
        *,
        platforms: Sequence[str] | None = None,
        preconditions: Sequence[Any] = (),
        status: Sequence[Any] = (),
        config: Any = None,
        fingerprint: FingerprintVerdict | None = None,
        has_file_signal: bool = False,
    ) -> GuardVerdict:
        """Evaluate the pipeline and return the verdict.

        Args:
            platforms: Allowed platforms; None means "anywhere".
            preconditions: Shell strings, callables, or ``Precondition`` objects.
            status: Shell strings or callables reporting "already done".
            config: Passed to callable guards.
            fingerprint: The file-staleness verdict, if one was computed.
            has_file_signal: Whether file staleness is a meaningful axis
                (method is not "none" and sources were declared). Drives the
                R10a AND.
        """
        checks: list[str] = []

        neutral = self._check_platforms(platforms, checks)
        if neutral is not None:
            return neutral

        error = self._check_preconditions(preconditions, config, checks)
        if error is not None:
            return error

        satisfied = self._status_satisfied(status, config, checks)
        fresh = fingerprint.up_to_date if fingerprint is not None else False
        if fingerprint is not None:
            checks.append(f"fingerprint  {fingerprint.reason}")

        # Before every skip branch below, including the status-guard one. A
        # refusal that could be reached by falling through to SKIP_FRESH — or
        # short-circuited by a status guard saying "already done" — would be
        # the exact false-clean this is here to prevent: a stage certifying
        # success having verified nothing.
        if fingerprint is not None and fingerprint.refused:
            return GuardVerdict(GuardState.REFUSED, fingerprint.reason, tuple(checks))

        if satisfied:
            # R10a: status ANDs with file staleness where a file signal exists.
            if has_file_signal and not fresh:
                checks.append("status satisfied, but sources changed → running (R10a)")
                return GuardVerdict(
                    GuardState.RUN,
                    "sources changed since last run (status guard does not override)",
                    tuple(checks),
                )
            return GuardVerdict(
                GuardState.SKIP_SATISFIED, "status guards satisfied", tuple(checks)
            )

        if fresh:
            return GuardVerdict(
                GuardState.SKIP_FRESH,
                fingerprint.reason if fingerprint else "up to date",
                tuple(checks),
            )

        reason = (
            fingerprint.reason
            if fingerprint is not None and not fingerprint.up_to_date
            else "no guard skipped this job"
        )
        return GuardVerdict(GuardState.RUN, reason, tuple(checks))

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------

    def _check_platforms(
        self, platforms: Sequence[str] | None, checks: list[str]
    ) -> GuardVerdict | None:
        if not platforms:
            return None
        if self._platform in platforms:
            checks.append(f"platforms  {self._platform} ✓")
            return None
        checks.append(
            f"platforms  {self._platform} ✗ (allowed: {', '.join(platforms)})"
        )
        return GuardVerdict(
            GuardState.SKIP_NEUTRAL,
            f"not applicable on {self._platform}",
            tuple(checks),
        )

    def _check_preconditions(
        self, preconditions: Sequence[Any], config: Any, checks: list[str]
    ) -> GuardVerdict | None:
        for item in preconditions:
            check = item.cmd_or_callable if isinstance(item, Precondition) else item
            message = item.msg if isinstance(item, Precondition) else None
            key = guard_key(check)

            cached = self._cache.get(key)
            if cached is None:
                passed = self._run_check(check, config)
                self._cache.set(key, passed)
                suffix = ""
            else:
                passed = cached
                suffix = " (cached this session)"

            checks.append(f"preconditions  {key} {'✓' if passed else '✗'}{suffix}")
            if not passed:
                return GuardVerdict(
                    GuardState.ERROR,
                    message or f"precondition failed: {key}",
                    tuple(checks),
                )
        return None

    def _status_satisfied(
        self, status: Sequence[Any], config: Any, checks: list[str]
    ) -> bool:
        if not status:
            return False
        for check in status:
            passed = self._run_check(check, config)
            checks.append(f"status  {guard_key(check)} {'✓' if passed else '✗'}")
            if not passed:
                return False
        return True

    def _run_check(self, check: Any, config: Any) -> bool:
        """Run one guard: shell string via the runner, callable with the config.

        A callable that raises counts as *not satisfied* rather than crashing
        the run — a guard is a question, and an exception is a "no".
        """
        if isinstance(check, str):
            if self._shell_runner is None:
                return False
            try:
                return bool(self._shell_runner(check))
            except Exception:
                return False
        try:
            return bool(_call_guard(check, config))
        except Exception:
            return False


def _call_guard(check: Callable[..., Any], config: Any) -> Any:
    """Call a guard callable in either supported form: ``f(config)`` or ``f()``.

    Arity is decided by inspecting the signature, never by catching TypeError
    from the call — that would silently swallow a TypeError raised *inside* the
    guard body and retry it with no arguments.
    """
    import inspect

    try:
        parameters = inspect.signature(check).parameters
    except (TypeError, ValueError):
        return check(config)  # builtin/C callable — assume the documented form
    return check() if len(parameters) == 0 else check(config)
