# Feature: tui-v3-integration, Property 4: Bar readiness correctly reflects token state
# Feature: tui-v3-integration, Property 2: SmartBar state round-trip across INSERT mode
"""Property-based tests for SmartBar (BarReadiness evaluation and state round-trip).

Tests SmartBar from functualize._cli.tui.bar:
- Property 4: Bar readiness correctly reflects token state
- Property 2: SmartBar state round-trip across INSERT mode

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.7, 4.1, 4.3, 4.4**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from textual.app import App, ComposeResult

from functualize._cli.tui.bar import BarReadiness, SmartBar

# =============================================================================
# Strategies
# =============================================================================

# Identifiers for job names and field names: lowercase alpha strings of reasonable length
_identifier = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_"),
    min_size=1,
    max_size=15,
)

# Token text: non-empty strings without leading dashes (to avoid accidental --flag)
_plain_token = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
).filter(lambda s: not s.startswith("--"))

# Flag token: always starts with "--" followed by identifier
_flag_token = _identifier.map(lambda name: f"--{name}")

# Value token: non-empty string for flag values
_value_token = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=15,
)


@st.composite
def _empty_tokens(draw: st.DrawFn) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Generate scenario: empty token list. Expected: GREY."""
    job_names = draw(st.lists(_identifier, min_size=0, max_size=5))
    registry: dict[str, list[str]] = {name: [] for name in job_names}
    return [], job_names, registry


@st.composite
def _unknown_command_tokens(
    draw: st.DrawFn,
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Generate scenario: first token not in job_names. Expected: GREY."""
    job_names = draw(st.lists(_identifier, min_size=1, max_size=5))
    # Generate a command that is NOT in job_names
    command = draw(_identifier.filter(lambda c: c not in job_names))
    extra_tokens = draw(st.lists(_plain_token, min_size=0, max_size=3))
    tokens = [command, *extra_tokens]
    registry: dict[str, list[str]] = {name: [] for name in job_names}
    return tokens, job_names, registry


@st.composite
def _known_job_missing_fields(
    draw: st.DrawFn,
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Generate scenario: known job with at least one missing required field. Expected: PENDING."""
    # Create a job with required fields
    job_name = draw(_identifier)
    required_fields = draw(st.lists(_identifier, min_size=1, max_size=6, unique=True))

    # Provide some but not all required fields as --flag value pairs
    if len(required_fields) == 1:
        # If only one field, provide none of them
        provided = []
    else:
        # Provide a strict subset
        num_provided = draw(
            st.integers(min_value=0, max_value=len(required_fields) - 1)
        )
        provided = required_fields[:num_provided]

    tokens = [job_name]
    for field in provided:
        tokens.append(f"--{field}")
        tokens.append(draw(_value_token))

    job_names = [job_name]
    registry: dict[str, list[str]] = {job_name: required_fields}
    return tokens, job_names, registry


@st.composite
def _known_job_all_satisfied(
    draw: st.DrawFn,
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Generate scenario: known job with all required fields satisfied. Expected: READY."""
    job_name = draw(_identifier)
    required_fields = draw(st.lists(_identifier, min_size=0, max_size=5, unique=True))

    tokens = [job_name]
    for field in required_fields:
        tokens.append(f"--{field}")
        tokens.append(draw(_value_token))

    job_names = [job_name]
    registry: dict[str, list[str]] = {job_name: required_fields}
    return tokens, job_names, registry


# Strategy for bar text values (for round-trip testing)
_bar_value = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=0,
    max_size=50,
)

_placeholder_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=30,
)


# =============================================================================
# Property 4: Bar readiness correctly reflects token state
# =============================================================================


@pytest.mark.slow
class TestBarReadinessReflectsTokenState:
    """Property 4: Bar readiness correctly reflects token state.

    For any token list and job registry, evaluate() produces:
    - empty tokens → GREY
    - tokens[0] not in job_names → GREY
    - tokens[0] in job_names with missing required args → PENDING
    - tokens[0] in job_names with all required args satisfied → READY

    The result is deterministic for the same inputs.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.7**
    """

    @given(data=_empty_tokens())
    @settings(max_examples=50)
    def test_empty_tokens_produce_grey(
        self, data: tuple[list[str], list[str], dict[str, list[str]]]
    ) -> None:
        """Req 3.1: Empty tokens → GREY with 'Type a command'."""
        tokens, job_names, registry = data
        bar = SmartBar(id="test")

        result = bar.evaluate(tokens, job_names, lambda j: registry.get(j, []))

        assert result is BarReadiness.GREY
        assert bar.readiness is BarReadiness.GREY

    @given(data=_unknown_command_tokens())
    @settings(max_examples=50)
    def test_unknown_command_produces_grey(
        self, data: tuple[list[str], list[str], dict[str, list[str]]]
    ) -> None:
        """Req 3.2: Unknown first token → GREY with 'Unknown: {token}'."""
        tokens, job_names, registry = data
        bar = SmartBar(id="test")

        result = bar.evaluate(tokens, job_names, lambda j: registry.get(j, []))

        assert result is BarReadiness.GREY
        assert bar.readiness is BarReadiness.GREY

    @given(data=_known_job_missing_fields())
    @settings(max_examples=50)
    def test_missing_required_fields_produce_pending(
        self, data: tuple[list[str], list[str], dict[str, list[str]]]
    ) -> None:
        """Req 3.3: Known job + missing required → PENDING."""
        tokens, job_names, registry = data
        bar = SmartBar(id="test")

        result = bar.evaluate(tokens, job_names, lambda j: registry.get(j, []))

        assert result is BarReadiness.PENDING
        assert bar.readiness is BarReadiness.PENDING

    @given(data=_known_job_all_satisfied())
    @settings(max_examples=50)
    def test_all_satisfied_produces_ready(
        self, data: tuple[list[str], list[str], dict[str, list[str]]]
    ) -> None:
        """Req 3.4: Known job + all required satisfied → READY."""
        tokens, job_names, registry = data
        bar = SmartBar(id="test")

        result = bar.evaluate(tokens, job_names, lambda j: registry.get(j, []))

        assert result is BarReadiness.READY
        assert bar.readiness is BarReadiness.READY

    @given(
        data=st.one_of(
            _empty_tokens(),
            _unknown_command_tokens(),
            _known_job_missing_fields(),
            _known_job_all_satisfied(),
        )
    )
    @settings(max_examples=100)
    def test_evaluate_is_deterministic(
        self, data: tuple[list[str], list[str], dict[str, list[str]]]
    ) -> None:
        """Req 3.7: Same inputs always produce same result."""
        tokens, job_names, registry = data

        bar1 = SmartBar(id="test1")
        bar2 = SmartBar(id="test2")

        result1 = bar1.evaluate(tokens, job_names, lambda j: registry.get(j, []))
        result2 = bar2.evaluate(tokens, job_names, lambda j: registry.get(j, []))

        assert result1 is result2


# =============================================================================
# Property 2: SmartBar state round-trip across INSERT mode
# =============================================================================


class _BarTestApp(App):
    """Minimal test app hosting a SmartBar for async testing."""

    def compose(self) -> ComposeResult:
        yield SmartBar(id="bar")


@pytest.mark.slow
class TestSmartBarStateRoundTrip:
    """Property 2: SmartBar state round-trip across INSERT mode.

    For any SmartBar state (value, cursor_position, placeholder), calling
    save_state() then restore_state() SHALL produce a bar state identical
    to the original.

    Additionally, restore_state() without prior save_state() raises RuntimeError.

    **Validates: Requirements 4.1, 4.3, 4.4**
    """

    @given(
        value=_bar_value,
        placeholder=_placeholder_text,
    )
    @settings(max_examples=50)
    async def test_save_restore_round_trip(
        self,
        value: str,
        placeholder: str,
    ) -> None:
        """Req 4.1, 4.3: save then restore produces identical state."""
        async with _BarTestApp().run_test() as pilot:
            bar = pilot.app.query_one("#bar", SmartBar)

            # Set initial state
            bar.value = value
            bar.placeholder = placeholder
            # Cursor position is clamped to [0, len(value)]
            expected_cursor = len(value)  # Setting value moves cursor to end

            # Save state
            bar.save_state()

            # Modify state (simulating INSERT mode)
            bar.value = "modified_value_for_insert"
            bar.placeholder = "Edit: some_field"
            bar.enter_edit_mode("test_field", "edit_value", "hint")

            # Restore state
            bar.restore_state()

            # Assert round-trip
            assert bar.value == value, f"Expected value='{value}', got '{bar.value}'"
            assert bar.placeholder == placeholder, (
                f"Expected placeholder='{placeholder}', got '{bar.placeholder}'"
            )
            assert bar.cursor_position == expected_cursor, (
                f"Expected cursor_position={expected_cursor}, got {bar.cursor_position}"
            )

    @given(
        value=_bar_value,
        cursor_offset=st.integers(min_value=0, max_value=50),
        placeholder=_placeholder_text,
    )
    @settings(max_examples=50)
    async def test_cursor_position_preserved_on_round_trip(
        self,
        value: str,
        cursor_offset: int,
        placeholder: str,
    ) -> None:
        """Req 4.1: save_state captures cursor_position correctly."""
        async with _BarTestApp().run_test() as pilot:
            bar = pilot.app.query_one("#bar", SmartBar)

            # Set value first, then position cursor
            bar.value = value
            # Clamp cursor to valid range
            target_cursor = min(cursor_offset, len(value))
            bar.cursor_position = target_cursor
            bar.placeholder = placeholder

            # Save
            bar.save_state()

            # Modify everything
            bar.value = "completely_different"
            bar.cursor_position = 0
            bar.placeholder = "Edit: field"

            # Restore
            bar.restore_state()

            assert bar.cursor_position == target_cursor, (
                f"Expected cursor at {target_cursor}, got {bar.cursor_position}"
            )

    async def test_restore_without_save_raises_runtime_error(self) -> None:
        """Req 4.4: restore_state() without save raises RuntimeError."""
        async with _BarTestApp().run_test() as pilot:
            bar = pilot.app.query_one("#bar", SmartBar)

            with pytest.raises(
                RuntimeError, match="restore_state.*without prior save_state"
            ):
                bar.restore_state()
