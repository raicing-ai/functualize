"""Unit tests for CursorContext parser edge cases.

Tests the parse_cursor_context function with specific inputs to verify
correct mode detection, field resolution, and partial text handling.

Feature: TUI Smart Bar & Modals (Phase 2)
Task: 1.3 — Write unit tests for CursorContext parser edge cases
Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.7
"""

from __future__ import annotations

from functualize._cli.completions.cursor_context import (
    CursorContext,
    parse_cursor_context,
)


class TestCursorContextEdgeCases:
    """Unit tests for parse_cursor_context edge cases."""

    def test_empty_text_returns_command_mode(self) -> None:
        """Empty text → mode='command', partial=''."""
        result = parse_cursor_context("", 0, ["deploy"])

        assert result == CursorContext(
            mode="command", job_name=None, field_name=None, partial=""
        )

    def test_single_token_matching_job_with_trailing_space(self) -> None:
        """'deploy ' with cursor at end → mode='flag', job_name='deploy'."""
        result = parse_cursor_context("deploy ", 7, ["deploy"])

        assert result.mode == "flag"
        assert result.job_name == "deploy"
        assert result.partial == ""

    def test_flag_value_position(self) -> None:
        """'deploy --env ' → mode='value', field_name='env'."""
        result = parse_cursor_context("deploy --env ", 13, ["deploy"])

        assert result.mode == "value"
        assert result.job_name == "deploy"
        assert result.field_name == "env"
        assert result.partial == ""

    def test_partial_flag(self) -> None:
        """'deploy --e' → mode='flag', partial='--e'."""
        result = parse_cursor_context("deploy --e", 10, ["deploy"])

        assert result.mode == "flag"
        assert result.job_name == "deploy"
        assert result.field_name is None
        assert result.partial == "--e"

    def test_quoted_strings(self) -> None:
        """Quoted strings are handled: 'deploy --msg "hello world" --env ' → mode='value', field_name='env'."""
        text = 'deploy --msg "hello world" --env '
        result = parse_cursor_context(text, len(text), ["deploy"])

        assert result.mode == "value"
        assert result.job_name == "deploy"
        assert result.field_name == "env"
        assert result.partial == ""

    def test_cursor_in_middle_of_text(self) -> None:
        """Only text before cursor matters when cursor_pos < len(text)."""
        # Full text is "deploy --env staging" but cursor is at position 13
        # (right after "deploy --env "), so we should get value mode for env
        text = "deploy --env staging"
        result = parse_cursor_context(text, 13, ["deploy"])

        assert result.mode == "value"
        assert result.job_name == "deploy"
        assert result.field_name == "env"
        assert result.partial == ""

    def test_unknown_job_returns_command_mode(self) -> None:
        """Unknown job name → mode='command'."""
        result = parse_cursor_context("unknown ", 8, ["deploy"])

        assert result.mode == "command"
        assert result.job_name is None

    def test_hyphenated_flag_converts_to_underscore(self) -> None:
        """'deploy --my-flag ' → field_name='my_flag' (hyphens become underscores)."""
        result = parse_cursor_context("deploy --my-flag ", 17, ["deploy"])

        assert result.mode == "value"
        assert result.job_name == "deploy"
        assert result.field_name == "my_flag"
        assert result.partial == ""


# Nested builtin tree: outer key = root name (``builtin``), inner key =
# child name, value = tuple of grand-subcommands (empty for leaf commands).
_SUBCOMMANDS: dict[str, dict[str, tuple[str, ...]]] = {
    "builtin": {
        "config": ("show", "path", "edit"),
        "cache": ("show", "clear", "check"),
        "version": (),
    }
}


class TestSubcommandMode:
    """Unit tests for builtin subcommand detection."""

    def test_builtin_with_trailing_space_enters_subcommand_mode(self) -> None:
        """``builtin `` → mode='subcommand', job_name='builtin' (show children)."""
        result = parse_cursor_context(
            "builtin ", 8, ["deploy"], builtin_subcommands=_SUBCOMMANDS
        )

        assert result.mode == "subcommand"
        assert result.job_name == "builtin"
        assert result.partial == ""

    def test_partial_child(self) -> None:
        """``builtin con`` → mode='subcommand', partial='con'."""
        result = parse_cursor_context(
            "builtin con", 11, ["deploy"], builtin_subcommands=_SUBCOMMANDS
        )

        assert result.mode == "subcommand"
        assert result.job_name == "builtin"
        assert result.partial == "con"

    def test_child_trailing_space_drills_into_grandchildren(self) -> None:
        """``builtin config `` → subcommand mode for config's children."""
        result = parse_cursor_context(
            "builtin config ", 15, ["deploy"], builtin_subcommands=_SUBCOMMANDS
        )

        assert result.mode == "subcommand"
        assert result.job_name == "builtin"
        assert result.field_name == "config"

    def test_partial_grandchild(self) -> None:
        """``builtin config sh`` → subcommand mode, partial='sh'."""
        result = parse_cursor_context(
            "builtin config sh", 18, ["deploy"], builtin_subcommands=_SUBCOMMANDS
        )

        assert result.mode == "subcommand"
        assert result.job_name == "builtin"
        assert result.field_name == "config"
        assert result.partial == "sh"

    def test_completed_subcommand_offers_nothing(self) -> None:
        """``builtin config show `` → nothing to complete."""
        result = parse_cursor_context(
            "builtin config show ", 21, ["deploy"], builtin_subcommands=_SUBCOMMANDS
        )

        assert result.mode == "none"

    def test_completed_subcommand_does_not_resume_command_list(self) -> None:
        """The reported bug: ``builtin config path `` re-offered jobs."""
        result = parse_cursor_context(
            "builtin config path ", 21, ["deploy"], builtin_subcommands=_SUBCOMMANDS
        )

        assert result.mode != "command"

    def test_leaf_builtin_offers_nothing(self) -> None:
        """``builtin version `` → leaf, nothing to offer."""
        result = parse_cursor_context(
            "builtin version ", 16, ["deploy"], builtin_subcommands=_SUBCOMMANDS
        )

        assert result.mode != "command"

    def test_flag_after_builtin_not_subcommand(self) -> None:
        """``builtin config --h`` → not subcommand mode (flag-style partial)."""
        result = parse_cursor_context(
            "builtin config --h", 19, ["deploy"], builtin_subcommands=_SUBCOMMANDS
        )

        assert result.mode != "subcommand"
        assert result.mode != "command"

    def test_a_job_shadows_a_same_named_builtin_root(self) -> None:
        """A real job named ``builtin`` suppresses the builtin tree."""
        result = parse_cursor_context(
            "builtin config show ",
            21,
            ["builtin"],
            builtin_subcommands=_SUBCOMMANDS,
        )

        assert result.mode != "none"
        assert result.job_name == "builtin"

    def test_without_mapping_builtin_stays_command_mode(self) -> None:
        """Without builtin_subcommands, ``builtin `` behaves as before."""
        result = parse_cursor_context("builtin ", 8, ["deploy"])

        assert result.mode == "command"

    def test_job_name_shadowing_builtin_prefers_job(self) -> None:
        """A job literally named ``builtin`` still gets flag completion."""
        result = parse_cursor_context(
            "builtin ", 8, ["builtin"], builtin_subcommands=_SUBCOMMANDS
        )

        assert result.mode == "flag"
        assert result.job_name == "builtin"

    def test_typing_builtin_root_name_is_command_mode(self) -> None:
        """``buil`` (no completed token yet) stays in command mode."""
        result = parse_cursor_context(
            "buil", 4, ["deploy"], builtin_subcommands=_SUBCOMMANDS
        )

        assert result.mode == "command"
        assert result.partial == "buil"
