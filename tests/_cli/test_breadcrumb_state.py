"""Property-based tests for BreadcrumbState rendering.

# Feature: tui-architecture-v2, Property 3: Breadcrumb rendering is well-formed

Tests BreadcrumbState.render() from functualize._cli.tui.models.ring_models:
- Property 3: Breadcrumb rendering is well-formed

**Validates: Requirements 2.2, 2.3, 2.4**
"""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.models.ring_models import BreadcrumbState

# =============================================================================
# Strategies
# =============================================================================

# Valid type prefixes per Requirement 2.2
_type_prefix_strategy = st.sampled_from(["D", "R", "E"])

# Non-empty title text (printable, no newlines)
_title_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"), blacklist_characters="\n\r"
    ),
    min_size=1,
    max_size=30,
)

# Sub-level text (non-empty, no newlines)
_sub_level_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"), blacklist_characters="\n\r"
    ),
    min_size=1,
    max_size=30,
)


@st.composite
def _breadcrumb_state(draw: st.DrawFn) -> BreadcrumbState:
    """Generate a valid BreadcrumbState with constrained inputs."""
    type_prefix = draw(_type_prefix_strategy)
    total = draw(st.integers(min_value=1, max_value=100))
    position = draw(st.integers(min_value=1, max_value=total))
    title = draw(_title_strategy)
    num_sub_levels = draw(st.integers(min_value=0, max_value=2))
    sub_levels = tuple(
        draw(
            st.lists(
                _sub_level_strategy, min_size=num_sub_levels, max_size=num_sub_levels
            )
        )
    )
    return BreadcrumbState(
        type_prefix=type_prefix,
        position=position,
        total=total,
        title=title,
        sub_levels=sub_levels,
    )


# =============================================================================
# Property 3: Breadcrumb rendering is well-formed
# =============================================================================


@pytest.mark.slow
class TestBreadcrumbRenderingWellFormed:
    """Property 3: Breadcrumb rendering is well-formed.

    For any valid BreadcrumbState (type_prefix in {"D", "R", "E"},
    position in [1, total], total >= 1, sub_levels length <= 2),
    calling render() should produce a string matching the pattern
    [TYPE:N/M] Title optionally followed by ' > SubLevel1' and ' > SubLevel2',
    where the title and all sub-levels appear in order.

    **Validates: Requirements 2.2, 2.3, 2.4**
    """

    @given(state=_breadcrumb_state())
    def test_render_starts_with_bracket_prefix(self, state: BreadcrumbState) -> None:
        """Rendered output starts with [TYPE:N/M] format (Req 2.2, 2.3)."""
        rendered = state.render()
        prefix_pattern = re.compile(r"^\[([DRE]):(\d+)/(\d+)\] ")
        match = prefix_pattern.match(rendered)
        assert match is not None, (
            f"Rendered output doesn't match prefix pattern: {rendered!r}"
        )
        assert match.group(1) == state.type_prefix
        assert int(match.group(2)) == state.position
        assert int(match.group(3)) == state.total

    @given(state=_breadcrumb_state())
    def test_render_contains_title_after_prefix(self, state: BreadcrumbState) -> None:
        """Rendered output contains the title immediately after [TYPE:N/M] (Req 2.3)."""
        rendered = state.render()
        expected_prefix = f"[{state.type_prefix}:{state.position}/{state.total}] "
        assert rendered.startswith(expected_prefix)
        remainder = rendered[len(expected_prefix) :]
        # Title should be the start of the remainder
        assert remainder.startswith(state.title), (
            f"Title {state.title!r} not found after prefix in: {rendered!r}"
        )

    @given(state=_breadcrumb_state())
    def test_render_sub_levels_separated_by_chevron(
        self, state: BreadcrumbState
    ) -> None:
        """Sub-levels are appended with ' > ' separator (Req 2.4)."""
        rendered = state.render()
        if not state.sub_levels:
            # No sub-levels: output is just [TYPE:N/M] Title
            expected = (
                f"[{state.type_prefix}:{state.position}/{state.total}] {state.title}"
            )
            assert rendered == expected
        else:
            # Sub-levels present: each separated by ' > '
            expected_suffix = " > ".join(state.sub_levels)
            expected = (
                f"[{state.type_prefix}:{state.position}/{state.total}] "
                f"{state.title} > {expected_suffix}"
            )
            assert rendered == expected

    @given(state=_breadcrumb_state())
    def test_render_preserves_order(self, state: BreadcrumbState) -> None:
        """Title and sub-levels appear in correct order in the output (Req 2.4)."""
        rendered = state.render()
        # Find positions of title and each sub-level
        title_pos = rendered.find(state.title)
        assert title_pos >= 0, f"Title {state.title!r} not found in: {rendered!r}"

        # Each sub-level should appear after the title
        prev_pos = title_pos
        for sub_level in state.sub_levels:
            sub_pos = rendered.find(sub_level, prev_pos + 1)
            assert sub_pos > prev_pos, (
                f"Sub-level {sub_level!r} not found after position {prev_pos} in: {rendered!r}"
            )
            prev_pos = sub_pos
