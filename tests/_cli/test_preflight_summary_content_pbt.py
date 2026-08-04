"""Property-based test for Pre-flight Summary content completeness.

Property 2: For any set of job field definitions (with names, values, sources),
the rendered output contains every field's name, value/default, source label,
and indicator character (● or ○).

Feature: TUI v3 UX Polish
Task: 8.2
**Validates: Requirements 2.3**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.tui.cli_arg_parser import parse_cli_args_to_kwargs
from functualize._cli.tui.preflight_summary import build_preflight_lines

# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeFieldDescriptor:
    """Minimal field descriptor matching the interface used by build_preflight_lines.

    ``required=True`` is fixed so the real function's three-state indicator
    (filled/required-empty/optional-empty) collapses to the two states
    (filled/empty) this property test exercises — matching this test's
    original intent (Property 2 is about required-field content
    completeness, not indicator-state coverage).
    """

    name: str
    default: Any | None
    required: bool = True


class FakeRichLog:
    """Captures write() and clear() calls like a RichLog widget."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.cleared: bool = False

    def clear(self) -> None:
        self.lines = []
        self.cleared = True

    def write(self, content: str) -> None:
        self.lines.append(content)


def render_preflight_summary(
    smart_bar_value: str,
    fields: list[FakeFieldDescriptor],
    log: FakeRichLog,
) -> None:
    """Render via the real build_preflight_lines, exactly as app.py does.

    This calls the actual production implementation instead of a
    hand-maintained replica, so the property test validates real behavior.
    """
    log.clear()
    tokens = smart_bar_value.split() if smart_bar_value.strip() else []
    if not tokens:
        return
    # tokens[0] is the job name; remaining are CLI args
    provided = parse_cli_args_to_kwargs(tokens[1:] if len(tokens) > 1 else [])
    for line in build_preflight_lines(fields, provided, avail_width=200):
        log.write(line)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Field names: valid identifiers (letters, digits, underscores), non-empty
_FIELD_NAME_CHARS = st.characters(
    whitelist_categories=("Ll",),  # lowercase letters only for simplicity
    whitelist_characters="_",
)

_field_names = st.text(alphabet=_FIELD_NAME_CHARS, min_size=2, max_size=15).filter(
    lambda s: s[0].isalpha()
)

# Values: non-empty strings without whitespace or leading dashes (valid CLI values)
_field_values = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_.-"),
    min_size=1,
    max_size=20,
).filter(lambda s: not s.startswith("-"))

# Defaults: either None or a non-empty string value
_defaults = st.one_of(st.none(), _field_values)


@st.composite
def field_sets(draw: st.DrawFn) -> tuple[list[FakeFieldDescriptor], dict[str, str]]:
    """Generate 1-5 fields with random names/defaults and a subset with CLI values.

    Returns:
        Tuple of (field_descriptors, cli_provided_values).
    """
    num_fields = draw(st.integers(min_value=1, max_value=5))
    names = draw(
        st.lists(
            _field_names,
            min_size=num_fields,
            max_size=num_fields,
            unique=True,
        )
    )
    fields: list[FakeFieldDescriptor] = []
    cli_values: dict[str, str] = {}

    for name in names:
        default = draw(_defaults)
        fields.append(FakeFieldDescriptor(name=name, default=default))
        # Randomly decide if this field has a CLI-provided value
        has_cli_value = draw(st.booleans())
        if has_cli_value:
            cli_values[name] = draw(_field_values)

    return fields, cli_values


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


class TestPreflightSummaryContentCompleteness:
    """Property 2: Pre-flight Summary content completeness.

    For any set of field definitions with names, values, and defaults,
    the rendered summary output contains every field's name, its current
    value (or default if no CLI value), source label (cli/default), and
    indicator (● for filled, ○ for empty).

    **Validates: Requirements 2.3**
    """

    @pytest.mark.slow
    @given(data=field_sets())
    @settings(max_examples=200)
    def test_rendered_output_contains_all_field_info(
        self,
        data: tuple[list[FakeFieldDescriptor], dict[str, str]],
    ) -> None:
        """Every field's name, value/default, source, and indicator appear in output.

        **Validates: Requirements 2.3**
        """
        fields, cli_values = data

        # Build the SmartBar value: "jobname --field1 val1 --field2 val2 ..."
        parts = ["testjob"]
        for name, value in cli_values.items():
            parts.append(f"--{name}")
            parts.append(value)
        smart_bar_value = " ".join(parts)

        log = FakeRichLog()
        render_preflight_summary(smart_bar_value, fields, log)

        # Verify we got one line per field
        assert len(log.lines) == len(fields), (
            f"Expected {len(fields)} lines, got {len(log.lines)}"
        )

        # Verify each field appears with correct content
        for fd in fields:
            cli_value = cli_values.get(fd.name, "")
            expected_value = (
                cli_value
                if cli_value
                else (fd.default if fd.default is not None else "")
            )
            expected_source = (
                "cli" if cli_value else ("default" if fd.default is not None else "")
            )
            expected_indicator = "●" if cli_value or fd.default is not None else "○"

            # The pre-flight mirrors the CLI flag spelling: a non-positional
            # field's underscored name is hyphenated (``dry_run`` → ``dry-run``).
            # These fakes are all non-positional, so expect the hyphenated form.
            display_name = fd.name.replace("_", "-")

            # Find the line for this field using the "{name}:" pattern
            # The render format is: "  {indicator} {name}: {value}  [dim]({source})[/dim]"
            field_marker = f" {display_name}: "
            matching_lines = [line for line in log.lines if field_marker in line]
            assert matching_lines, (
                f"Field {fd.name!r} (marker {field_marker!r}) not found in any output line. Lines: {log.lines}"
            )
            line = matching_lines[0]

            # Check indicator
            assert expected_indicator in line, (
                f"Expected indicator {expected_indicator!r} for field {fd.name!r} in line: {line!r}"
            )

            # Check field name (CLI spelling)
            assert display_name in line, (
                f"Field name {display_name!r} not in line: {line!r}"
            )

            # Check value (or default) appears
            if expected_value:
                assert str(expected_value) in line, (
                    f"Expected value {expected_value!r} for field {fd.name!r} in line: {line!r}"
                )

            # Check source label
            if expected_source:
                assert expected_source in line, (
                    f"Expected source {expected_source!r} for field {fd.name!r} in line: {line!r}"
                )
