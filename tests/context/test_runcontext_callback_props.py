"""Property-based tests for Callback Error Isolation.

Property 21: Callback Error Isolation
Validates: Requirements 14.5

Tests that:
- A failing callback (raises Exception) does not prevent subsequent callbacks
  from being invoked
- A failing callback does not prevent the underlying operation (status change,
  step tracking, log emission)
- The exception from a failing callback is logged at WARNING level
- Multiple failing callbacks are all isolated — each failure is independently
  handled
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.job_config import JobConfigView
from functualize.job.context import (
    JobPhase,
    RunContext,
    RunStatus,
)

# --- Strategies ---

# Terminal statuses that can be transitioned to from RUNNING
terminal_statuses = st.sampled_from(
    [RunStatus.SUCCESS, RunStatus.FAILURE, RunStatus.CANCELLED, RunStatus.TIMEOUT]
)

# Number of callbacks to register (at least 2 to test isolation)
num_callbacks = st.integers(min_value=2, max_value=8)


# Positions within a callback list that will fail (indices are 0-based)
def failing_positions(n: int) -> st.SearchStrategy[list[int]]:
    """Generate a non-empty subset of positions that should fail."""
    return st.lists(
        st.integers(min_value=0, max_value=n - 1),
        min_size=1,
        max_size=n,
        unique=True,
    )


# Messages for log calls
log_messages = st.text(
    min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N"))
)

# Step names
step_names = st.text(
    min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))
)

# Error messages raised by callbacks
error_messages = st.text(
    min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N"))
)


# --- Helpers ---


def make_run_context() -> tuple[RunContext, MagicMock]:
    """Create a RunContext with mocked dependencies in RUNNING state."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock(spec=logging.Logger)
    rc = RunContext(name="test-job", config=mock_config, logger=mock_logger)
    return rc, mock_logger


# Feature: enriched-runcontext, Property 21: Callback Error Isolation
# **Validates: Requirements 14.5**
class TestStatusCallbackErrorIsolation:
    """A failing on_status_change callback does not prevent subsequent callbacks
    or the underlying status transition."""

    @given(
        n=num_callbacks,
        data=st.data(),
        target_status=terminal_statuses,
    )
    def test_failing_callback_does_not_prevent_subsequent_callbacks(
        self, n: int, data: st.DataObject, target_status: RunStatus
    ) -> None:
        """Subsequent callbacks fire even when earlier ones raise.

        **Validates: Requirements 14.5**
        """
        fail_positions = data.draw(failing_positions(n))
        rc, _ = make_run_context()

        invoked: list[int] = []

        for i in range(n):
            if i in fail_positions:

                def make_bad_cb(
                    idx: int,
                ) -> Callable[[RunStatus, RunStatus, str], None]:
                    def bad_cb(old: RunStatus, new: RunStatus, msg: str) -> None:
                        invoked.append(idx)
                        raise RuntimeError(f"callback {idx} failed")

                    return bad_cb

                rc.on_status_change(make_bad_cb(i))
            else:

                def make_good_cb(
                    idx: int,
                ) -> Callable[[RunStatus, RunStatus, str], None]:
                    def good_cb(old: RunStatus, new: RunStatus, msg: str) -> None:
                        invoked.append(idx)

                    return good_cb

                rc.on_status_change(make_good_cb(i))

        rc.set_run_status(target_status)

        # All callbacks should have been invoked regardless of failures
        assert invoked == list(range(n))

    @given(target_status=terminal_statuses)
    def test_failing_callback_does_not_prevent_status_transition(
        self, target_status: RunStatus
    ) -> None:
        """The underlying status transition completes even when a callback raises.

        **Validates: Requirements 14.5**
        """
        rc, _ = make_run_context()

        def bad_cb(old: RunStatus, new: RunStatus, msg: str) -> None:
            raise ValueError("explode")

        rc.on_status_change(bad_cb)
        rc.set_run_status(target_status)

        # Status transition happened despite callback failure
        assert rc.run_status == target_status

    @given(
        target_status=terminal_statuses,
        err_msg=error_messages,
    )
    def test_failing_callback_exception_logged_at_warning(
        self, target_status: RunStatus, err_msg: str
    ) -> None:
        """The exception from a failing callback is logged at WARNING level.

        **Validates: Requirements 14.5**
        """
        rc, mock_logger = make_run_context()

        def bad_cb(old: RunStatus, new: RunStatus, msg: str) -> None:
            raise ValueError(err_msg)

        rc.on_status_change(bad_cb)
        rc.set_run_status(target_status)

        mock_logger.warning.assert_called()
        # The implementation logs with exc_info=True, capturing exception in traceback
        call_kwargs = mock_logger.warning.call_args[1]
        assert call_kwargs.get("exc_info") is True

    @given(
        n=st.integers(min_value=2, max_value=5),
        target_status=terminal_statuses,
    )
    def test_multiple_failing_callbacks_all_isolated(
        self, n: int, target_status: RunStatus
    ) -> None:
        """Multiple failing callbacks are all independently handled.

        **Validates: Requirements 14.5**
        """
        rc, mock_logger = make_run_context()

        for i in range(n):

            def make_bad_cb(idx: int) -> Callable[[RunStatus, RunStatus, str], None]:
                def bad_cb(old: RunStatus, new: RunStatus, msg: str) -> None:
                    raise RuntimeError(f"fail-{idx}")

                return bad_cb

            rc.on_status_change(make_bad_cb(i))

        rc.set_run_status(target_status)

        # Status still transitioned
        assert rc.run_status == target_status
        # Each failure was logged
        assert mock_logger.warning.call_count == n


class TestStepCallbackErrorIsolation:
    """A failing on_phase_change callback does not prevent subsequent
    callbacks or the underlying step tracking."""

    @given(
        n=num_callbacks,
        data=st.data(),
        step_name=step_names,
    )
    def test_failing_callback_does_not_prevent_subsequent_callbacks(
        self, n: int, data: st.DataObject, step_name: str
    ) -> None:
        """Subsequent step callbacks fire even when earlier ones raise.

        **Validates: Requirements 14.5**
        """
        fail_positions = data.draw(failing_positions(n))
        rc, _ = make_run_context()

        invoked: list[int] = []

        for i in range(n):
            if i in fail_positions:

                def make_bad_cb(idx: int) -> Callable[[JobPhase, str], None]:
                    def bad_cb(step: JobPhase, action: str) -> None:
                        invoked.append(idx)
                        raise RuntimeError(f"step callback {idx} failed")

                    return bad_cb

                rc.on_phase_change(make_bad_cb(i))
            else:

                def make_good_cb(idx: int) -> Callable[[JobPhase, str], None]:
                    def good_cb(step: JobPhase, action: str) -> None:
                        invoked.append(idx)

                    return good_cb

                rc.on_phase_change(make_good_cb(i))

        rc.track_phase(step_name, "running", RunStatus.RUNNING)

        # All callbacks invoked in order
        assert invoked == list(range(n))

    @given(step_name=step_names)
    def test_failing_callback_does_not_prevent_step_tracking(
        self, step_name: str
    ) -> None:
        """The underlying step tracking completes even when a callback raises.

        **Validates: Requirements 14.5**
        """
        rc, _ = make_run_context()

        def bad_cb(step: JobPhase, action: str) -> None:
            raise ValueError("step explode")

        rc.on_phase_change(bad_cb)
        rc.track_phase(step_name, "running", RunStatus.RUNNING)

        # Step was tracked despite callback failure
        tracked = rc.get_phase(step_name)
        assert tracked is not None
        assert tracked["name"] == step_name
        assert tracked["status"] == RunStatus.RUNNING

    @given(
        step_name=step_names,
        err_msg=error_messages,
    )
    def test_failing_callback_exception_logged_at_warning(
        self, step_name: str, err_msg: str
    ) -> None:
        """The exception from a failing step callback is logged at WARNING level.

        **Validates: Requirements 14.5**
        """
        rc, mock_logger = make_run_context()

        def bad_cb(step: JobPhase, action: str) -> None:
            raise ValueError(err_msg)

        rc.on_phase_change(bad_cb)
        rc.track_phase(step_name, "running")

        mock_logger.warning.assert_called()
        # The implementation logs with exc_info=True, capturing exception in traceback
        call_kwargs = mock_logger.warning.call_args[1]
        assert call_kwargs.get("exc_info") is True

    @given(
        n=st.integers(min_value=2, max_value=5),
        step_name=step_names,
    )
    def test_multiple_failing_callbacks_all_isolated(
        self, n: int, step_name: str
    ) -> None:
        """Multiple failing step callbacks are all independently handled.

        **Validates: Requirements 14.5**
        """
        rc, mock_logger = make_run_context()

        for i in range(n):

            def make_bad_cb(idx: int) -> Callable[[JobPhase, str], None]:
                def bad_cb(step: JobPhase, action: str) -> None:
                    raise RuntimeError(f"step-fail-{idx}")

                return bad_cb

            rc.on_phase_change(make_bad_cb(i))

        rc.track_phase(step_name, "running", RunStatus.RUNNING)

        # Step still tracked
        assert rc.get_phase(step_name) is not None
        # Each failure was logged independently
        assert mock_logger.warning.call_count == n


class TestLogCallbackErrorIsolation:
    """A failing on_log callback does not prevent subsequent callbacks
    or the underlying log emission."""

    @given(
        n=num_callbacks,
        data=st.data(),
        message=log_messages,
    )
    def test_failing_callback_does_not_prevent_subsequent_callbacks(
        self, n: int, data: st.DataObject, message: str
    ) -> None:
        """Subsequent log callbacks fire even when earlier ones raise.

        **Validates: Requirements 14.5**
        """
        fail_positions = data.draw(failing_positions(n))
        rc, _ = make_run_context()

        invoked: list[int] = []

        for i in range(n):
            if i in fail_positions:

                def make_bad_cb(idx: int) -> Callable[[str, str], str | None]:
                    def bad_cb(level: str, msg: str) -> str | None:
                        invoked.append(idx)
                        raise RuntimeError(f"log callback {idx} failed")

                    return bad_cb

                rc.on_log(make_bad_cb(i))
            else:

                def make_good_cb(idx: int) -> Callable[[str, str], str | None]:
                    def good_cb(level: str, msg: str) -> str | None:
                        invoked.append(idx)
                        return msg  # pass through

                    return good_cb

                rc.on_log(make_good_cb(i))

        rc.log(message)

        # All callbacks invoked in order
        assert invoked == list(range(n))

    @given(message=log_messages)
    def test_failing_callback_does_not_prevent_log_emission(self, message: str) -> None:
        """The underlying log emission completes even when a callback raises.

        **Validates: Requirements 14.5**
        """
        rc, mock_logger = make_run_context()

        def bad_cb(level: str, msg: str) -> str | None:
            raise ValueError("log explode")

        rc.on_log(bad_cb)
        rc.log(message)

        # Log was emitted despite callback failure
        mock_logger.info.assert_called_with(message)

    @given(
        message=log_messages,
        err_msg=error_messages,
    )
    def test_failing_callback_exception_logged_at_warning(
        self, message: str, err_msg: str
    ) -> None:
        """The exception from a failing log callback is logged at WARNING level.

        **Validates: Requirements 14.5**
        """
        rc, mock_logger = make_run_context()

        def bad_cb(level: str, msg: str) -> str | None:
            raise ValueError(err_msg)

        rc.on_log(bad_cb)
        rc.log(message)

        mock_logger.warning.assert_called()
        # The implementation logs with exc_info=True, capturing exception in traceback
        call_kwargs = mock_logger.warning.call_args[1]
        assert call_kwargs.get("exc_info") is True

    @given(
        n=st.integers(min_value=2, max_value=5),
        message=log_messages,
    )
    def test_multiple_failing_callbacks_all_isolated(
        self, n: int, message: str
    ) -> None:
        """Multiple failing log callbacks are all independently handled.

        **Validates: Requirements 14.5**
        """
        rc, mock_logger = make_run_context()

        for i in range(n):

            def make_bad_cb(idx: int) -> Callable[[str, str], str | None]:
                def bad_cb(level: str, msg: str) -> str | None:
                    raise RuntimeError(f"log-fail-{idx}")

                return bad_cb

            rc.on_log(make_bad_cb(i))

        rc.log(message)

        # Log was still emitted
        mock_logger.info.assert_called_with(message)
        # Each failure was logged independently
        assert mock_logger.warning.call_count == n
