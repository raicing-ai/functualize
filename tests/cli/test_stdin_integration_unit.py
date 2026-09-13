"""Unit tests for stdin integration.

# Feature: cli-unix-compatibility, Task 7.4

Tests that stdin piping, explicit flag priority, TTY error handling,
default-value fallback, and multiple-Stdin-param detection all work correctly
through `resolve_stdin_params()` and the `create_job_command()` integration.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from functualize._engine.stdin_reader import resolve_stdin_params
from functualize.job.markers import Stdin

# =============================================================================
# Test: Pipe scenario — stdin piped, no flag → param populated from stdin
# =============================================================================


class TestPipePopulatesParam:
    """When stdin is piped and no CLI value is provided, the param gets stdin content.

    **Validates: Requirement 5.1**
    """

    def test_single_param_populated_from_pipe(self) -> None:
        """Single Stdin param with no CLI value reads piped content."""
        stdin_markers = {"data": Stdin()}
        cli_values: dict[str, Any] = {}

        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=False
            ),
            patch(
                "functualize._engine.stdin_reader.sys.stdin.read",
                return_value="piped data",
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        assert result == {"data": "piped data"}

    def test_none_cli_value_treated_as_not_provided(self) -> None:
        """A CLI value of None is treated as 'not provided' — stdin is read."""
        stdin_markers = {"content": Stdin(encoding="utf-8")}
        cli_values: dict[str, Any] = {"content": None}

        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=False
            ),
            patch(
                "functualize._engine.stdin_reader.sys.stdin.read",
                return_value="hello world",
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        assert result == {"content": "hello world"}

    def test_multiline_content_preserved(self) -> None:
        """Multi-line piped content is preserved exactly."""
        stdin_markers = {"payload": Stdin()}
        cli_values: dict[str, Any] = {}
        content = "line1\nline2\nline3\n"

        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=False
            ),
            patch(
                "functualize._engine.stdin_reader.sys.stdin.read",
                return_value=content,
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        assert result == {"payload": content}


# =============================================================================
# Test: Explicit flag wins over piped stdin
# =============================================================================


class TestExplicitFlagWins:
    """When a CLI flag value is provided, it takes priority over piped stdin.

    **Validates: Requirement 5.2**
    """

    def test_cli_value_overrides_piped_stdin(self) -> None:
        """CLI value provided → resolve_stdin_params returns empty dict."""
        stdin_markers = {"data": Stdin()}
        cli_values: dict[str, Any] = {"data": "explicit value"}

        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=False
            ),
            patch(
                "functualize._engine.stdin_reader.sys.stdin.read",
                return_value="piped data",
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        # Empty dict = nothing resolved from stdin, CLI value wins
        assert result == {}

    def test_empty_string_cli_value_still_wins(self) -> None:
        """Even an empty string CLI value counts as 'provided' and wins."""
        stdin_markers = {"data": Stdin()}
        cli_values: dict[str, Any] = {"data": ""}

        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=False
            ),
            patch(
                "functualize._engine.stdin_reader.sys.stdin.read",
                return_value="piped data",
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        assert result == {}

    def test_cli_value_wins_even_when_tty(self) -> None:
        """CLI value wins regardless of stdin TTY state."""
        stdin_markers = {"data": Stdin()}
        cli_values: dict[str, Any] = {"data": "flag value"}

        with patch(
            "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=True
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        assert result == {}


# =============================================================================
# Test: TTY + required + no default → error (no blocking)
# =============================================================================


class TestATerminalResolvesNothing:
    """Stdin is a terminal and nothing supplied the parameter → resolve nothing.

    **This class and the one that followed it used to assert the opposite**, and
    what they asserted was a defect worth reading about. `resolve_stdin_params`
    raised `SystemExit(1)` here, under a comment saying "the caller is
    responsible for determining whether the param has a default … signal this so
    the caller can decide". It exited rather than signalling, so no caller ever
    could — and the class documenting that fact was called
    `TestTtyWithDefault`, its docstring explaining that the CLI adapter
    compensated by "removing None values from kwargs". That compensation stopped
    existing when the kwargs split moved into the engine (run-request/T11), and
    the class kept passing anyway, because all it asserted was the exit.

    The maintainer's decision (2026-09-10): a parameter with a default is
    optional here as it is everywhere else in the framework. So this function
    resolves nothing and lets the job's own default win.

    A parameter with **no** default is not made optional by this — it fails as
    the ordinary missing-argument error every other parameter raises, one level
    up. That is asserted where it now happens, in
    `tests/engine/test_run_request_stdin.py`, rather than here: this function no
    longer knows what a default is, which is the point.

    **Validates: Requirements 5.3, 5.4**
    """

    def test_no_cli_value_resolves_nothing(self) -> None:
        stdin_markers = {"data": Stdin()}
        cli_values: dict[str, Any] = {}

        with patch(
            "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=True
        ):
            resolved = resolve_stdin_params(stdin_markers, cli_values)

        assert resolved == {}

    def test_an_explicit_none_also_resolves_nothing(self) -> None:
        """`None` means "the flag was not given", not "the value is None"."""
        stdin_markers = {"content": Stdin()}
        cli_values: dict[str, Any] = {"content": None}

        with patch(
            "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=True
        ):
            resolved = resolve_stdin_params(stdin_markers, cli_values)

        assert resolved == {}

    def test_it_does_not_exit_and_does_not_write_to_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The two halves of the old behaviour, pinned as gone.

        Not exiting is the decision; staying silent is what makes it usable —
        a job quietly taking its default should not print an error first.
        """
        stdin_markers = {"payload": Stdin()}

        with patch(
            "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=True
        ):
            resolved = resolve_stdin_params(stdin_markers, {})

        assert resolved == {}
        assert capsys.readouterr().err == ""


# =============================================================================
# Test: Multiple Stdin params → error
# =============================================================================


class TestMultipleStdinParams:
    """Multiple unresolved Stdin params raise ValueError (ambiguous).

    Stdin can only feed one parameter — if multiple need it, the user must
    provide explicit CLI flag values for all but one.

    **Validates: Requirement 5.5**
    """

    def test_two_unresolved_stdin_params_raises_value_error(self) -> None:
        """Two Stdin params with no CLI values → ValueError."""
        stdin_markers = {"data": Stdin(), "content": Stdin()}
        cli_values: dict[str, Any] = {}

        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=False
            ),
            pytest.raises(ValueError, match="Multiple Stdin-marked parameters"),
        ):
            resolve_stdin_params(stdin_markers, cli_values)

    def test_three_unresolved_stdin_params_raises_value_error(self) -> None:
        """Three Stdin params with no CLI values → ValueError."""
        stdin_markers = {
            "data": Stdin(),
            "content": Stdin(),
            "payload": Stdin(),
        }
        cli_values: dict[str, Any] = {}

        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=False
            ),
            pytest.raises(ValueError, match="Multiple Stdin-marked parameters"),
        ):
            resolve_stdin_params(stdin_markers, cli_values)

    def test_error_raised_even_when_stdin_is_tty(self) -> None:
        """Multiple unresolved Stdin params raise ValueError regardless of TTY state."""
        stdin_markers = {"data": Stdin(), "content": Stdin()}
        cli_values: dict[str, Any] = {}

        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=True
            ),
            pytest.raises(ValueError, match="Multiple Stdin-marked parameters"),
        ):
            resolve_stdin_params(stdin_markers, cli_values)

    def test_one_resolved_one_unresolved_is_ok(self) -> None:
        """One Stdin param resolved via CLI, one unresolved → no error, reads stdin."""
        stdin_markers = {"data": Stdin(), "content": Stdin()}
        cli_values: dict[str, Any] = {"data": "explicit"}

        with (
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=False
            ),
            patch(
                "functualize._engine.stdin_reader.sys.stdin.read",
                return_value="piped value",
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        assert result == {"content": "piped value"}

    def test_error_message_lists_param_names(self) -> None:
        """The ValueError message lists the ambiguous parameter names."""
        stdin_markers = {"alpha": Stdin(), "beta": Stdin()}
        cli_values: dict[str, Any] = {}

        with (
            pytest.raises(ValueError, match="alpha.*beta|beta.*alpha"),
            patch(
                "functualize._engine.stdin_reader.sys.stdin.isatty", return_value=False
            ),
        ):
            resolve_stdin_params(stdin_markers, cli_values)
