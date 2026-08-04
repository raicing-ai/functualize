"""Tests for the guard pipeline (S3/T18, §D.2 + §D.7b + companion R10a).

Covers the precedence order, the distinct skip states CI needs to tell apart,
the R10a AND-rule, and the session precondition cache.
"""

from __future__ import annotations

import pytest

from functualize._engine.guards import (
    GuardEvaluator,
    GuardState,
    PreconditionCache,
    guard_key,
)
from functualize._primitives.fingerprint import FingerprintVerdict
from functualize._types.job_declaration import Precondition

FRESH = FingerprintVerdict(True, "3 sources unchanged")
STALE = FingerprintVerdict(False, "1 changed (src/a.py) since last run", ("src/a.py",))


def _evaluator(shell_ok: bool = True, platform: str = "linux") -> GuardEvaluator:
    return GuardEvaluator(shell_runner=lambda _cmd: shell_ok, platform=platform)


class TestPlatforms:
    def test_match_proceeds(self) -> None:
        verdict = _evaluator().evaluate(platforms=["linux"])
        assert verdict.state is GuardState.RUN

    def test_mismatch_is_neutral_skip(self) -> None:
        verdict = _evaluator(platform="darwin").evaluate(platforms=["linux"])
        assert verdict.state is GuardState.SKIP_NEUTRAL
        assert "not applicable" in verdict.reason

    def test_none_means_anywhere(self) -> None:
        assert _evaluator(platform="sunos").evaluate(platforms=None).will_run

    def test_platforms_outrank_preconditions(self) -> None:
        # A platform mismatch must skip neutrally without even running the
        # precondition (which would ERROR).
        verdict = _evaluator(shell_ok=False, platform="darwin").evaluate(
            platforms=["linux"], preconditions=["docker --version"]
        )
        assert verdict.state is GuardState.SKIP_NEUTRAL


class TestPreconditions:
    def test_pass_proceeds(self) -> None:
        assert _evaluator(shell_ok=True).evaluate(preconditions=["true"]).will_run

    def test_failure_is_error_not_skip(self) -> None:
        verdict = _evaluator(shell_ok=False).evaluate(preconditions=["false"])
        assert verdict.state is GuardState.ERROR

    def test_custom_message_surfaces(self) -> None:
        verdict = _evaluator(shell_ok=False).evaluate(
            preconditions=[Precondition("docker --version", msg="Docker required")]
        )
        assert verdict.state is GuardState.ERROR
        assert verdict.reason == "Docker required"

    def test_callable_precondition(self) -> None:
        verdict = _evaluator().evaluate(
            preconditions=[lambda cfg: cfg["env"] in ("dev", "prod")],
            config={"env": "staging"},
        )
        assert verdict.state is GuardState.ERROR

    def test_zero_arg_callable_supported(self) -> None:
        assert _evaluator().evaluate(preconditions=[lambda: True]).will_run

    def test_raising_guard_counts_as_failure_not_crash(self) -> None:
        def boom(cfg):
            raise RuntimeError("nope")

        verdict = _evaluator().evaluate(preconditions=[boom])
        assert verdict.state is GuardState.ERROR

    def test_internal_typeerror_is_not_retried_as_zero_arg(self) -> None:
        calls: list[int] = []

        def guard(cfg):
            calls.append(1)
            raise TypeError("raised inside the body, not an arity problem")

        verdict = _evaluator().evaluate(preconditions=[guard], config={})
        assert verdict.state is GuardState.ERROR
        assert len(calls) == 1  # called once, never retried with no args

    def test_precondition_outranks_status(self) -> None:
        # Environment wrong → ERROR, even though status says "already done".
        evaluator = GuardEvaluator(shell_runner=lambda cmd: cmd != "docker --version")
        verdict = evaluator.evaluate(
            preconditions=["docker --version"], status=["test -f dist/app.whl"]
        )
        assert verdict.state is GuardState.ERROR


class TestSessionCache:
    def test_precondition_runs_once_per_session(self) -> None:
        runs: list[str] = []
        evaluator = GuardEvaluator(
            shell_runner=lambda cmd: (runs.append(cmd), True)[1],
            cache=PreconditionCache(),
        )
        evaluator.evaluate(preconditions=["docker --version"])
        evaluator.evaluate(preconditions=["docker --version"])
        assert runs == ["docker --version"]  # second job reused the cache

    def test_cached_result_is_marked_in_the_trace(self) -> None:
        evaluator = _evaluator()
        evaluator.evaluate(preconditions=["docker --version"])
        verdict = evaluator.evaluate(preconditions=["docker --version"])
        assert any("cached this session" in line for line in verdict.checks)

    def test_cached_failure_still_errors(self) -> None:
        evaluator = _evaluator(shell_ok=False)
        evaluator.evaluate(preconditions=["docker --version"])
        assert evaluator.evaluate(preconditions=["docker --version"]).state is (
            GuardState.ERROR
        )

    def test_cache_backed_by_state_store(self, tmp_path) -> None:
        from functualize._primitives.state_store import StateStore

        store = StateStore(tmp_path / "state.json")
        cache = PreconditionCache(store)
        cache.set("docker --version", True)
        assert cache.get("docker --version") is True
        # Survives a fresh cache over the same store (session scope).
        assert PreconditionCache(store).get("docker --version") is True

    def test_distinct_callables_get_distinct_keys(self) -> None:
        assert guard_key(lambda: True) != guard_key("some command")


class TestStatusAndFreshness:
    def test_status_satisfied_skips(self) -> None:
        verdict = _evaluator(shell_ok=True).evaluate(status=["test -f dist/app.whl"])
        assert verdict.state is GuardState.SKIP_SATISFIED

    def test_status_unsatisfied_runs(self) -> None:
        verdict = _evaluator(shell_ok=False).evaluate(status=["test -f dist/app.whl"])
        assert verdict.state is GuardState.RUN

    def test_all_status_checks_must_pass(self) -> None:
        evaluator = GuardEvaluator(shell_runner=lambda cmd: cmd == "first")
        verdict = evaluator.evaluate(status=["first", "second"])
        assert verdict.state is GuardState.RUN

    def test_fresh_fingerprint_skips(self) -> None:
        verdict = _evaluator().evaluate(fingerprint=FRESH, has_file_signal=True)
        assert verdict.state is GuardState.SKIP_FRESH

    def test_stale_fingerprint_runs_with_reason(self) -> None:
        verdict = _evaluator().evaluate(fingerprint=STALE, has_file_signal=True)
        assert verdict.state is GuardState.RUN
        assert "src/a.py" in verdict.reason


class TestR10aAndRule:
    """A truthy status guard ANDs with file staleness — it never overrides it."""

    def test_satisfied_status_does_not_mask_changed_sources(self) -> None:
        verdict = _evaluator(shell_ok=True).evaluate(
            status=["test -f dist/app.whl"], fingerprint=STALE, has_file_signal=True
        )
        assert verdict.state is GuardState.RUN
        assert "does not override" in verdict.reason

    def test_satisfied_status_with_fresh_files_skips(self) -> None:
        verdict = _evaluator(shell_ok=True).evaluate(
            status=["test -f dist/app.whl"], fingerprint=FRESH, has_file_signal=True
        )
        assert verdict.state is GuardState.SKIP_SATISFIED

    def test_no_file_signal_lets_status_skip_alone(self) -> None:
        # method="none" or no declared sources: there is nothing to be stale
        # about, so ANDing would make status guards useless.
        verdict = _evaluator(shell_ok=True).evaluate(
            status=["test -f dist/app.whl"],
            fingerprint=FingerprintVerdict(
                False, "method=none — file checking disabled"
            ),
            has_file_signal=False,
        )
        assert verdict.state is GuardState.SKIP_SATISFIED

    def test_r10a_is_recorded_in_the_trace(self) -> None:
        verdict = _evaluator(shell_ok=True).evaluate(
            status=["ok"], fingerprint=STALE, has_file_signal=True
        )
        assert any("R10a" in line for line in verdict.checks)


class TestVerdictShape:
    def test_no_guards_runs(self) -> None:
        assert _evaluator().evaluate().will_run

    def test_checks_trace_is_ordered(self) -> None:
        verdict = _evaluator(shell_ok=True).evaluate(
            platforms=["linux"],
            preconditions=["docker --version"],
            status=["test -f x"],
            fingerprint=FRESH,
            has_file_signal=True,
        )
        kinds = [line.split()[0] for line in verdict.checks]
        assert kinds == ["platforms", "preconditions", "status", "fingerprint"]

    def test_skip_states_report_is_skip(self) -> None:
        assert GuardState.SKIP_NEUTRAL.is_skip
        assert GuardState.SKIP_SATISFIED.is_skip
        assert GuardState.SKIP_FRESH.is_skip
        assert not GuardState.RUN.is_skip
        assert not GuardState.ERROR.is_skip
        assert not GuardState.BLOCKED.is_skip

    def test_blocked_state_carries_awaiting_model(self) -> None:
        # §D.7b: BLOCKED joins the guard states, carrying the awaited model.
        from functualize._engine.guards import GuardVerdict

        class Approval:
            pass

        verdict = GuardVerdict(
            GuardState.BLOCKED, "awaiting approval", awaiting=Approval
        )
        assert verdict.state is GuardState.BLOCKED
        assert verdict.awaiting is Approval
        assert not verdict.will_run


class TestPreconditionsBeforeStatusOrdering:
    @pytest.mark.parametrize(
        ("platform", "shell_ok", "expected"),
        [
            ("darwin", True, GuardState.SKIP_NEUTRAL),  # platform wins
            ("linux", False, GuardState.ERROR),  # precondition wins over status
        ],
    )
    def test_precedence(self, platform, shell_ok, expected) -> None:
        verdict = GuardEvaluator(
            shell_runner=lambda _c: shell_ok, platform=platform
        ).evaluate(
            platforms=["linux"],
            preconditions=["docker --version"],
            status=["already-done"],
        )
        assert verdict.state is expected
