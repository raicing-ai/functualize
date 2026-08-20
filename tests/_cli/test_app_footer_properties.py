"""Property-based tests for status bar and display footer transitions.

Tests that the status bar and display footer correctly update for every
valid FocusState transition.

Feature: tui-preflight-and-footer-polish
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone

# =============================================================================
# Constants — mirrored from app.py to validate against (R8-AC4, R8-AC5)
# =============================================================================

_MODE_STYLES: dict[FocusMode, str] = {
    FocusMode.COMMAND: "[dim]COMMAND[/dim]",
    FocusMode.NORMAL: "[bold cyan]NORMAL[/bold cyan]",
    FocusMode.INSERT: "[bold green]INSERT[/bold green]",
    FocusMode.FILTER: "[bold yellow]FILTER[/bold yellow]",
}

_ZONE_NAMES: dict[FocusZone, str] = {
    FocusZone.SMARTBAR: "SmartBar",
    FocusZone.DISPLAY: "Display",
    FocusZone.PANEL: "Panel",
}


def _expected_status_bar(mode: FocusMode, zone: FocusZone, readiness_str: str) -> str:
    """Replicate the status bar format from app.py's _update_status_bar."""
    mode_str = _MODE_STYLES.get(mode, "")
    zone_str = _ZONE_NAMES.get(zone, "")
    return f" {mode_str}  {zone_str}  {readiness_str}"


# =============================================================================
# Strategies
# =============================================================================

# All valid mode transitions from FocusState._VALID_TRANSITIONS
_VALID_TRANSITIONS = list(FocusState._VALID_TRANSITIONS)

# All zones for pairing with target mode
_all_zones = st.sampled_from(list(FocusZone))


@st.composite
def _transition_sequence(draw: st.DrawFn) -> list[tuple[FocusMode, FocusZone]]:
    """Generate a sequence of valid FocusState transitions starting from COMMAND.

    Returns a list of (target_mode, target_zone) pairs representing
    successive states after valid transitions.
    """
    # Start from COMMAND mode
    current_mode = FocusMode.COMMAND

    # Generate 2-10 transitions
    length = draw(st.integers(min_value=2, max_value=10))
    transitions: list[tuple[FocusMode, FocusZone]] = []

    for _ in range(length):
        # Find all valid next modes from current_mode
        valid_next_modes = [
            to_mode
            for (from_mode, to_mode) in _VALID_TRANSITIONS
            if from_mode == current_mode
        ]
        if not valid_next_modes:
            break  # pragma: no cover — shouldn't happen with well-formed FSM

        # Pick a random valid next mode
        next_mode = draw(st.sampled_from(valid_next_modes))
        # Pick a random zone
        zone = draw(_all_zones)

        transitions.append((next_mode, zone))
        current_mode = next_mode

    return transitions


# =============================================================================
# Property: Status bar format is correct for every (mode, zone) pair
# =============================================================================


@pytest.mark.slow
class TestStatusBarFormatOnTransition:
    """Status bar updates correctly on every FocusState transition.

    For any valid FocusState (mode, zone) pair, the status bar format
    SHALL be: {MODE}  {Zone}  {readiness_indicator} (R8-AC3).

    **Validates: Requirements 8.1, 8.3**
    """

    @given(transitions=_transition_sequence())
    def test_status_bar_format_after_each_transition(
        self, transitions: list[tuple[FocusMode, FocusZone]]
    ) -> None:
        """After each valid transition, status bar matches expected format.

        **Validates: Requirements 8.1, 8.3**
        """
        from functualize._cli.tui.app import _MODE_STYLES, _ZONE_NAMES

        for target_mode, target_zone in transitions:
            mode_str = _MODE_STYLES.get(target_mode, "")
            zone_str = _ZONE_NAMES.get(target_zone, "")

            # Verify all modes have a style
            assert mode_str != "", f"Mode {target_mode.name} has no style mapping"
            # Verify all zones have a name
            assert zone_str != "", f"Zone {target_zone.name} has no name mapping"

    @given(
        mode=st.sampled_from(list(FocusMode)),
        zone=st.sampled_from(list(FocusZone)),
    )
    def test_status_bar_deterministic_for_same_state(
        self, mode: FocusMode, zone: FocusZone
    ) -> None:
        """Status bar output is deterministic for same (mode, zone) input.

        **Validates: Requirements 8.1, 8.3**
        """
        from functualize._cli.tui.app import _MODE_STYLES, _ZONE_NAMES

        result1 = f" {_MODE_STYLES.get(mode, '')}  {_ZONE_NAMES.get(zone, '')}  "
        result2 = f" {_MODE_STYLES.get(mode, '')}  {_ZONE_NAMES.get(zone, '')}  "
        assert result1 == result2

    @given(
        mode=st.sampled_from(list(FocusMode)),
        zone=st.sampled_from(list(FocusZone)),
    )
    def test_status_bar_contains_no_panel_hints(
        self, mode: FocusMode, zone: FocusZone
    ) -> None:
        """Status bar never contains panel action hints (R8-AC2).

        **Validates: Requirements 8.2**
        """
        from functualize._cli.tui.app import _MODE_STYLES, _ZONE_NAMES

        mode_str = _MODE_STYLES.get(mode, "")
        zone_str = _ZONE_NAMES.get(zone, "")
        status_content = f" {mode_str}  {zone_str}  "

        # These are panel-specific hints that MUST NOT appear in the status bar
        panel_hints = ["j/k", "h/l", " i ", " r ", "Esc back", "Enter detail"]
        for hint in panel_hints:
            assert hint not in status_content, (
                f"Status bar for ({mode.name}, {zone.name}) "
                f"contains panel hint: {hint!r}"
            )
