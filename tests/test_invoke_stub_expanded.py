"""Tests for the expanded Invoke stub in functualize.job._invoke.

Validates the new parameters, validation logic, and method signatures
added in Phase 1 (task 2.1) to the type-contract Invoke class.
"""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import BaseModel

from functualize._engine.errors import JobNotFoundError
from functualize.job._invoke import Invoke, InvokeResult


class SampleConfig(BaseModel):
    name: str = "default"
    count: int = 10


class TestInvokeCallSignature:
    """Test expanded __call__ signature with new parameters."""

    def test_string_job_name_reaches_not_implemented(self) -> None:
        """String job_or_fn bypasses function resolution and hits NotImplementedError."""
        inv = Invoke()
        with pytest.raises(NotImplementedError):
            inv("my_job")

    def test_callable_raises_job_not_found_error(self) -> None:
        """Unregistered callable raises JobNotFoundError."""
        inv = Invoke()

        def unregistered_fn():
            pass

        with pytest.raises(JobNotFoundError):
            inv(unregistered_fn)

    def test_config_kwarg_mutual_exclusivity(self) -> None:
        """Passing both config and kwargs raises ValueError."""
        inv = Invoke()
        with pytest.raises(ValueError, match="Cannot pass both"):
            inv("my_job", config=SampleConfig(), extra_arg="value")

    def test_config_only_passes_validation(self) -> None:
        """Config without kwargs passes the exclusivity check."""
        inv = Invoke()
        # Should get NotImplementedError (not ValueError)
        with pytest.raises(NotImplementedError):
            inv("my_job", config=SampleConfig())

    def test_kwargs_only_passes_validation(self) -> None:
        """kwargs without config passes the exclusivity check."""
        inv = Invoke()
        with pytest.raises(NotImplementedError):
            inv("my_job", name="test", count=5)

    def test_available_tools_max_64_validation(self) -> None:
        """available_tools with > 64 entries raises ValueError."""
        inv = Invoke()
        tools = [f"tool_{i}" for i in range(65)]
        with pytest.raises(ValueError, match="at most 64 entries"):
            inv("my_job", available_tools=tools)

    def test_available_tools_at_64_passes_validation(self) -> None:
        """available_tools with exactly 64 entries passes the check."""
        inv = Invoke()
        tools = [f"tool_{i}" for i in range(64)]
        # Should get NotImplementedError (not ValueError on count)
        with pytest.raises(NotImplementedError):
            inv("my_job", available_tools=tools)

    def test_available_tools_empty_passes_validation(self) -> None:
        """available_tools as empty list passes validation."""
        inv = Invoke()
        with pytest.raises(NotImplementedError):
            inv("my_job", available_tools=[])

    def test_all_new_parameters_accepted(self) -> None:
        """All new parameters are accepted without TypeError."""
        inv = Invoke()
        with pytest.raises(NotImplementedError):
            inv(
                "my_job",
                config=SampleConfig(),
                awaits_input=SampleConfig,
                available_tools=["tool1"],
                force_gate=True,
                gate_strategy="resolve",
                timeout=30.0,
            )


class TestInvokeParallel:
    """Test Invoke.parallel method."""

    def test_parallel_raises_value_error_over_32(self) -> None:
        """More than 32 jobs raises ValueError."""
        inv = Invoke()
        jobs = [("job", {}) for _ in range(33)]
        with pytest.raises(ValueError, match="at most 32 jobs"):
            inv.parallel(jobs)

    def test_parallel_32_jobs_reaches_not_implemented(self) -> None:
        """32 jobs passes validation."""
        inv = Invoke()
        jobs = [("job", {}) for _ in range(32)]
        with pytest.raises(NotImplementedError):
            inv.parallel(jobs)

    def test_parallel_1_job_reaches_not_implemented(self) -> None:
        """1 job passes validation."""
        inv = Invoke()
        with pytest.raises(NotImplementedError):
            inv.parallel([("job", {})])

    def test_parallel_accepts_callable_in_tuples(self) -> None:
        """parallel accepts callables in the job tuples."""
        inv = Invoke()

        def my_fn():
            pass

        with pytest.raises(NotImplementedError):
            inv.parallel([(my_fn, {})])


class TestInvokeSchema:
    """Test Invoke.schema method."""

    def test_schema_with_string_raises_not_implemented(self) -> None:
        """schema with string job name raises NotImplementedError."""
        inv = Invoke()
        with pytest.raises(NotImplementedError):
            inv.schema("my_job")

    def test_schema_with_callable_raises_not_implemented(self) -> None:
        """schema with callable raises NotImplementedError."""
        inv = Invoke()

        def my_fn():
            pass

        with pytest.raises(NotImplementedError):
            inv.schema(my_fn)


class TestInvokeResult:
    """Test InvokeResult dataclass."""

    def test_invoke_result_creation(self) -> None:
        """InvokeResult can be created with all fields."""
        result = InvokeResult(
            success=True,
            return_value="hello",
            exception=None,
            metadata={"key": "val"},
        )
        assert result.success is True
        assert result.return_value == "hello"
        assert result.exception is None
        assert result.metadata == {"key": "val"}

    def test_invoke_result_defaults(self) -> None:
        """InvokeResult has sensible defaults."""
        result = InvokeResult(success=False)
        assert result.return_value is None
        assert result.exception is None
        assert result.metadata == {}

    def test_invoke_result_is_frozen(self) -> None:
        """InvokeResult is immutable (frozen dataclass)."""
        result = InvokeResult(success=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.success = False  # type: ignore[misc]
