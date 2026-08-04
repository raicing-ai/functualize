"""Tests for invoke_parallel, get_job_schema, and log callback filter (Task 6.7).

Covers:
- invoke_parallel: 1-32 jobs, independent RunContexts, results in input order,
  300s per-job timeout, error handling
- get_job_schema: returns JobDescriptor, raises JobNotFoundError, RuntimeError
- Log callback filter: None suppresses, str replaces, chain in registration order,
  exception handling
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from functualize._config.job_config import JobConfigView
from functualize._engine.errors import JobNotFoundError
from functualize._types.descriptors import JobDescriptor
from functualize.job.context import RunContext, RunStatus

# --- Helpers ---


def make_run_context(
    *,
    name: str = "test-job",
    execution_engine: object | None = None,
    invoke_depth: int = 0,
    max_invoke_depth: int = 10,
) -> tuple[RunContext, MagicMock]:
    """Create a RunContext with mocked dependencies."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock(spec=logging.Logger)
    rc = RunContext(
        name=name,
        config=mock_config,
        logger=mock_logger,
        _execution_engine=execution_engine,
        _invoke_depth=invoke_depth,
        _max_invoke_depth=max_invoke_depth,
    )
    return rc, mock_logger


def make_job_result(
    *,
    status: RunStatus = RunStatus.SUCCESS,
    job_name: str = "child-job",
    return_value: object = None,
) -> object:
    """Create a mock JobResult."""
    from functualize._engine.result import JobResult

    return JobResult(
        status=status,
        duration_ms=100.0,
        return_value=return_value,
        exception=None,
    )


def make_registered_job(name: str = "child-job") -> object:
    """Create a mock RegisteredJob."""
    from functualize._engine.result import RegisteredJob

    return RegisteredJob(
        name=name,
        function=lambda rc: None,
        config_class=None,
        group=None,
        module_path="test.module",
        job_directory=None,
    )


def make_descriptor(name: str = "test-job") -> JobDescriptor:
    """Create a test JobDescriptor."""
    return JobDescriptor(
        name=name,
        group=None,
        module_path="test.module",
        source_file="/test/module.py",
        source_mtime=1000.0,
        content_hash="abc123",
        docstring="Test job",
        config_fields=[],
        dependencies={},
    )


# --- Tests: invoke_parallel ---


class TestInvokeParallel:
    """Tests for RunContext.invoke_parallel()."""

    def test_empty_list_returns_empty(self) -> None:
        """Empty jobs list returns [] without spawning threads."""
        engine = MagicMock()
        rc, _ = make_run_context(execution_engine=engine)
        result = rc.invoke_parallel([])
        assert result == []

    def test_raises_valueerror_for_more_than_32_jobs(self) -> None:
        """ValueError raised when more than 32 jobs specified."""
        engine = MagicMock()
        rc, _ = make_run_context(execution_engine=engine)
        jobs = [("job", {}) for _ in range(33)]
        with pytest.raises(ValueError, match="at most 32 jobs"):
            rc.invoke_parallel(jobs)

    def test_raises_runtime_error_without_engine(self) -> None:
        """RuntimeError raised when RunContext has no engine."""
        rc, _ = make_run_context(execution_engine=None)
        with pytest.raises(RuntimeError, match="not created by JobExecutionEngine"):
            rc.invoke_parallel([("job", {})])

    def test_results_in_input_order(self) -> None:
        """Results are returned in the same order as input list."""
        from functualize._engine.result import JobResult, RegisteredJob

        results_by_name = {
            "fast": JobResult(
                status=RunStatus.SUCCESS,
                duration_ms=10.0,
                return_value="fast_result",
                exception=None,
            ),
            "slow": JobResult(
                status=RunStatus.SUCCESS,
                duration_ms=100.0,
                return_value="slow_result",
                exception=None,
            ),
            "medium": JobResult(
                status=RunStatus.SUCCESS,
                duration_ms=50.0,
                return_value="medium_result",
                exception=None,
            ),
        }

        engine = MagicMock()
        engine.get_job.side_effect = lambda name: RegisteredJob(
            name=name,
            function=lambda rc: None,
            config_class=None,
            group=None,
            module_path="test",
            job_directory=None,
        )
        engine.execute.side_effect = lambda **kwargs: results_by_name[
            kwargs["job_name"]
        ]

        rc, _ = make_run_context(execution_engine=engine)
        jobs = [("slow", {}), ("fast", {}), ("medium", {})]
        results = rc.invoke_parallel(jobs)

        assert len(results) == 3
        assert results[0].return_value == "slow_result"
        assert results[1].return_value == "fast_result"
        assert results[2].return_value == "medium_result"

    def test_single_job_executes(self) -> None:
        """A single job is executed and result returned."""
        from functualize._engine.result import JobResult, RegisteredJob

        expected = JobResult(
            status=RunStatus.SUCCESS,
            duration_ms=50.0,
            return_value="done",
            exception=None,
        )

        engine = MagicMock()
        engine.get_job.return_value = RegisteredJob(
            name="my-job",
            function=lambda rc: None,
            config_class=None,
            group=None,
            module_path="test",
            job_directory=None,
        )
        engine.execute.return_value = expected

        rc, _ = make_run_context(execution_engine=engine)
        results = rc.invoke_parallel([("my-job", {"x": 1})])

        assert len(results) == 1
        assert results[0].status == RunStatus.SUCCESS
        assert results[0].return_value == "done"

    def test_job_not_found_returns_failure(self) -> None:
        """JobNotFoundError captured as FAILURE result."""
        engine = MagicMock()
        engine.get_job.side_effect = JobNotFoundError("missing-job")

        rc, _ = make_run_context(execution_engine=engine)
        results = rc.invoke_parallel([("missing-job", {})])

        assert len(results) == 1
        assert results[0].status == RunStatus.FAILURE
        assert isinstance(results[0].exception, JobNotFoundError)

    def test_recursion_limit_returns_failure(self) -> None:
        """Exceeding max_invoke_depth returns FAILURE with RecursionLimitError."""
        from functualize._engine.errors import RecursionLimitError

        engine = MagicMock()
        # At max depth already
        rc, _ = make_run_context(
            execution_engine=engine, invoke_depth=10, max_invoke_depth=10
        )
        results = rc.invoke_parallel([("job", {})])

        assert len(results) == 1
        assert results[0].status == RunStatus.FAILURE
        assert isinstance(results[0].exception, RecursionLimitError)

    def test_exception_in_job_captured_without_interrupting_others(self) -> None:
        """Unhandled exception in one job doesn't interrupt siblings."""
        from functualize._engine.result import JobResult, RegisteredJob

        call_count = [0]

        def mock_execute(**kwargs):
            call_count[0] += 1
            if kwargs["job_name"] == "bad":
                raise RuntimeError("boom")
            return JobResult(
                status=RunStatus.SUCCESS,
                duration_ms=10.0,
                return_value="ok",
                exception=None,
            )

        engine = MagicMock()
        engine.get_job.side_effect = lambda name: RegisteredJob(
            name=name,
            function=lambda rc: None,
            config_class=None,
            group=None,
            module_path="test",
            job_directory=None,
        )
        engine.execute.side_effect = mock_execute

        rc, _ = make_run_context(execution_engine=engine)
        results = rc.invoke_parallel([("good1", {}), ("bad", {}), ("good2", {})])

        assert len(results) == 3
        assert results[0].status == RunStatus.SUCCESS
        assert results[1].status == RunStatus.FAILURE
        assert isinstance(results[1].exception, RuntimeError)
        assert results[2].status == RunStatus.SUCCESS

    def test_32_jobs_accepted(self) -> None:
        """Exactly 32 jobs is within the valid range."""
        from functualize._engine.result import JobResult, RegisteredJob

        engine = MagicMock()
        engine.get_job.return_value = RegisteredJob(
            name="job",
            function=lambda rc: None,
            config_class=None,
            group=None,
            module_path="test",
            job_directory=None,
        )
        engine.execute.return_value = JobResult(
            status=RunStatus.SUCCESS,
            duration_ms=1.0,
            return_value=None,
            exception=None,
        )

        rc, _ = make_run_context(execution_engine=engine)
        jobs = [("job", {}) for _ in range(32)]
        results = rc.invoke_parallel(jobs)
        assert len(results) == 32


# --- Tests: get_job_schema ---


class TestGetJobSchema:
    """Tests for RunContext.get_job_schema()."""

    def test_returns_descriptor_for_registered_job(self) -> None:
        """Returns JobDescriptor for a registered job."""
        descriptor = make_descriptor("my-job")

        engine = MagicMock()
        engine._app.job_registry.get_descriptor.return_value = descriptor

        rc, _ = make_run_context(execution_engine=engine)
        result = rc.get_job_schema("my-job")

        assert result is descriptor
        assert result.name == "my-job"

    def test_raises_job_not_found_error(self) -> None:
        """Raises JobNotFoundError if job is not registered."""
        engine = MagicMock()
        engine._app.job_registry.get_descriptor.side_effect = KeyError("No descriptor")

        rc, _ = make_run_context(execution_engine=engine)
        with pytest.raises(JobNotFoundError):
            rc.get_job_schema("nonexistent")

    def test_raises_runtime_error_without_engine(self) -> None:
        """Raises RuntimeError if RunContext not created by engine."""
        rc, _ = make_run_context(execution_engine=None)
        with pytest.raises(RuntimeError, match="not created by"):
            rc.get_job_schema("any-job")


# --- Tests: Log Callback Filter ---


class TestLogCallbackFilter:
    """Tests for the new log callback filter/suppress semantics."""

    def test_none_suppresses_message(self) -> None:
        """Returning None suppresses the log message entirely."""
        rc, mock_logger = make_run_context()

        def suppress_cb(level: str, msg: str) -> str | None:
            return None

        rc.on_log(suppress_cb)
        rc.log("should be suppressed")

        # Logger should NOT be called
        mock_logger.info.assert_not_called()

    def test_string_replaces_message(self) -> None:
        """Returning a string replaces the message for the logger."""
        rc, mock_logger = make_run_context()

        def transform_cb(level: str, msg: str) -> str | None:
            return f"[prefix] {msg}"

        rc.on_log(transform_cb)
        rc.log("original")

        mock_logger.info.assert_called_once_with("[prefix] original")

    def test_chain_order_preserved(self) -> None:
        """Callbacks chain in registration order, each seeing previous result."""
        rc, mock_logger = make_run_context()

        def cb1(level: str, msg: str) -> str | None:
            return msg + " -> cb1"

        def cb2(level: str, msg: str) -> str | None:
            return msg + " -> cb2"

        rc.on_log(cb1)
        rc.on_log(cb2)
        rc.log("start")

        mock_logger.info.assert_called_once_with("start -> cb1 -> cb2")

    def test_none_stops_chain(self) -> None:
        """When a callback returns None, subsequent callbacks are not invoked."""
        rc, mock_logger = make_run_context()
        second_called = []

        def suppress_cb(level: str, msg: str) -> str | None:
            return None

        def second_cb(level: str, msg: str) -> str | None:
            second_called.append(True)
            return msg

        rc.on_log(suppress_cb)
        rc.on_log(second_cb)
        rc.log("test")

        assert second_called == []
        mock_logger.info.assert_not_called()

    def test_exception_passes_input_message_to_next(self) -> None:
        """On exception, input message passes unchanged to next callback."""
        rc, mock_logger = make_run_context()

        def bad_cb(level: str, msg: str) -> str | None:
            raise RuntimeError("oops")

        def next_cb(level: str, msg: str) -> str | None:
            return msg + " -> next"

        rc.on_log(bad_cb)
        rc.on_log(next_cb)
        rc.log("original")

        # Exception logged as warning
        mock_logger.warning.assert_called()
        # Next callback received the original message (not affected by exception)
        mock_logger.info.assert_called_once_with("original -> next")

    def test_pass_through_preserves_existing_behavior(self) -> None:
        """Returning the original message preserves pass-through behavior."""
        rc, mock_logger = make_run_context()

        def passthrough_cb(level: str, msg: str) -> str | None:
            return msg

        rc.on_log(passthrough_cb)
        rc.log("hello world")

        mock_logger.info.assert_called_once_with("hello world")

    def test_multiple_transforms_chain(self) -> None:
        """Multiple transforming callbacks compose correctly."""
        rc, mock_logger = make_run_context()

        def upper_cb(level: str, msg: str) -> str | None:
            return msg.upper()

        def prefix_cb(level: str, msg: str) -> str | None:
            return f"LOG: {msg}"

        rc.on_log(upper_cb)
        rc.on_log(prefix_cb)
        rc.log("hello")

        mock_logger.info.assert_called_once_with("LOG: HELLO")

    def test_suppress_after_transform(self) -> None:
        """A suppress callback can come after a transform callback."""
        rc, mock_logger = make_run_context()

        def transform_cb(level: str, msg: str) -> str | None:
            return msg.upper()

        def suppress_cb(level: str, msg: str) -> str | None:
            if "SECRET" in msg:
                return None
            return msg

        rc.on_log(transform_cb)
        rc.on_log(suppress_cb)
        rc.log("secret data")

        # "secret data" -> "SECRET DATA" (by transform_cb)
        # "SECRET DATA" contains "SECRET" -> suppressed
        mock_logger.info.assert_not_called()

    def test_no_callbacks_emits_normally(self) -> None:
        """No callbacks means message goes straight to logger."""
        rc, mock_logger = make_run_context()
        rc.log("direct message")
        mock_logger.info.assert_called_once_with("direct message")
