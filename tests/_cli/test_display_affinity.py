# Feature: tui-architecture-v2, Property 14: Display affinity matching
"""Property-based tests for display affinity matching.

Tests is_display_related and find_related_displays from
functualize._cli.tui.display_affinity:
- Property 14: Display affinity matching

**Validates: Requirements 6.1, 6.2, 6.10**
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.display_affinity import (
    find_related_displays,
    is_display_related,
)

# =============================================================================
# Mock DisplayProvider
# =============================================================================


@dataclass
class MockDisplayProvider:
    """Minimal mock implementing DisplayProvider interface for testing."""

    display_id: str = "mock-display"
    display_title: str = "Mock Display"
    display_priority: int = 10
    refresh_interval: float | None = None
    linked_jobs: list[str] | None = None
    linked_groups: list[str] | None = None
    _should_show: bool = True

    def should_show(self, cwd: Path, app: Any) -> bool:
        return self._should_show

    def compose_display(self) -> Any:
        return []

    def refresh(self) -> None:
        pass

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        return []


# =============================================================================
# Strategies
# =============================================================================

# A single name segment: lowercase letters, 2-8 chars
_name_segment = st.text(
    alphabet=st.characters(categories=("Ll",), min_codepoint=97, max_codepoint=122),
    min_size=2,
    max_size=8,
)

# A qualified job name like "infra.aws.deploy" (1 to 4 segments joined by dots)
_qualified_job_name = st.lists(_name_segment, min_size=1, max_size=4).map(
    lambda parts: ".".join(parts)
)


@st.composite
def _provider_with_linked_jobs(draw: st.DrawFn) -> MockDisplayProvider:
    """Generate a provider with random linked_jobs list."""
    jobs = draw(st.lists(_qualified_job_name, min_size=1, max_size=5))
    return MockDisplayProvider(linked_jobs=jobs, linked_groups=None)


@st.composite
def _provider_with_linked_groups(draw: st.DrawFn) -> MockDisplayProvider:
    """Generate a provider with random linked_groups list."""
    # Make some groups dotted (multi-segment)
    dotted_groups = draw(
        st.lists(
            st.lists(_name_segment, min_size=1, max_size=3).map(
                lambda parts: ".".join(parts)
            ),
            min_size=1,
            max_size=5,
        )
    )
    return MockDisplayProvider(linked_jobs=None, linked_groups=dotted_groups)


# =============================================================================
# Property 14: Display affinity matching
# =============================================================================


@pytest.mark.slow
class TestDisplayAffinityMatching:
    """Property 14: Display affinity matching.

    For any DisplayProvider with linked_jobs and linked_groups, and any
    qualified job name, the display is considered "related" if the exact
    job name appears in linked_jobs OR the job's group (or any ancestor
    group segment) appears in linked_groups. A display that returns
    should_show(cwd)=False is never activated by job linking alone.

    **Validates: Requirements 6.1, 6.2, 6.10**
    """

    @given(job_name=_qualified_job_name)
    def test_exact_job_in_linked_jobs_is_related(self, job_name: str) -> None:
        """A provider with the exact job_name in linked_jobs is related."""
        provider = MockDisplayProvider(linked_jobs=[job_name], linked_groups=None)
        assert is_display_related(provider, job_name) is True

    @given(
        job_name=_qualified_job_name,
        extra_jobs=st.lists(_qualified_job_name, min_size=0, max_size=5),
    )
    def test_exact_job_among_others_is_related(
        self, job_name: str, extra_jobs: list[str]
    ) -> None:
        """A provider with the job_name among other linked_jobs is related."""
        all_jobs = extra_jobs + [job_name]
        provider = MockDisplayProvider(linked_jobs=all_jobs, linked_groups=None)
        assert is_display_related(provider, job_name) is True

    @given(
        job_name=_qualified_job_name,
        linked_jobs=st.lists(_qualified_job_name, min_size=1, max_size=5),
    )
    def test_job_not_in_linked_jobs_not_related(
        self, job_name: str, linked_jobs: list[str]
    ) -> None:
        """A provider whose linked_jobs do NOT contain the job_name is not related
        (unless linked_groups match)."""
        # Filter out the exact job_name from linked_jobs to ensure no match
        filtered_jobs = [j for j in linked_jobs if j != job_name]
        if not filtered_jobs:
            filtered_jobs = ["unrelated.job.name"]
        provider = MockDisplayProvider(linked_jobs=filtered_jobs, linked_groups=None)
        assert is_display_related(provider, job_name) is False

    @given(job_name=_qualified_job_name)
    def test_group_in_linked_groups_is_related(self, job_name: str) -> None:
        """A provider with the job's group in linked_groups is related.

        For job "infra.aws.deploy", the group is "infra.aws".
        """
        parts = job_name.rsplit(".", 1)
        if len(parts) < 2:
            # Single-segment job name has no group, so skip
            return

        group = parts[0]
        provider = MockDisplayProvider(linked_jobs=None, linked_groups=[group])
        assert is_display_related(provider, job_name) is True

    @given(job_name=_qualified_job_name)
    def test_ancestor_group_in_linked_groups_is_related(self, job_name: str) -> None:
        """A provider with any ancestor group in linked_groups is related.

        For job "infra.aws.deploy", ancestors are ["infra", "infra.aws"].
        """
        parts = job_name.rsplit(".", 1)
        if len(parts) < 2:
            # Single-segment job name has no group, so skip
            return

        group_path = parts[0]
        segments = group_path.split(".")
        if len(segments) < 2:
            # Group path is a single segment, tested in test_group_in_linked_groups
            return

        # Use the first ancestor (e.g., "infra" from "infra.aws")
        ancestor = segments[0]
        provider = MockDisplayProvider(linked_jobs=None, linked_groups=[ancestor])
        assert is_display_related(provider, job_name) is True

    @given(job_name=_qualified_job_name)
    def test_none_job_name_never_related(self, job_name: str) -> None:
        """When job_name is None, no display is ever related."""
        provider = MockDisplayProvider(
            linked_jobs=[job_name], linked_groups=["some-group"]
        )
        assert is_display_related(provider, None) is False

    @given(
        job_name=_qualified_job_name,
        unrelated_groups=st.lists(_name_segment, min_size=1, max_size=5),
    )
    def test_unrelated_groups_not_matching(
        self, job_name: str, unrelated_groups: list[str]
    ) -> None:
        """Groups that are not the job's group or ancestor are not related."""
        parts = job_name.rsplit(".", 1)
        # Build the set of actual groups/ancestors for this job
        actual_groups: set[str] = set()
        if len(parts) == 2:
            group_path = parts[0]
            segs = group_path.split(".")
            for i in range(1, len(segs) + 1):
                actual_groups.add(".".join(segs[:i]))

        # Filter out any groups that happen to match actual ancestors
        filtered_groups = [g for g in unrelated_groups if g not in actual_groups]
        if not filtered_groups:
            filtered_groups = ["zzz-definitely-unrelated"]

        provider = MockDisplayProvider(linked_jobs=None, linked_groups=filtered_groups)
        assert is_display_related(provider, job_name) is False

    @given(
        job_name=_qualified_job_name,
        num_providers=st.integers(min_value=1, max_value=10),
    )
    def test_find_related_excludes_should_show_false(
        self, job_name: str, num_providers: int
    ) -> None:
        """find_related_displays never includes providers where should_show=False,
        even if job-linked.

        **Validates: Requirement 6.10**
        """
        providers: list[MockDisplayProvider] = []
        for i in range(num_providers):
            # All providers are job-linked
            provider = MockDisplayProvider(
                display_id=f"display-{i}",
                display_priority=i,
                linked_jobs=[job_name],
                linked_groups=None,
                _should_show=False,  # CWD check fails
            )
            providers.append(provider)

        result = find_related_displays(
            providers=providers,  # type: ignore[arg-type]
            job_name=job_name,
            cwd=Path("/tmp"),
            app=None,  # type: ignore[arg-type]
        )
        assert result == [], (
            "Displays with should_show=False must never be included "
            "even when job-linked"
        )

    @given(
        job_name=_qualified_job_name,
        num_visible=st.integers(min_value=1, max_value=5),
        num_hidden=st.integers(min_value=0, max_value=5),
    )
    def test_find_related_includes_only_visible_job_linked(
        self, job_name: str, num_visible: int, num_hidden: int
    ) -> None:
        """find_related_displays includes only providers that are both
        job-linked AND should_show=True."""
        providers: list[MockDisplayProvider] = []

        # Visible, job-linked providers
        for i in range(num_visible):
            providers.append(
                MockDisplayProvider(
                    display_id=f"visible-{i}",
                    display_priority=i * 10,
                    linked_jobs=[job_name],
                    linked_groups=None,
                    _should_show=True,
                )
            )

        # Hidden, job-linked providers
        for i in range(num_hidden):
            providers.append(
                MockDisplayProvider(
                    display_id=f"hidden-{i}",
                    display_priority=100 + i,
                    linked_jobs=[job_name],
                    linked_groups=None,
                    _should_show=False,
                )
            )

        result = find_related_displays(
            providers=providers,  # type: ignore[arg-type]
            job_name=job_name,
            cwd=Path("/tmp"),
            app=None,  # type: ignore[arg-type]
        )

        # Only visible providers should be included
        assert len(result) == num_visible
        for r in result:
            assert r.display_id.startswith("visible-")  # type: ignore[attr-defined]
