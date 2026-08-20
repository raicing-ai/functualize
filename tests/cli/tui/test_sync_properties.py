"""Property-based tests for SmartBar ↔ Config Table sync.

Property 9: SmartBar sync reflects all and only session overrides
- For any job_name and field list, the output starts with job_name
- Every field with edit_origin != NONE appears as --{name} {value} in the output
- Every field with edit_origin == NONE does NOT appear in the output
- Fields appear in list order
- Values with whitespace are quoted with double quotes
- When ALL fields have edit_origin NONE, output is just the job name
- The number of -- flags in the output equals the number of fields with edit_origin != NONE

**Validates: Requirements 6.1, 6.2, 6.4**
"""

from __future__ import annotations

import re
import shlex

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.panels.config_table import EditOrigin, FieldDef
from functualize._cli.tui.sync import sync_overrides_to_bar

# =============================================================================
# Strategies
# =============================================================================

# Job names: non-empty identifier-like strings (no spaces, no dashes at start)
_job_name = st.from_regex(r"[a-z][a-z0-9_\-]{0,19}", fullmatch=True)

# Field names: non-empty identifier-like strings (no spaces)
_field_name = st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True)

# Values without whitespace
_value_no_ws = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-./:=",
    ),
    min_size=1,
    max_size=20,
)

# Values with whitespace (contain at least one space or tab)
_value_with_ws = st.builds(
    lambda prefix, ws, suffix: prefix + ws + suffix,
    prefix=_value_no_ws,
    ws=st.sampled_from([" ", "\t", "  "]),
    suffix=_value_no_ws,
)

# Any value: either with or without whitespace
_field_value = st.one_of(_value_no_ws, _value_with_ws)


def _make_field_def(name: str, value: str, origin: EditOrigin) -> FieldDef:
    """Create a FieldDef for testing."""
    return FieldDef(
        name=name,
        value=value,
        source="default",
        edit_origin=origin,
        original_value=value,
        original_source="default",
    )


@st.composite
def _unique_field_list(
    draw: st.DrawFn, min_size: int = 0, max_size: int = 10
) -> list[FieldDef]:
    """Generate a list of FieldDefs with unique names and random edit_origins."""
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    names = draw(st.lists(_field_name, min_size=count, max_size=count, unique=True))
    fields = []
    for name in names:
        value = draw(_field_value)
        origin = draw(st.sampled_from(list(EditOrigin)))
        fields.append(_make_field_def(name, value, origin))
    return fields


@st.composite
def _unique_field_list_all_none(draw: st.DrawFn) -> list[FieldDef]:
    """Generate a list of FieldDefs all with edit_origin == NONE."""
    count = draw(st.integers(min_value=1, max_value=10))
    names = draw(st.lists(_field_name, min_size=count, max_size=count, unique=True))
    fields = []
    for name in names:
        value = draw(_field_value)
        fields.append(_make_field_def(name, value, EditOrigin.NONE))
    return fields


@st.composite
def _unique_field_list_all_overridden(draw: st.DrawFn) -> list[FieldDef]:
    """Generate a list of FieldDefs all with edit_origin != NONE."""
    count = draw(st.integers(min_value=2, max_value=8))
    names = draw(st.lists(_field_name, min_size=count, max_size=count, unique=True))
    fields = []
    for name in names:
        value = draw(_field_value)
        origin = draw(st.sampled_from([EditOrigin.VALUE, EditOrigin.SOURCE]))
        fields.append(_make_field_def(name, value, origin))
    return fields


# =============================================================================
# Property 9: SmartBar sync reflects all and only session overrides
# =============================================================================


@pytest.mark.slow
class TestSmartBarSyncProperties:
    """Property 9: SmartBar sync reflects all and only session overrides.

    **Validates: Requirements 6.1, 6.2, 6.4**
    """

    @given(
        job_name=_job_name,
        fields=_unique_field_list(min_size=0, max_size=10),
    )
    def test_output_starts_with_job_name(
        self, job_name: str, fields: list[FieldDef]
    ) -> None:
        """For any job_name and field list, the output starts with job_name.

        **Validates: Requirements 6.2**
        """
        result = sync_overrides_to_bar(job_name, fields)
        assert result.startswith(job_name)
        # Job name is the first token
        first_token = result.split(" ")[0]
        assert first_token == job_name

    @given(
        job_name=_job_name,
        fields=_unique_field_list(min_size=1, max_size=10),
    )
    def test_overridden_fields_appear_in_output(
        self, job_name: str, fields: list[FieldDef]
    ) -> None:
        """Every field with edit_origin != NONE appears as --{name} in the output.

        **Validates: Requirements 6.1, 6.2**
        """
        result = sync_overrides_to_bar(job_name, fields)

        for f in fields:
            if f.edit_origin != EditOrigin.NONE:
                # Match exact flag token: --{name} followed by space
                pattern = re.compile(rf"--{re.escape(f.name)}\s")
                assert pattern.search(result), (
                    f"Field '{f.name}' with edit_origin={f.edit_origin} "
                    f"should appear in output: {result}"
                )

    @given(
        job_name=_job_name,
        fields=_unique_field_list(min_size=1, max_size=10),
    )
    def test_none_fields_do_not_appear_in_output(
        self, job_name: str, fields: list[FieldDef]
    ) -> None:
        """Every field with edit_origin == NONE does NOT appear in the output.

        **Validates: Requirements 6.1, 6.2**
        """
        result = sync_overrides_to_bar(job_name, fields)

        for f in fields:
            if f.edit_origin == EditOrigin.NONE:
                # Match exact flag token: --{name} followed by space or end
                pattern = re.compile(rf"--{re.escape(f.name)}(?:\s|$)")
                assert not pattern.search(result), (
                    f"Field '{f.name}' with edit_origin=NONE "
                    f"should NOT appear in output: {result}"
                )

    @given(
        job_name=_job_name,
        fields=_unique_field_list_all_overridden(),
    )
    def test_fields_appear_in_list_order(
        self, job_name: str, fields: list[FieldDef]
    ) -> None:
        """Override fields appear in the same order as the field list.

        **Validates: Requirements 6.2**
        """
        result = sync_overrides_to_bar(job_name, fields)

        # Find position of each exact --{name} token in the output
        positions = []
        for f in fields:
            # Match exact flag: --{name} followed by a space (value follows)
            match = re.search(rf"--{re.escape(f.name)}\s", result)
            assert match is not None, f"Field '{f.name}' not found in output: {result}"
            positions.append(match.start())

        # Positions should be strictly increasing
        for i in range(len(positions) - 1):
            assert positions[i] < positions[i + 1], (
                f"Field '{fields[i].name}' at pos {positions[i]} should come "
                f"before '{fields[i + 1].name}' at pos {positions[i + 1]} "
                f"in output: {result}"
            )

    @given(
        job_name=_job_name,
        fields=_unique_field_list(min_size=0, max_size=10),
    )
    def test_whitespace_values_are_quoted(
        self, job_name: str, fields: list[FieldDef]
    ) -> None:
        """Values with whitespace are enclosed in double quotes.

        **Validates: Requirements 6.2**
        """
        result = sync_overrides_to_bar(job_name, fields)

        for f in fields:
            if f.edit_origin != EditOrigin.NONE:
                has_ws = " " in f.value or "\t" in f.value
                if has_ws:
                    # The value should be quoted in the output
                    expected_fragment = f'--{f.name} "{f.value}"'
                    assert expected_fragment in result, (
                        f"Whitespace value for '{f.name}' should be quoted: "
                        f"expected '{expected_fragment}' in '{result}'"
                    )
                else:
                    # The value should NOT be quoted
                    expected_fragment = f"--{f.name} {f.value}"
                    assert expected_fragment in result, (
                        f"Non-whitespace value for '{f.name}' should not be "
                        f"quoted: expected '{expected_fragment}' in '{result}'"
                    )

    @given(
        job_name=_job_name,
        fields=_unique_field_list_all_none(),
    )
    def test_all_none_returns_only_job_name(
        self, job_name: str, fields: list[FieldDef]
    ) -> None:
        """When ALL fields have edit_origin NONE, output is just the job name.

        **Validates: Requirements 6.4**
        """
        result = sync_overrides_to_bar(job_name, fields)
        assert result == job_name

    @given(
        job_name=_job_name,
        fields=_unique_field_list(min_size=0, max_size=10),
    )
    def test_flag_count_matches_override_count(
        self, job_name: str, fields: list[FieldDef]
    ) -> None:
        """The number of -- flags equals the number of fields with edit_origin != NONE.

        **Validates: Requirements 6.1, 6.2**
        """
        result = sync_overrides_to_bar(job_name, fields)

        overridden = [f for f in fields if f.edit_origin != EditOrigin.NONE]

        # Count flags by position, not by matching "--" in the text. These
        # fields are all named (the strategy emits no positionals), so the
        # tokens after the job name alternate flag, value — and a *value* may
        # itself be "--" or "--x", which a textual scan counts as a flag.
        # shlex handles the quoting the emitter applies to values with spaces.
        tokens = shlex.split(result)
        flags = tokens[1::2]

        assert flags == [f"--{f.name}" for f in overridden], (
            f"Expected one flag per overridden field, got {flags} in: {result}"
        )
