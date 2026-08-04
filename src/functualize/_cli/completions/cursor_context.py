"""Cursor context parsing for TUI smart bar value completion.

Tokenizes the smart bar text respecting quoted strings and determines the
semantic position of the cursor — whether the user is completing a command
name, a flag name, a flag value, or a positional argument. This drives the
completion list to show context-appropriate suggestions.

This module is in the ``_cli/`` layer — it uses only stdlib.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class CursorContext:
    """Semantic position of the cursor within the smart bar text.

    Determines what kind of completions to show:

    - mode="command": show command/job name completions
    - mode="subcommand": show subcommands of the resolved builtin command
    - mode="flag": show --flag completions for the resolved job
    - mode="value": show value completions for the resolved field
    - mode="positional": show positional argument completions
    - mode="none": offer nothing (e.g. past a builtin's subcommand)

    Structural invariants:

    - When mode="value", both job_name and field_name are non-None.
    - When mode="flag" or "value", job_name is non-None.
    - When mode="positional", job_name is non-None and positional_index is non-None.
    - When mode="subcommand" or "none", job_name holds the builtin command name.
    """

    mode: str  # "command" | "subcommand" | "flag" | "value" | "positional" | "none"
    job_name: str | None
    field_name: str | None
    partial: str
    positional_index: int | None = None  # 0-based, for "positional" mode


def _smart_split(text: str) -> list[str]:
    """Tokenize text respecting quoted strings (single and double quotes).

    Uses :func:`shlex.split` with ``posix=True`` for proper quote handling.
    Falls back to a simple whitespace split if the input has unbalanced quotes
    (incomplete quoting is expected when the user is still typing).

    Args:
        text: The raw smart bar text to tokenize.

    Returns:
        A list of token strings with quotes removed from completed tokens.
    """
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        # Unbalanced quotes — fall back to simple split
        return text.split()


def _count_positional_tokens(tokens_after_job: list[str]) -> int:
    """Count non-flag tokens after the job name, skipping flag values.

    A "flag" token starts with "--" (or "-" for short flags). The token
    immediately following a flag (that doesn't contain "=") is considered
    its value and is not counted as positional.

    Args:
        tokens_after_job: Completed tokens after the job name token.

    Returns:
        The number of positional (non-flag, non-flag-value) tokens.
    """
    count = 0
    skip_next = False
    for token in tokens_after_job:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-") and token != "-":
            # It's a flag token. If it doesn't contain "=", the next
            # token is its value.
            if "=" not in token:
                skip_next = True
            continue
        # Non-flag token → positional argument
        count += 1
    return count


def parse_cursor_context(
    text: str,
    cursor_pos: int,
    job_names: list[str],
    positional_params: dict[str, int] | None = None,
    builtin_subcommands: dict[str, dict[str, tuple[str, ...]]] | None = None,
) -> CursorContext:
    """Parse smart bar text and cursor position into a semantic context.

    Determines whether the cursor is completing a command name, a builtin
    subcommand, a flag name, a flag value, or a positional argument based
    on the tokens preceding the cursor position.

    Args:
        text: The full smart bar text content.
        cursor_pos: The cursor position (0 to len(text) inclusive).
        job_names: List of recognized job names for resolution.
        positional_params: Optional mapping of job name to the count of
            Arg()-annotated positional parameters for that job. When provided,
            enables "positional" mode detection.
        builtin_subcommands: Optional nested ``{root: {child: (grandchild, ...)}}``
            builtin tree. Two levels deep: outer key is the root name
            (``builtin``), inner keys are the children (``cache``, ``config``,
            …), and values are each child's subcommand names (or empty tuple
            when the child is a leaf). Membership at any level suppresses
            command-mode completions.

    Returns:
        A :class:`CursorContext` describing the semantic position.
    """
    # Tokenize text up to cursor position
    text_to_cursor = text[:cursor_pos]
    tokens = _smart_split(text_to_cursor)
    trailing_space = text_to_cursor.endswith(" ") and bool(text_to_cursor.strip())

    # No tokens or cursor in first position → command mode
    if not tokens:
        return CursorContext(mode="command", job_name=None, field_name=None, partial="")

    # Determine partial (what's being typed right now)
    if trailing_space:
        partial = ""
        completed_tokens = tokens
    else:
        partial = tokens[-1]
        completed_tokens = tokens[:-1]

    # Walk the nested builtin tree one level per completed token.
    # A job with the same name shadows the builtin (matches dispatch precedence).
    if (
        builtin_subcommands
        and completed_tokens
        and completed_tokens[0] in builtin_subcommands
        and completed_tokens[0] not in job_names
    ):
        _walk = builtin_subcommands[completed_tokens[0]]
        if len(completed_tokens) == 1 and not partial.startswith("-"):
            return CursorContext(
                mode="subcommand",
                job_name=completed_tokens[0],
                field_name=None,
                partial=partial,
            )
        if (
            len(completed_tokens) == 2
            and completed_tokens[1] in _walk
            and not partial.startswith("-")
        ):
            inner = _walk[completed_tokens[1]]
            if not inner:
                return CursorContext(
                    mode="none",
                    job_name=completed_tokens[0],
                    field_name=completed_tokens[1],
                    partial=partial,
                )
            return CursorContext(
                mode="subcommand",
                job_name=completed_tokens[0],
                field_name=completed_tokens[1],
                partial=partial,
            )
        return CursorContext(
            mode="none",
            job_name=completed_tokens[0],
            field_name=completed_tokens[1] if len(completed_tokens) >= 2 else None,
            partial=partial,
        )

    # Resolve job name from first completed token
    job_name: str | None = None
    if completed_tokens and completed_tokens[0] in job_names:
        job_name = completed_tokens[0]
    elif not completed_tokens and tokens[0] not in job_names:
        # Still typing the command name
        return CursorContext(
            mode="command", job_name=None, field_name=None, partial=partial
        )

    # If no job resolved yet, we're completing a command
    if job_name is None:
        return CursorContext(
            mode="command", job_name=None, field_name=None, partial=partial
        )

    # Check if we're in value position: previous completed token is a --flag
    if completed_tokens and len(completed_tokens) >= 2:
        prev_token = completed_tokens[-1]
        if prev_token.startswith("--") and "=" not in prev_token:
            field_name = prev_token[2:].replace("-", "_")
            return CursorContext(
                mode="value",
                job_name=job_name,
                field_name=field_name,
                partial=partial,
            )

    # If partial starts with "--", we're completing a flag (always, even if
    # positional slots remain unfilled — Requirement 19.5)
    if partial.startswith("--"):
        return CursorContext(
            mode="flag", job_name=job_name, field_name=None, partial=partial
        )

    # If trailing space after a --flag, we're entering a value
    if trailing_space and completed_tokens:
        last = completed_tokens[-1]
        if last.startswith("--") and "=" not in last:
            field_name = last[2:].replace("-", "_")
            return CursorContext(
                mode="value",
                job_name=job_name,
                field_name=field_name,
                partial="",
            )

    # --- Positional mode detection ---
    # If we know the number of positional params for this job, check whether
    # the cursor is in positional argument territory.
    if positional_params and job_name in positional_params:
        n_positional = positional_params[job_name]
        if n_positional > 0:
            # Tokens after the job name (excluding the job token itself)
            tokens_after_job = completed_tokens[1:]
            k = _count_positional_tokens(tokens_after_job)

            # If the partial itself is not empty and doesn't start with "-",
            # it's being typed as a positional value (not yet completed).
            # The count K is based on completed tokens only.
            if k < n_positional:
                return CursorContext(
                    mode="positional",
                    job_name=job_name,
                    field_name=None,
                    partial=partial,
                    positional_index=k,
                )
            # K >= N: all positional slots filled → fall through to flag mode

    # Default: flag completion mode (after job name)
    return CursorContext(
        mode="flag", job_name=job_name, field_name=None, partial=partial
    )
