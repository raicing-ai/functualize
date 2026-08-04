"""Unit tests for execution pipeline wiring in app.py.

Tests how action_execute interacts with BarReadiness guard and _run_job,
and how action_autocomplete_toggle shows/hides the dropdown.

**Validates: Requirements 20.1, 20.2**
"""

from __future__ import annotations

from unittest.mock import MagicMock

from functualize._cli.tui.bar import BarReadiness

# =============================================================================
# Helpers — mock the minimal app attributes needed for testing
# =============================================================================


class MockSmartBar:
    """Minimal SmartBar mock for action_execute tests."""

    def __init__(
        self, readiness: BarReadiness = BarReadiness.GREY, value: str = ""
    ) -> None:
        self._readiness = readiness
        self.value = value

    @property
    def readiness(self) -> BarReadiness:
        return self._readiness


# =============================================================================
# Test 1: action_execute is no-op when BarReadiness is not READY
# =============================================================================


class TestActionExecuteNoOpWhenNotReady:
    """Req 20.1: action_execute is a no-op when readiness is not READY."""

    def test_execute_noop_when_grey(self) -> None:
        """action_execute returns early (no _run_job) when readiness is GREY."""
        app = MagicMock()
        app._smart_bar = MockSmartBar(readiness=BarReadiness.GREY, value="deploy")
        app._run_job = MagicMock()

        # Call the real action_execute logic (import and call unbound)
        from functualize._cli.tui.app import FunctualizeInlineTUI

        FunctualizeInlineTUI.action_execute(app)

        app._run_job.assert_not_called()

    def test_execute_noop_when_pending(self) -> None:
        """action_execute returns early when readiness is PENDING."""
        app = MagicMock()
        app._smart_bar = MockSmartBar(readiness=BarReadiness.PENDING, value="deploy")
        app._run_job = MagicMock()

        from functualize._cli.tui.app import FunctualizeInlineTUI

        FunctualizeInlineTUI.action_execute(app)

        app._run_job.assert_not_called()

    def test_execute_noop_when_editing(self) -> None:
        """action_execute returns early when readiness is EDITING."""
        app = MagicMock()
        app._smart_bar = MockSmartBar(readiness=BarReadiness.EDITING, value="us-west-2")
        app._run_job = MagicMock()

        from functualize._cli.tui.app import FunctualizeInlineTUI

        FunctualizeInlineTUI.action_execute(app)

        app._run_job.assert_not_called()

    def test_execute_noop_when_invalid(self) -> None:
        """action_execute returns early when readiness is INVALID."""
        app = MagicMock()
        app._smart_bar = MockSmartBar(readiness=BarReadiness.INVALID, value="bad-input")
        app._run_job = MagicMock()

        from functualize._cli.tui.app import FunctualizeInlineTUI

        FunctualizeInlineTUI.action_execute(app)

        app._run_job.assert_not_called()

    def test_execute_noop_for_all_non_ready_states(self) -> None:
        """action_execute is a no-op for every BarReadiness state except READY."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        non_ready_states = [
            BarReadiness.GREY,
            BarReadiness.PENDING,
            BarReadiness.EDITING,
            BarReadiness.INVALID,
        ]
        for state in non_ready_states:
            app = MagicMock()
            app._smart_bar = MockSmartBar(readiness=state, value="some-command")
            app._run_job = MagicMock()

            FunctualizeInlineTUI.action_execute(app)

            (
                app._run_job.assert_not_called(),
                f"_run_job should not be called for {state}",
            )


# =============================================================================
# Test 2: action_execute builds PendingExecution from tokens when READY
# =============================================================================


class TestActionExecuteCallsRunJobWhenReady:
    """Req 20.1: action_execute calls _run_job with tokens when readiness is READY."""

    def test_execute_calls_run_job_with_tokens(self) -> None:
        """action_execute tokenizes bar value and calls _run_job when READY."""
        app = MagicMock()
        app._smart_bar = MockSmartBar(
            readiness=BarReadiness.READY, value="deploy --region us-east-1"
        )
        app._run_job = MagicMock()

        from functualize._cli.tui.app import FunctualizeInlineTUI

        FunctualizeInlineTUI.action_execute(app)

        app._run_job.assert_called_once_with(["deploy", "--region", "us-east-1"])

    def test_execute_calls_run_job_single_token(self) -> None:
        """action_execute works with a single-token command (no args)."""
        app = MagicMock()
        app._smart_bar = MockSmartBar(readiness=BarReadiness.READY, value="status")
        app._run_job = MagicMock()

        from functualize._cli.tui.app import FunctualizeInlineTUI

        FunctualizeInlineTUI.action_execute(app)

        app._run_job.assert_called_once_with(["status"])

    def test_execute_noop_when_ready_but_empty(self) -> None:
        """action_execute is no-op if READY but bar value is empty/whitespace."""
        app = MagicMock()
        app._smart_bar = MockSmartBar(readiness=BarReadiness.READY, value="   ")
        app._run_job = MagicMock()

        from functualize._cli.tui.app import FunctualizeInlineTUI

        FunctualizeInlineTUI.action_execute(app)

        app._run_job.assert_not_called()


# =============================================================================
# Test 3: autocomplete toggle shows/hides the dropdown
# =============================================================================


class TestAutocompleteToggle:
    """Req 20.2: autocomplete toggle shows/hides the dropdown."""

    def test_toggle_hides_when_visible_with_options(self) -> None:
        """When autocomplete is visible with options, toggle hides it."""
        app = MagicMock()

        # Create a mock autocomplete widget that is visible with options
        mock_ac = MagicMock()
        mock_ac.display = True
        mock_ac.option_list.option_count = 3

        app.query_one = MagicMock(return_value=mock_ac)

        from functualize._cli.tui.app import FunctualizeInlineTUI

        FunctualizeInlineTUI.action_autocomplete_toggle(app)

        mock_ac.action_hide.assert_called_once()

    def test_toggle_shows_when_not_visible(self) -> None:
        """When autocomplete is not visible, toggle triggers a rebuild/show."""
        app = MagicMock()

        # Create a mock autocomplete widget that is not visible
        mock_ac = MagicMock()
        mock_ac.display = False
        mock_ac.option_list.option_count = 0

        app.query_one = MagicMock(return_value=mock_ac)

        from functualize._cli.tui.app import FunctualizeInlineTUI

        FunctualizeInlineTUI.action_autocomplete_toggle(app)

        # Should NOT hide — should trigger rebuild/show
        mock_ac.action_hide.assert_not_called()
        mock_ac.refresh_dropdown.assert_called_once()

    def test_toggle_shows_when_visible_but_no_options(self) -> None:
        """When autocomplete widget is displayed but has 0 options, toggle triggers rebuild."""
        app = MagicMock()

        mock_ac = MagicMock()
        mock_ac.display = True
        mock_ac.option_list.option_count = 0

        app.query_one = MagicMock(return_value=mock_ac)

        from functualize._cli.tui.app import FunctualizeInlineTUI

        FunctualizeInlineTUI.action_autocomplete_toggle(app)

        # No options → falls to else branch → refresh_dropdown
        mock_ac.action_hide.assert_not_called()
        mock_ac.refresh_dropdown.assert_called_once()

    def test_is_autocomplete_visible_returns_true_when_displayed_with_options(
        self,
    ) -> None:
        """is_autocomplete_visible() returns True when widget displayed with options."""
        app = MagicMock()

        mock_ac = MagicMock()
        mock_ac.display = True
        mock_ac.option_list.option_count = 5

        app.query_one = MagicMock(return_value=mock_ac)

        from functualize._cli.tui.app import FunctualizeInlineTUI

        result = FunctualizeInlineTUI.is_autocomplete_visible(app)

        assert result is True

    def test_is_autocomplete_visible_returns_false_when_hidden(self) -> None:
        """is_autocomplete_visible() returns False when widget is not displayed."""
        app = MagicMock()

        mock_ac = MagicMock()
        mock_ac.display = False
        mock_ac.option_list.option_count = 5

        app.query_one = MagicMock(return_value=mock_ac)

        from functualize._cli.tui.app import FunctualizeInlineTUI

        result = FunctualizeInlineTUI.is_autocomplete_visible(app)

        assert result is False
