"""Tests for error types in the Phase 1 API surface.

Validates:
- RecursionLimitError stores depth, max_depth, job_name (Requirement 3.7)
- GateResolutionError stores gate_name, strategies_attempted, last_error (Requirement 7.10)
- JobNotFoundError accepts str | Callable (Requirement 1.2)
- AmbiguousJobError stores name and candidates, message format (Requirement 12)
"""

from __future__ import annotations

from functualize._engine.errors import JobNotFoundError
from functualize._types.errors import (
    AmbiguousJobError,
    GateResolutionError,
    RecursionLimitError,
)


class TestRecursionLimitError:
    """Tests for RecursionLimitError in _types/errors.py."""

    def test_stores_depth(self) -> None:
        err = RecursionLimitError(depth=5, max_depth=10, job_name="my_job")
        assert err.depth == 5

    def test_stores_max_depth(self) -> None:
        err = RecursionLimitError(depth=5, max_depth=10, job_name="my_job")
        assert err.max_depth == 10

    def test_stores_job_name(self) -> None:
        err = RecursionLimitError(depth=5, max_depth=10, job_name="my_job")
        assert err.job_name == "my_job"

    def test_message_contains_context(self) -> None:
        err = RecursionLimitError(depth=3, max_depth=5, job_name="nested_job")
        msg = str(err)
        assert "3" in msg
        assert "5" in msg
        assert "nested_job" in msg

    def test_is_exception(self) -> None:
        err = RecursionLimitError(depth=1, max_depth=2, job_name="x")
        assert isinstance(err, Exception)


class TestGateResolutionError:
    """Tests for GateResolutionError in _types/errors.py."""

    def test_stores_gate_name(self) -> None:
        err = GateResolutionError(
            gate_name="input_gate",
            strategies_attempted=3,
            last_error="timeout",
        )
        assert err.gate_name == "input_gate"

    def test_stores_strategies_attempted(self) -> None:
        err = GateResolutionError(
            gate_name="input_gate",
            strategies_attempted=3,
            last_error="timeout",
        )
        assert err.strategies_attempted == 3

    def test_stores_last_error(self) -> None:
        err = GateResolutionError(
            gate_name="input_gate",
            strategies_attempted=3,
            last_error="timeout",
        )
        assert err.last_error == "timeout"

    def test_message_contains_context(self) -> None:
        err = GateResolutionError(
            gate_name="approval_gate",
            strategies_attempted=2,
            last_error="connection refused",
        )
        msg = str(err)
        assert "approval_gate" in msg
        assert "2" in msg
        assert "connection refused" in msg

    def test_is_exception(self) -> None:
        err = GateResolutionError(gate_name="g", strategies_attempted=1, last_error="e")
        assert isinstance(err, Exception)


class TestJobNotFoundError:
    """Tests for JobNotFoundError in _engine/errors.py."""

    def test_accepts_string(self) -> None:
        err = JobNotFoundError("my_job")
        assert err.fn_or_name == "my_job"
        assert "my_job" in str(err)

    def test_accepts_callable(self) -> None:
        def some_function() -> None:
            pass

        err = JobNotFoundError(some_function)
        assert err.fn_or_name is some_function
        assert "some_function" in str(err)

    def test_callable_message_mentions_registry(self) -> None:
        def my_func() -> None:
            pass

        err = JobNotFoundError(my_func)
        assert "not registered" in str(err)

    def test_string_message_mentions_job(self) -> None:
        err = JobNotFoundError("deploy_service")
        assert "not registered" in str(err)

    def test_is_exception(self) -> None:
        err = JobNotFoundError("x")
        assert isinstance(err, Exception)

    def test_lambda_callable(self) -> None:
        fn = lambda: None  # noqa: E731
        err = JobNotFoundError(fn)
        assert err.fn_or_name is fn
        # Lambda should still produce a meaningful message
        assert "not registered" in str(err)


class TestAmbiguousJobError:
    """Tests for AmbiguousJobError in _types/errors.py.

    Validates: Requirements 12
    """

    def test_construction_stores_name(self) -> None:
        err = AmbiguousJobError(
            name="provision",
            candidates=["infra.provision", "deploy.provision"],
        )
        assert err.name == "provision"

    def test_construction_stores_candidates(self) -> None:
        err = AmbiguousJobError(
            name="provision",
            candidates=["infra.provision", "deploy.provision"],
        )
        assert err.candidates == ["infra.provision", "deploy.provision"]

    def test_message_contains_ambiguous_name(self) -> None:
        err = AmbiguousJobError(
            name="provision",
            candidates=["infra.provision", "deploy.provision"],
        )
        assert "Ambiguous job name 'provision'" in str(err)

    def test_message_suggests_qualified_form(self) -> None:
        err = AmbiguousJobError(
            name="provision",
            candidates=["infra.provision", "deploy.provision"],
        )
        assert "Use the qualified form" in str(err)

    def test_message_contains_all_candidates(self) -> None:
        candidates = ["infra.provision", "deploy.provision"]
        err = AmbiguousJobError(name="provision", candidates=candidates)
        msg = str(err)
        for candidate in candidates:
            assert candidate in msg

    def test_is_exception(self) -> None:
        err = AmbiguousJobError(name="x", candidates=["a.x", "b.x"])
        assert isinstance(err, Exception)
