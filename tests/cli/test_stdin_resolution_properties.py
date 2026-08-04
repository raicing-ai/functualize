"""Property-based tests for stdin resolution (Properties 7, 13).

Tests that resolve_stdin_params correctly prioritizes explicit CLI flag values
over piped stdin content (Property 7) and populates a single Stdin-marked param
from piped content when no CLI flag is provided (Property 13).

# Feature: cli-unix-compatibility, Properties 7, 13
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.stdin_reader import resolve_stdin_params
from functualize.job.markers import Stdin

# =============================================================================
# Strategies
# =============================================================================

# Strategy: valid Python identifiers for parameter names
_param_names = st.sampled_from(
    [
        "data",
        "content",
        "payload",
        "body",
        "input_text",
        "message",
        "source",
        "raw",
    ]
)

# Strategy: non-empty stdin content (simulating piped input)
_stdin_content = st.text(min_size=1, max_size=500)

# Strategy: CLI flag values (non-None strings representing explicit user input)
_cli_flag_values = st.text(min_size=1, max_size=200)

# Strategy: Stdin marker with varying encoding (always utf-8 for simplicity)
_stdin_marker = st.builds(
    Stdin,
    flag=st.one_of(st.none(), st.just("--data"), st.just("--input")),
    help=st.one_of(st.none(), st.text(min_size=1, max_size=30)),
    encoding=st.just("utf-8"),
)


# =============================================================================
# Property 7: Stdin Explicit-Wins
# =============================================================================


@pytest.mark.slow
class TestStdinExplicitWins:
    """Property 7: Stdin Explicit-Wins.

    For any stdin pipe content and any CLI flag value provided for a
    Stdin()-marked parameter, the resolved parameter value SHALL always
    equal the CLI flag value — explicit input always takes priority over
    implicit stdin.

    **Validates: Requirement 5.2**
    """

    @given(
        param_name=_param_names,
        cli_value=_cli_flag_values,
        stdin_content=_stdin_content,
        marker=_stdin_marker,
    )
    @settings(max_examples=200)
    def test_cli_value_wins_over_piped_stdin(
        self,
        param_name: str,
        cli_value: str,
        stdin_content: str,
        marker: Stdin,
    ) -> None:
        """When CLI provides a value, stdin content is ignored entirely.

        **Validates: Requirement 5.2**
        """
        stdin_markers = {param_name: marker}
        cli_values = {param_name: cli_value}

        # Mock stdin as piped (non-TTY) with content available
        with (
            patch("functualize._cli.stdin_reader.sys.stdin.isatty", return_value=False),
            patch(
                "functualize._cli.stdin_reader.sys.stdin.read",
                return_value=stdin_content,
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        # CLI value wins: resolve_stdin_params returns empty dict
        # because the param is already resolved via CLI
        assert result == {}, (
            f"Expected empty dict (CLI value wins), got {result}. "
            f"CLI value '{cli_value}' should take priority over stdin content."
        )

    @given(
        param_name=_param_names,
        cli_value=_cli_flag_values,
        marker=_stdin_marker,
    )
    @settings(max_examples=200)
    def test_cli_value_wins_when_stdin_is_tty(
        self,
        param_name: str,
        cli_value: str,
        marker: Stdin,
    ) -> None:
        """When CLI provides a value and stdin is TTY, result is still empty.

        **Validates: Requirement 5.2**
        """
        stdin_markers = {param_name: marker}
        cli_values = {param_name: cli_value}

        # Mock stdin as TTY (no piped data)
        with patch("functualize._cli.stdin_reader.sys.stdin.isatty", return_value=True):
            result = resolve_stdin_params(stdin_markers, cli_values)

        # CLI value wins: returns empty dict
        assert result == {}, (
            f"Expected empty dict (CLI value wins), got {result}. "
            f"Even with TTY stdin, CLI value '{cli_value}' should take priority."
        )

    @given(
        param_name=_param_names,
        cli_value=_cli_flag_values,
        stdin_content=_stdin_content,
        marker=_stdin_marker,
        extra_name=st.sampled_from(["extra", "other", "secondary"]),
        extra_marker=_stdin_marker,
    )
    @settings(max_examples=200)
    def test_cli_value_wins_with_multiple_stdin_params(
        self,
        param_name: str,
        cli_value: str,
        stdin_content: str,
        marker: Stdin,
        extra_name: str,
        extra_marker: Stdin,
    ) -> None:
        """When all Stdin params have CLI values, stdin is never read.

        **Validates: Requirement 5.2**
        """
        # Ensure distinct param names
        if extra_name == param_name:
            extra_name = f"{extra_name}_alt"

        stdin_markers = {param_name: marker, extra_name: extra_marker}
        cli_values = {param_name: cli_value, extra_name: "other_value"}

        # Mock stdin as piped (non-TTY)
        with (
            patch("functualize._cli.stdin_reader.sys.stdin.isatty", return_value=False),
            patch(
                "functualize._cli.stdin_reader.sys.stdin.read",
                return_value=stdin_content,
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        # All params have CLI values → empty dict
        assert result == {}, (
            f"Expected empty dict when all Stdin params have CLI values, got {result}."
        )


# =============================================================================
# Property 13: Stdin Resolution from Pipe
# =============================================================================


@pytest.mark.slow
class TestStdinResolutionFromPipe:
    """Property 13: Stdin Resolution from Pipe.

    For any non-empty string content piped to stdin and for any function with
    a single Stdin()-marked parameter that has no CLI flag value provided,
    resolve_stdin_params SHALL populate that parameter with the piped content.

    **Validates: Requirement 5.1**
    """

    @given(
        param_name=_param_names,
        stdin_content=_stdin_content,
        marker=_stdin_marker,
    )
    @settings(max_examples=200)
    def test_single_unresolved_param_gets_piped_content(
        self,
        param_name: str,
        stdin_content: str,
        marker: Stdin,
    ) -> None:
        """A single Stdin param with no CLI value is populated from pipe.

        **Validates: Requirement 5.1**
        """
        stdin_markers = {param_name: marker}
        cli_values: dict[str, Any] = {}  # No CLI value provided

        # Mock stdin as piped (non-TTY) with content
        with (
            patch("functualize._cli.stdin_reader.sys.stdin.isatty", return_value=False),
            patch(
                "functualize._cli.stdin_reader.sys.stdin.read",
                return_value=stdin_content,
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        assert result == {param_name: stdin_content}, (
            f"Expected {{'{param_name}': '{stdin_content[:50]}...'}}, "
            f"got {result}. Piped content should populate the unresolved param."
        )

    @given(
        param_name=_param_names,
        stdin_content=_stdin_content,
        marker=_stdin_marker,
    )
    @settings(max_examples=200)
    def test_none_cli_value_treated_as_unresolved(
        self,
        param_name: str,
        stdin_content: str,
        marker: Stdin,
    ) -> None:
        """A CLI value of None is treated as 'not provided' — stdin is read.

        **Validates: Requirement 5.1**
        """
        stdin_markers = {param_name: marker}
        cli_values: dict[str, Any] = {param_name: None}  # None = not provided

        # Mock stdin as piped (non-TTY) with content
        with (
            patch("functualize._cli.stdin_reader.sys.stdin.isatty", return_value=False),
            patch(
                "functualize._cli.stdin_reader.sys.stdin.read",
                return_value=stdin_content,
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        assert result == {param_name: stdin_content}, (
            f"Expected {{'{param_name}': content}}, got {result}. "
            f"None CLI value should be treated as unresolved."
        )

    @given(
        param_name=_param_names,
        stdin_content=_stdin_content,
        cli_value=_cli_flag_values,
        marker=_stdin_marker,
        extra_name=st.sampled_from(["extra", "other", "secondary"]),
        extra_marker=_stdin_marker,
    )
    @settings(max_examples=200)
    def test_one_resolved_one_unresolved_reads_stdin_for_unresolved(
        self,
        param_name: str,
        stdin_content: str,
        cli_value: str,
        marker: Stdin,
        extra_name: str,
        extra_marker: Stdin,
    ) -> None:
        """With multiple Stdin params, only the one without CLI value gets stdin.

        **Validates: Requirement 5.1**
        """
        # Ensure distinct param names
        if extra_name == param_name:
            extra_name = f"{extra_name}_alt"

        stdin_markers = {param_name: marker, extra_name: extra_marker}
        # First param has CLI value, second does not
        cli_values: dict[str, Any] = {param_name: cli_value}

        # Mock stdin as piped (non-TTY) with content
        with (
            patch("functualize._cli.stdin_reader.sys.stdin.isatty", return_value=False),
            patch(
                "functualize._cli.stdin_reader.sys.stdin.read",
                return_value=stdin_content,
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        # Only the unresolved param (extra_name) gets stdin content
        assert result == {extra_name: stdin_content}, (
            f"Expected {{'{extra_name}': content}}, got {result}. "
            f"Only the param without a CLI value should get stdin content."
        )

    @given(
        param_name=_param_names,
        stdin_content=_stdin_content,
        marker=_stdin_marker,
    )
    @settings(max_examples=100)
    def test_piped_content_preserved_exactly(
        self,
        param_name: str,
        stdin_content: str,
        marker: Stdin,
    ) -> None:
        """The exact piped content is returned without modification.

        **Validates: Requirement 5.1**
        """
        stdin_markers = {param_name: marker}
        cli_values: dict[str, Any] = {}

        with (
            patch("functualize._cli.stdin_reader.sys.stdin.isatty", return_value=False),
            patch(
                "functualize._cli.stdin_reader.sys.stdin.read",
                return_value=stdin_content,
            ),
        ):
            result = resolve_stdin_params(stdin_markers, cli_values)

        # Content should be byte-for-byte identical
        assert result[param_name] is stdin_content, (
            "Expected exact same string object from stdin, "
            "got a different string. Content should not be transformed."
        )
