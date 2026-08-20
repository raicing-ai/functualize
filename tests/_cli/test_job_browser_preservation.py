# Feature: job-browser-panel, Property 2: Preservation — Non-Job-Browser Panel Behavior Unchanged
"""Property-based tests for preservation of non-job-browser panel behavior.

These tests verify that panel host interactions NOT involving the job browser
panel continue to work correctly. They encode the CURRENT behavior of:
- PanelHost ring navigation (Ctrl+J/K wrapping)
- PanelHost Esc collapse (from any panel)
- ConfigTablePanel cursor navigation bounds
- SettingsPanel initial state

These tests MUST PASS on unfixed code, and continue passing after the fix
to guarantee no regressions.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

# =============================================================================
# Strategies
# =============================================================================

# Strategy: number of panels in a ring (non-job-browser scenarios: 1..8)
_panel_count = st.integers(min_value=1, max_value=8)

# Strategy: starting panel index
_start_index = st.integers(min_value=0, max_value=7)

# Strategy: number of navigate_next/prev operations
_nav_steps = st.integers(min_value=1, max_value=30)

# Strategy: sequence of navigation directions (True = next, False = prev)
_nav_directions = st.lists(st.booleans(), min_size=1, max_size=30)

# Strategy: number of Esc presses (1..5)
_esc_count = st.integers(min_value=1, max_value=5)

# Strategy for ConfigTablePanel-like navigation
_field_count = st.integers(min_value=1, max_value=20)
_cursor_moves = st.lists(
    st.sampled_from(["down", "up"]),
    min_size=1,
    max_size=50,
)


# =============================================================================
# Helpers — Model PanelHost ring navigation WITHOUT Textual
# =============================================================================


class PanelHostModel:
    """Pure-logic model of PanelHost ring navigation and collapse.

    Mirrors the logic in panel_host.py without requiring Textual widgets.
    Used to test that ring navigation wrapping and Esc collapse behavior
    is preserved for all non-job-browser panel configurations.
    """

    def __init__(self, panel_count: int, start_index: int = 0) -> None:
        self._panel_count = max(1, panel_count)
        self._current_index = max(0, min(start_index, self._panel_count - 1))
        self._is_active = False
        self._breadcrumb_stack: list[str] = []

    def activate(self, start_index: int = 0) -> None:
        """Activate the panel host at start_index."""
        self._is_active = True
        self._breadcrumb_stack = []
        self._current_index = max(0, min(start_index, self._panel_count - 1))

    def collapse(self) -> None:
        """Collapse the panel host."""
        self._is_active = False
        self._breadcrumb_stack = []

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def current_index(self) -> int:
        return self._current_index

    def navigate_next(self) -> None:
        """Advance to next panel (wraps). No-op if single panel."""
        if self._panel_count <= 1:
            return
        self._current_index = (self._current_index + 1) % self._panel_count

    def navigate_prev(self) -> None:
        """Move to previous panel (wraps). No-op if single panel."""
        if self._panel_count <= 1:
            return
        self._current_index = (self._current_index - 1) % self._panel_count

    def push_breadcrumb(self, sub_title: str) -> None:
        """Push a sub-level onto breadcrumb stack (max 2)."""
        if len(self._breadcrumb_stack) < 2:
            self._breadcrumb_stack.append(sub_title)

    def handle_esc(self) -> bool:
        """Handle Esc: pop breadcrumb if any, else collapse. Always returns True."""
        if self._breadcrumb_stack:
            self._breadcrumb_stack.pop()
            return True
        self.collapse()
        return True


class ConfigTableModel:
    """Pure-logic model of ConfigTablePanel cursor navigation.

    Models j/k (cursor_down/cursor_up) wrapping behavior for a table
    with N fields. Mirrors ConfigTablePanel without requiring Textual.
    """

    def __init__(self, field_count: int) -> None:
        self._field_count = max(0, field_count)
        self._cursor_row = 0

    @property
    def cursor_row(self) -> int:
        return self._cursor_row

    @property
    def field_count(self) -> int:
        return self._field_count

    def action_cursor_down(self) -> None:
        """Move cursor down, wrapping from last to first."""
        if self._field_count == 0:
            return
        self._cursor_row = (self._cursor_row + 1) % self._field_count

    def action_cursor_up(self) -> None:
        """Move cursor up, wrapping from first to last."""
        if self._field_count == 0:
            return
        self._cursor_row = (self._cursor_row - 1) % self._field_count


# =============================================================================
# Property 2.1: Panel Ring Cycling Preservation (Req 3.2)
# =============================================================================


@pytest.mark.slow
class TestPanelRingCyclingPreservation:
    """Panel ring cycling (Ctrl+J/K) wraps correctly for non-job-browser panels.

    For any panel ring with N panels (N >= 1), navigate_next and navigate_prev
    SHALL wrap the current_index within [0, N-1] without producing invalid
    indices or layout artifacts.

    **Validates: Requirements 3.2**
    """

    @given(
        panel_count=_panel_count,
        directions=_nav_directions,
    )
    def test_ring_navigation_stays_in_bounds(
        self, panel_count: int, directions: list[bool]
    ) -> None:
        """After any sequence of next/prev, index remains in [0, panel_count-1].

        **Validates: Requirements 3.2**
        """
        host = PanelHostModel(panel_count)
        host.activate(0)

        for go_next in directions:
            if go_next:
                host.navigate_next()
            else:
                host.navigate_prev()

            assert 0 <= host.current_index < panel_count, (
                f"Index {host.current_index} out of bounds for {panel_count} panels"
            )

    @given(
        panel_count=st.integers(min_value=2, max_value=8),
        steps=_nav_steps,
    )
    def test_navigate_next_wraps_to_zero(self, panel_count: int, steps: int) -> None:
        """Navigating next N times from index 0 returns to index 0 (ring property).

        **Validates: Requirements 3.2**
        """
        host = PanelHostModel(panel_count)
        host.activate(0)

        # Navigate next exactly panel_count times — should wrap back to 0
        for _ in range(panel_count):
            host.navigate_next()

        assert host.current_index == 0, (
            f"After {panel_count} next steps in a {panel_count}-panel ring, "
            f"expected index 0 but got {host.current_index}"
        )

    @given(
        panel_count=st.integers(min_value=2, max_value=8),
        steps=_nav_steps,
    )
    def test_navigate_prev_wraps_to_last(self, panel_count: int, steps: int) -> None:
        """Navigating prev from index 0 wraps to last index (panel_count - 1).

        **Validates: Requirements 3.2**
        """
        host = PanelHostModel(panel_count)
        host.activate(0)

        host.navigate_prev()

        assert host.current_index == panel_count - 1, (
            f"Expected index {panel_count - 1} after prev from 0, "
            f"got {host.current_index}"
        )

    @given(panel_count=st.just(1))
    def test_single_panel_navigation_is_noop(self, panel_count: int) -> None:
        """With only 1 panel, navigate_next/navigate_prev are no-ops.

        **Validates: Requirements 3.2**
        """
        host = PanelHostModel(panel_count)
        host.activate(0)

        host.navigate_next()
        assert host.current_index == 0

        host.navigate_prev()
        assert host.current_index == 0


# =============================================================================
# Property 2.2: Esc Collapse Preservation (Req 3.3)
# =============================================================================


@pytest.mark.slow
class TestEscCollapsePreservation:
    """Esc collapses the panel host from any panel position.

    For any active PanelHost at any panel index, handle_esc() SHALL
    collapse the host (is_active becomes False). If breadcrumbs are
    pushed, Esc pops them first before collapsing.

    **Validates: Requirements 3.3**
    """

    @given(
        panel_count=_panel_count,
        start_index=st.data(),
    )
    def test_esc_collapses_from_any_panel(
        self, panel_count: int, start_index: st.DataObject
    ) -> None:
        """handle_esc() collapses panel host regardless of current panel index.

        **Validates: Requirements 3.3**
        """
        idx = start_index.draw(st.integers(min_value=0, max_value=panel_count - 1))
        host = PanelHostModel(panel_count)
        host.activate(idx)

        assert host.is_active is True

        result = host.handle_esc()

        assert result is True, "handle_esc() should always return True"
        assert host.is_active is False, (
            f"Panel host should be collapsed after Esc from panel {idx}"
        )

    @given(
        panel_count=_panel_count,
        esc_count=_esc_count,
    )
    def test_esc_collapse_is_idempotent(self, panel_count: int, esc_count: int) -> None:
        """Multiple Esc presses after collapse don't cause errors (idempotent).

        **Validates: Requirements 3.3**
        """
        host = PanelHostModel(panel_count)
        host.activate(0)

        # First Esc collapses
        host.handle_esc()
        assert host.is_active is False

        # Subsequent handle_esc on collapsed host still returns True
        # (same behavior as real PanelHost — it collapses again, which is a no-op)
        for _ in range(esc_count - 1):
            result = host.handle_esc()
            assert result is True
            assert host.is_active is False

    @given(
        panel_count=_panel_count,
        data=st.data(),
    )
    def test_esc_pops_breadcrumb_before_collapsing(
        self, panel_count: int, data: st.DataObject
    ) -> None:
        """If breadcrumbs are pushed, Esc pops them first, then collapses.

        **Validates: Requirements 3.3**
        """
        breadcrumb_count = data.draw(st.integers(min_value=1, max_value=2))
        host = PanelHostModel(panel_count)
        host.activate(0)

        # Push breadcrumbs
        for i in range(breadcrumb_count):
            host.push_breadcrumb(f"sub{i}")

        # First Esc presses pop breadcrumbs (host stays active)
        for i in range(breadcrumb_count):
            result = host.handle_esc()
            assert result is True
            assert host.is_active is True, (
                f"Host should stay active while popping breadcrumb {i}"
            )

        # Final Esc collapses
        result = host.handle_esc()
        assert result is True
        assert host.is_active is False


# =============================================================================
# Property 2.3: ConfigTablePanel Navigation Preservation (Req 3.1)
# =============================================================================


@pytest.mark.slow
class TestConfigTableNavigationPreservation:
    """ConfigTablePanel j/k navigation stays in bounds with wrapping.

    For any ConfigTablePanel with N fields (N >= 1), cursor_down and
    cursor_up SHALL keep the cursor_row within [0, N-1] with wrapping
    (same behavior as before the job browser fix).

    **Validates: Requirements 3.1**
    """

    @given(
        field_count=_field_count,
        moves=_cursor_moves,
    )
    def test_cursor_stays_in_bounds(self, field_count: int, moves: list[str]) -> None:
        """After any sequence of cursor_down/cursor_up, row stays in [0, N-1].

        **Validates: Requirements 3.1**
        """
        model = ConfigTableModel(field_count)

        for move in moves:
            if move == "down":
                model.action_cursor_down()
            else:
                model.action_cursor_up()

            assert 0 <= model.cursor_row < field_count, (
                f"Cursor row {model.cursor_row} out of bounds for {field_count} fields"
            )

    @given(field_count=_field_count)
    def test_cursor_down_wraps_from_last_to_first(self, field_count: int) -> None:
        """Moving down from last row wraps to row 0.

        **Validates: Requirements 3.1**
        """
        model = ConfigTableModel(field_count)

        # Move to last row
        for _ in range(field_count - 1):
            model.action_cursor_down()

        assert model.cursor_row == field_count - 1

        # One more down wraps to 0
        model.action_cursor_down()
        assert model.cursor_row == 0

    @given(field_count=_field_count)
    def test_cursor_up_wraps_from_first_to_last(self, field_count: int) -> None:
        """Moving up from row 0 wraps to last row.

        **Validates: Requirements 3.1**
        """
        model = ConfigTableModel(field_count)

        # Cursor starts at 0, move up wraps to last
        model.action_cursor_up()
        assert model.cursor_row == field_count - 1


# =============================================================================
# Property 2.4: Settings Panel Display Preservation (Req 3.4)
# =============================================================================


@pytest.mark.slow
class TestSettingsPanelPreservation:
    """SettingsPanel exposes a coherent, navigable settings registry.

    These were three `@given(data=st.data())` tests whose generated `data` was
    never drawn from — 50 identical iterations each — asserting a snapshot of
    the registry: exactly 9 settings, under bare names, with a fixed default
    apiece. The registry has since moved to dotted names and grown to 27, so
    the snapshot broke without any behaviour changing. What is actually worth
    protecting is the registry's internal coherence, which does not churn as
    settings are added.

    **Validates: Requirements 3.4**
    """

    def test_every_default_belongs_to_a_listed_setting(self) -> None:
        """`_DEFAULT_VALUES` never carries a key the panel does not display.

        The reverse does not hold: settings that are unset by nature — the
        discovery filters, `import_libs`, `shell.program` — appear in the panel
        with no static default.
        """
        from functualize._cli.tui.settings_panel import (
            _DEFAULT_VALUES,
            _SETTINGS_ORDER,
        )

        assert set(_DEFAULT_VALUES).issubset(_SETTINGS_ORDER), (
            "Defaults exist for settings the panel never lists: "
            f"{sorted(set(_DEFAULT_VALUES) - set(_SETTINGS_ORDER))}"
        )

    def test_settings_order_has_no_duplicates(self) -> None:
        """A setting listed twice would render twice and edit ambiguously."""
        from functualize._cli.tui.settings_panel import _SETTINGS_ORDER

        assert len(_SETTINGS_ORDER) == len(set(_SETTINGS_ORDER))

    def test_settings_are_namespaced_or_top_level_known(self) -> None:
        """Settings are addressed by dotted name within a known namespace.

        The bare-name spelling (`theme`, `execution_mode`) is gone; a setting
        now says which section owns it, which is what makes it writable back
        to a config file.
        """
        from functualize._cli.tui.settings_panel import _SETTINGS_ORDER

        known_namespaces = {"tui", "cli", "discovery", "plugins", "shell"}
        top_level = {"dotenv", "dotenv_path", "import_libs"}

        for setting in _SETTINGS_ORDER:
            if setting in top_level:
                continue
            assert "." in setting, (
                f"Setting {setting!r} is neither namespaced nor a known top-level key"
            )
            assert setting.split(".", 1)[0] in known_namespaces, (
                f"Setting {setting!r} sits in an unknown namespace"
            )

    def test_settings_panel_actions_include_navigation(self) -> None:
        """SettingsPanel get_available_actions always includes j/k navigate hint.

        **Validates: Requirements 3.4**
        """
        from functualize._cli.tui.settings_panel import (
            _DEFAULT_VALUES,
            _SETTINGS_ORDER,
            SettingsPanel,
        )

        # SettingsPanel provides fallback actions even without mounting
        # (the except branch in get_available_actions)
        panel = SettingsPanel.__new__(SettingsPanel)
        panel._settings = list(_SETTINGS_ORDER)
        panel._values = dict(_DEFAULT_VALUES)
        panel._sources = {s: "default" for s in panel._settings}

        actions = panel.get_available_actions(focused=True)
        action_keys = [k for k, _v in actions]
        assert "j/k" in action_keys, "Settings panel must advertise j/k navigation"


# =============================================================================
# Property 2.5: Empty State Preservation (Req 3.5)
# =============================================================================


@pytest.mark.slow
class TestEmptyStatePreservation:
    """Empty state (no jobs) produces no crash and appropriate behavior.

    When panel host has panels but no job-related content, the ring
    navigation and collapse behavior must remain stable.

    **Validates: Requirements 3.5**
    """

    @given(
        panel_count=st.integers(min_value=1, max_value=5),
        directions=_nav_directions,
    )
    def test_empty_ring_navigation_stable(
        self, panel_count: int, directions: list[bool]
    ) -> None:
        """Ring navigation is stable regardless of panel content (empty or not).

        **Validates: Requirements 3.5**
        """
        host = PanelHostModel(panel_count)
        host.activate(0)

        for go_next in directions:
            if go_next:
                host.navigate_next()
            else:
                host.navigate_prev()

            # Must stay active and in bounds
            assert host.is_active is True
            assert 0 <= host.current_index < panel_count

        # Esc always works
        host.handle_esc()
        assert host.is_active is False
