"""Unit tests for _run_fallback_chain (public API).

The old callback-based routing tests for FileExecutionFallback and AliasFallback
have been removed as those classes are deprecated and no longer used in the
``_cli/main.py`` critical path. Single-file execution is now handled by
``_handle_single_file`` and alias expansion by ``_handle_job`` (direct dispatch).

_run_fallback_chain remains in the public API (functualize.app.adapters.cli)
for consumer projects that use CliAdapter/FallbackGroup directly.

_Requirements: 15.2–15.5, 15.10_
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from functualize.app.adapters.cli import _run_fallback_chain

if TYPE_CHECKING:
    import pytest

# =============================================================================
# Helpers
# =============================================================================


@dataclass
class MockFallback:
    """A mock FallbackCommand that records calls."""

    will_match: bool = False
    exit_code: int = 0
    matches_called: bool = field(default=False, init=False)
    execute_called: bool = field(default=False, init=False)

    def matches(self, args: list[str], app: object) -> bool:
        self.matches_called = True
        return self.will_match

    def execute(self, args: list[str], app: object) -> int:
        self.execute_called = True
        return self.exit_code


# =============================================================================
# _run_fallback_chain tests
# =============================================================================


class TestRunFallbackChain:
    """Tests for _run_fallback_chain function."""

    def test_no_fallbacks_returns_1(self) -> None:
        """No fallbacks, any args → returns 1 (command not found)."""
        result = _run_fallback_chain(["some-cmd"], app=MagicMock(), fallbacks=[])

        assert result == 1

    def test_first_fallback_matches_returns_its_exit_code(self) -> None:
        """First fallback matches → its execute() called, returns its exit code."""
        fb = MockFallback(will_match=True, exit_code=42)

        result = _run_fallback_chain(["cmd"], app=MagicMock(), fallbacks=[fb])

        assert fb.execute_called is True
        assert result == 42

    def test_second_fallback_matches_when_first_doesnt(self) -> None:
        """Second fallback matches (first doesn't) → second's execute() called."""
        fb1 = MockFallback(will_match=False, exit_code=10)
        fb2 = MockFallback(will_match=True, exit_code=5)

        result = _run_fallback_chain(["cmd"], app=MagicMock(), fallbacks=[fb1, fb2])

        assert fb1.matches_called is True
        assert fb1.execute_called is False
        assert fb2.execute_called is True
        assert result == 5

    def test_command_not_found_output_includes_suggestions(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """'command not found' output includes suggestions for similar commands."""
        from functualize.app import FunctualizeApp

        # Create a mock app that returns known job names
        mock_app = MagicMock(spec=FunctualizeApp)
        mock_descriptor_deploy = MagicMock()
        mock_descriptor_deploy.name = "deploy"
        mock_descriptor_destroy = MagicMock()
        mock_descriptor_destroy.name = "destroy"
        mock_app.get_jobs.return_value = [
            mock_descriptor_deploy,
            mock_descriptor_destroy,
        ]

        result = _run_fallback_chain(["dep"], app=mock_app, fallbacks=[])

        assert result == 1
        captured = capsys.readouterr()
        # The error message should appear on stderr
        assert "not found" in captured.err
        # Should suggest "deploy" since "dep" is a prefix of "deploy"
        assert "deploy" in captured.err

    def test_no_match_empty_args_returns_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Empty args with no fallbacks → returns 1."""
        result = _run_fallback_chain([], app=MagicMock(), fallbacks=[])

        assert result == 1
