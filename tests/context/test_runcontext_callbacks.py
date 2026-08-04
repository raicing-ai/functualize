"""Unit tests for RunContext callback registration and invocation.

Tests task 6.9 additions:
- on_status_change(callback) registration and invocation
- on_phase_change(callback) registration and invocation
- on_log(callback) registration and invocation
- Callbacks invoked in registration order
- Callback exceptions logged at WARNING, never prevent the underlying operation
"""

import logging
from unittest.mock import MagicMock

import pytest

from functualize._config.job_config import JobConfigView
from functualize.job.context import (
    JobPhase,
    RunContext,
    RunStatus,
)


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock JobConfigView instance."""
    return MagicMock(spec=JobConfigView)


@pytest.fixture
def mock_logger() -> MagicMock:
    """Create a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def rc(mock_config: MagicMock, mock_logger: MagicMock) -> RunContext:
    """Create a RunContext instance for testing."""
    return RunContext(name="test-job", config=mock_config, logger=mock_logger)


class TestOnStatusChange:
    """Tests for on_status_change callback registration and invocation."""

    def test_registers_callback(self, rc: RunContext) -> None:
        """on_status_change adds callback to the list."""
        cb = MagicMock()
        rc.on_status_change(cb)
        assert rc._status_callbacks is not None
        assert cb in rc._status_callbacks

    def test_callback_invoked_on_set_run_status(self, rc: RunContext) -> None:
        """Registered callback is invoked when set_run_status is called."""
        cb = MagicMock()
        rc.on_status_change(cb)
        rc.set_run_status(RunStatus.SUCCESS, "done")
        cb.assert_called_once_with(RunStatus.RUNNING, RunStatus.SUCCESS, "done")

    def test_multiple_callbacks_invoked_in_order(self, rc: RunContext) -> None:
        """Multiple callbacks are invoked in registration order."""
        calls: list[int] = []
        rc.on_status_change(lambda old, new, msg: calls.append(1))
        rc.on_status_change(lambda old, new, msg: calls.append(2))
        rc.on_status_change(lambda old, new, msg: calls.append(3))
        rc.set_run_status(RunStatus.SUCCESS)
        assert calls == [1, 2, 3]

    def test_callback_exception_logged_at_warning(
        self, rc: RunContext, mock_logger: MagicMock
    ) -> None:
        """Callback exception is logged at WARNING level."""

        def bad_cb(old: RunStatus, new: RunStatus, msg: str) -> None:
            raise ValueError("boom")

        rc.on_status_change(bad_cb)
        rc.set_run_status(RunStatus.SUCCESS)
        mock_logger.warning.assert_called()
        # Exception is logged with exc_info=True, callback reference is in message
        assert mock_logger.warning.call_args is not None

    def test_callback_exception_does_not_prevent_transition(
        self, rc: RunContext
    ) -> None:
        """Callback exception doesn't prevent the status transition."""

        def bad_cb(old: RunStatus, new: RunStatus, msg: str) -> None:
            raise RuntimeError("explode")

        rc.on_status_change(bad_cb)
        rc.set_run_status(RunStatus.SUCCESS)
        assert rc.run_status == RunStatus.SUCCESS

    def test_callback_exception_does_not_prevent_other_callbacks(
        self, rc: RunContext
    ) -> None:
        """A failing callback doesn't prevent subsequent callbacks from running."""
        second_cb = MagicMock()

        def bad_cb(old: RunStatus, new: RunStatus, msg: str) -> None:
            raise ValueError("first fails")

        rc.on_status_change(bad_cb)
        rc.on_status_change(second_cb)
        rc.set_run_status(RunStatus.SUCCESS)
        second_cb.assert_called_once()

    def test_no_callbacks_registered_no_error(self, rc: RunContext) -> None:
        """set_run_status works fine when no callbacks registered."""
        rc.set_run_status(RunStatus.SUCCESS)
        assert rc.run_status == RunStatus.SUCCESS

    def test_callback_receives_correct_old_and_new_status(self, rc: RunContext) -> None:
        """Callback receives correct old and new status values."""
        received: list[tuple[RunStatus, RunStatus, str]] = []
        rc.on_status_change(lambda old, new, msg: received.append((old, new, msg)))
        rc.set_run_status(RunStatus.SUCCESS, "all good")
        assert received == [(RunStatus.RUNNING, RunStatus.SUCCESS, "all good")]


class TestOnJobPhaseChange:
    """Tests for on_phase_change callback registration and invocation."""

    def test_registers_callback(self, rc: RunContext) -> None:
        """on_phase_change adds callback to the list."""
        cb = MagicMock()
        rc.on_phase_change(cb)
        assert rc._phase_callbacks is not None
        assert cb in rc._phase_callbacks

    def test_callback_invoked_on_new_step(self, rc: RunContext) -> None:
        """Callback invoked with action='created' on new step."""
        cb = MagicMock()
        rc.on_phase_change(cb)
        rc.track_phase("deploy", "deploying", RunStatus.RUNNING)
        cb.assert_called_once()
        step_arg, action_arg = cb.call_args[0]
        assert step_arg["name"] == "deploy"
        assert action_arg == "created"

    def test_callback_invoked_on_updated_step(self, rc: RunContext) -> None:
        """Callback invoked with action='updated' on existing step update."""
        cb = MagicMock()
        rc.on_phase_change(cb)
        rc.track_phase("build", "building", RunStatus.RUNNING)
        rc.track_phase("build", "done", RunStatus.SUCCESS)
        assert cb.call_count == 2
        # Second call should have action='updated'
        _, action_arg = cb.call_args_list[1][0]
        assert action_arg == "updated"

    def test_multiple_callbacks_invoked_in_order(self, rc: RunContext) -> None:
        """Multiple callbacks invoked in registration order."""
        calls: list[int] = []
        rc.on_phase_change(lambda step, action: calls.append(1))
        rc.on_phase_change(lambda step, action: calls.append(2))
        rc.on_phase_change(lambda step, action: calls.append(3))
        rc.track_phase("step1", "msg")
        assert calls == [1, 2, 3]

    def test_callback_exception_logged_at_warning(
        self, rc: RunContext, mock_logger: MagicMock
    ) -> None:
        """Callback exception logged at WARNING level."""

        def bad_cb(step: JobPhase, action: str) -> None:
            raise ValueError("step boom")

        rc.on_phase_change(bad_cb)
        rc.track_phase("deploy", "deploying")
        mock_logger.warning.assert_called()
        assert mock_logger.warning.call_args is not None

    def test_callback_exception_does_not_prevent_step_tracking(
        self, rc: RunContext
    ) -> None:
        """Callback exception doesn't prevent the step from being tracked."""

        def bad_cb(step: JobPhase, action: str) -> None:
            raise RuntimeError("explode")

        rc.on_phase_change(bad_cb)
        rc.track_phase("deploy", "deploying", RunStatus.RUNNING)
        assert rc.get_phase("deploy") is not None
        assert rc.get_phase("deploy")["status"] == RunStatus.RUNNING  # type: ignore[index]

    def test_callback_exception_does_not_prevent_other_callbacks(
        self, rc: RunContext
    ) -> None:
        """A failing callback doesn't prevent subsequent callbacks from running."""
        second_cb = MagicMock()

        def bad_cb(step: JobPhase, action: str) -> None:
            raise ValueError("first fails")

        rc.on_phase_change(bad_cb)
        rc.on_phase_change(second_cb)
        rc.track_phase("deploy", "deploying")
        second_cb.assert_called_once()

    def test_step_dict_passed_to_callback(self, rc: RunContext) -> None:
        """Callback receives the actual step dictionary."""
        received: list[tuple[JobPhase, str]] = []
        rc.on_phase_change(lambda step, action: received.append((step, action)))
        rc.track_phase("build", "building", RunStatus.RUNNING)
        step, action = received[0]
        assert step["name"] == "build"
        assert step["message"] == "building"
        assert step["status"] == RunStatus.RUNNING
        assert action == "created"

    def test_no_callbacks_registered_no_error(self, rc: RunContext) -> None:
        """track_phase works fine when no callbacks registered."""
        rc.track_phase("test", "testing")
        assert rc.get_phase("test") is not None


class TestOnLog:
    """Tests for on_log callback registration and invocation."""

    def test_registers_callback(self, rc: RunContext) -> None:
        """on_log adds callback to the list."""
        cb = MagicMock()
        rc.on_log(cb)
        assert rc._log_callbacks is not None
        assert cb in rc._log_callbacks

    def test_callback_invoked_before_log_emission(
        self, rc: RunContext, mock_logger: MagicMock
    ) -> None:
        """Log callback is invoked before the message is emitted to logger."""
        invocation_order: list[str] = []
        mock_logger.info.side_effect = lambda msg: invocation_order.append("logger")

        def log_cb(level: str, message: str) -> str | None:
            invocation_order.append("callback")
            return message  # pass through

        rc.on_log(log_cb)
        rc.log("hello")
        assert invocation_order == ["callback", "logger"]

    def test_callback_receives_level_and_message(self, rc: RunContext) -> None:
        """Log callback receives (level, message) arguments."""
        received: list[tuple[str, str]] = []

        def log_cb(level: str, msg: str) -> str | None:
            received.append((level, msg))
            return msg  # pass through

        rc.on_log(log_cb)
        rc.log("test message", level="warning")
        assert received == [("warning", "test message")]

    def test_multiple_callbacks_invoked_in_order(self, rc: RunContext) -> None:
        """Multiple log callbacks are invoked in registration order."""
        calls: list[int] = []

        def cb1(level: str, msg: str) -> str | None:
            calls.append(1)
            return msg

        def cb2(level: str, msg: str) -> str | None:
            calls.append(2)
            return msg

        def cb3(level: str, msg: str) -> str | None:
            calls.append(3)
            return msg

        rc.on_log(cb1)
        rc.on_log(cb2)
        rc.on_log(cb3)
        rc.log("hi")
        assert calls == [1, 2, 3]

    def test_callback_exception_logged_at_warning(
        self, rc: RunContext, mock_logger: MagicMock
    ) -> None:
        """Log callback exception is logged at WARNING level."""

        def bad_cb(level: str, message: str) -> None:
            raise ValueError("log boom")

        rc.on_log(bad_cb)
        rc.log("hello")
        mock_logger.warning.assert_called()
        assert mock_logger.warning.call_args is not None

    def test_callback_exception_does_not_prevent_log_emission(
        self, rc: RunContext, mock_logger: MagicMock
    ) -> None:
        """Callback exception doesn't prevent the log message from being emitted."""

        def bad_cb(level: str, message: str) -> None:
            raise RuntimeError("explode")

        rc.on_log(bad_cb)
        rc.log("important message")
        mock_logger.info.assert_called_with("important message")

    def test_callback_exception_does_not_prevent_other_callbacks(
        self, rc: RunContext
    ) -> None:
        """A failing callback doesn't prevent subsequent callbacks from running."""
        second_calls: list[str] = []

        def bad_cb(level: str, message: str) -> str | None:
            raise ValueError("first fails")

        def good_cb(level: str, message: str) -> str | None:
            second_calls.append(message)
            return message

        rc.on_log(bad_cb)
        rc.on_log(good_cb)
        rc.log("msg")
        assert second_calls == ["msg"]

    def test_message_converted_to_str_for_callback(self, rc: RunContext) -> None:
        """Non-string messages are converted to str for callbacks."""
        received: list[tuple[str, str]] = []

        def log_cb(level: str, msg: str) -> str | None:
            received.append((level, msg))
            return msg

        rc.on_log(log_cb)
        rc.log(42)
        assert received == [("info", "42")]

    def test_no_callbacks_registered_no_error(
        self, rc: RunContext, mock_logger: MagicMock
    ) -> None:
        """log() works fine when no callbacks registered."""
        rc.log("message")
        mock_logger.info.assert_called_with("message")

    def test_default_level_is_info(self, rc: RunContext) -> None:
        """Default log level passed to callback is 'info'."""
        received: list[tuple[str, str]] = []

        def log_cb(level: str, msg: str) -> str | None:
            received.append((level, msg))
            return msg

        rc.on_log(log_cb)
        rc.log("test")
        assert received[0][0] == "info"
