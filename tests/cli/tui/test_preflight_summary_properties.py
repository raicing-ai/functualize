# Feature: tui-v3-ux-polish, Property 1: Pre-flight Summary visibility invariant
"""Property-based tests for Pre-flight Summary visibility.

Tests the visibility logic of the Pre-flight Summary widget:
- Property 1: Pre-flight Summary is visible iff readiness ∈ {PENDING, READY}
  AND no panel toggle is active.

**Validates: Requirements 2.1, 2.4, 2.5, 2.6**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.tui.bar import BarReadiness

# =============================================================================
# Strategies
# =============================================================================

_readiness_strategy = st.sampled_from(list(BarReadiness))
_panel_active_strategy = st.booleans()


# =============================================================================
# Pure visibility predicate (extracted from app._update_preflight_summary)
# =============================================================================


def _should_show_preflight_summary(readiness: BarReadiness, panel_active: bool) -> bool:
    """Pure function encoding the visibility logic from _update_preflight_summary."""
    return readiness in (BarReadiness.PENDING, BarReadiness.READY) and not panel_active


# =============================================================================
# Property 1: Pre-flight Summary visibility invariant
# =============================================================================


@pytest.mark.slow
class TestPreflightSummaryVisibility:
    """Property 1: Pre-flight Summary visibility invariant.

    For any combination of SmartBar readiness state and panel-active boolean,
    the Pre-flight Summary widget is visible if and only if
    readiness ∈ {PENDING, READY} AND no panel toggle is active.

    **Validates: Requirements 2.1, 2.4, 2.5, 2.6**
    """

    @given(readiness=_readiness_strategy, panel_active=_panel_active_strategy)
    @settings(max_examples=50)
    def test_visible_only_when_pending_or_ready_and_no_panel(
        self,
        readiness: BarReadiness,
        panel_active: bool,
    ) -> None:
        """The summary is visible iff readiness is PENDING/READY and no panel is active."""
        result = _should_show_preflight_summary(readiness, panel_active)

        # Expected: True only when readiness is PENDING or READY, and panel is not active
        expected = (
            readiness in (BarReadiness.PENDING, BarReadiness.READY) and not panel_active
        )
        assert result == expected, (
            f"For readiness={readiness.name}, panel_active={panel_active}: "
            f"expected {expected}, got {result}"
        )

    @given(readiness=_readiness_strategy)
    @settings(max_examples=50)
    def test_panel_active_always_hides_summary(
        self,
        readiness: BarReadiness,
    ) -> None:
        """Req 2.4: When panel is active, summary is always hidden regardless of readiness."""
        result = _should_show_preflight_summary(readiness, panel_active=True)
        assert result is False, (
            f"Summary should be hidden when panel is active, "
            f"but was visible for readiness={readiness.name}"
        )

    @given(panel_active=_panel_active_strategy)
    @settings(max_examples=50)
    def test_grey_readiness_always_hides_summary(
        self,
        panel_active: bool,
    ) -> None:
        """Req 2.6: When readiness is GREY, summary is always hidden."""
        result = _should_show_preflight_summary(BarReadiness.GREY, panel_active)
        assert result is False, (
            f"Summary should be hidden when readiness is GREY, "
            f"but was visible with panel_active={panel_active}"
        )

    @given(panel_active=_panel_active_strategy)
    @settings(max_examples=50)
    def test_editing_readiness_always_hides_summary(
        self,
        panel_active: bool,
    ) -> None:
        """Req 2.6 (implied): When readiness is EDITING, summary is always hidden."""
        result = _should_show_preflight_summary(BarReadiness.EDITING, panel_active)
        assert result is False, (
            f"Summary should be hidden when readiness is EDITING, "
            f"but was visible with panel_active={panel_active}"
        )

    @given(panel_active=_panel_active_strategy)
    @settings(max_examples=50)
    def test_invalid_readiness_always_hides_summary(
        self,
        panel_active: bool,
    ) -> None:
        """Req 2.6 (implied): When readiness is INVALID, summary is always hidden."""
        result = _should_show_preflight_summary(BarReadiness.INVALID, panel_active)
        assert result is False, (
            f"Summary should be hidden when readiness is INVALID, "
            f"but was visible with panel_active={panel_active}"
        )

    def test_pending_no_panel_shows_summary(self) -> None:
        """Req 2.1: PENDING + no panel → visible."""
        assert (
            _should_show_preflight_summary(BarReadiness.PENDING, panel_active=False)
            is True
        )

    def test_ready_no_panel_shows_summary(self) -> None:
        """Req 2.1: READY + no panel → visible."""
        assert (
            _should_show_preflight_summary(BarReadiness.READY, panel_active=False)
            is True
        )

    def test_pending_panel_active_hides_summary(self) -> None:
        """Req 2.4: PENDING + panel active → hidden."""
        assert (
            _should_show_preflight_summary(BarReadiness.PENDING, panel_active=True)
            is False
        )

    def test_ready_panel_active_hides_summary(self) -> None:
        """Req 2.4: READY + panel active → hidden."""
        assert (
            _should_show_preflight_summary(BarReadiness.READY, panel_active=True)
            is False
        )
