"""Unit tests for JobBrowserPanel edge cases.

Tests cover:
- set_jobs() with empty and non-empty lists
- _derive_source_label() static method
- _derive_description() static method with truncation
- get_available_actions() focused/unfocused

**Validates: Requirements 2.3, 2.4, 2.5, 3.5**
"""

from __future__ import annotations

from functualize._cli.tui.panels.job_browser import JobBrowserPanel
from functualize._types.descriptors import JobDescriptor

# =============================================================================
# TestSetJobs
# =============================================================================


class TestSetJobs:
    """Tests for set_jobs() state management without mounting."""

    def test_empty_list_sets_row_count_zero(self) -> None:
        panel = JobBrowserPanel(id="test")
        panel.set_jobs([])
        assert panel._row_count == 0
        assert panel._cursor_row == 0
        assert panel._jobs == []

    def test_non_empty_list_sets_row_count(self) -> None:
        jobs = [JobDescriptor(name=f"job{i}", group=None) for i in range(5)]
        panel = JobBrowserPanel(id="test")
        panel.set_jobs(jobs)
        assert panel._row_count == 5
        assert panel._cursor_row == 0
        assert len(panel._jobs) == 5


# =============================================================================
# TestDeriveSourceLabel
# =============================================================================


class TestDeriveSourceLabel:
    """Tests for _derive_source_label static method."""

    def test_empty_source_returns_local(self) -> None:
        job = JobDescriptor(name="test", group=None, source="")
        assert JobBrowserPanel._derive_source_label(job) == "local"

    def test_no_source_returns_local(self) -> None:
        job = JobDescriptor(name="test", group=None)
        assert JobBrowserPanel._derive_source_label(job) == "local"

    def test_carried_label_wins(self) -> None:
        """Post-C1 the row carries its kind; the panel no longer guesses.

        The command tree knows whether a node is a job or a reserved builtin,
        so it stamps `source_label` on the row instead of leaving the panel to
        infer it.
        """
        from types import SimpleNamespace

        row = SimpleNamespace(name="builtin", source="", source_label="builtin")
        assert JobBrowserPanel._derive_source_label(row) == "builtin"

    def test_path_sniffing_is_gone(self) -> None:
        """A real job under a `functualize/_cli` path is no longer mislabelled.

        This used to return "builtin" purely because of the path substring —
        the false positive that motivated deleting the heuristic (C1.5).
        """
        job = JobDescriptor(
            name="test", group=None, source="functualize/_cli/something.py"
        )
        assert JobBrowserPanel._derive_source_label(job) == "local"

    def test_functualize_app_path_is_also_local_now(self) -> None:
        job = JobDescriptor(name="test", group=None, source="functualize/app/core.py")
        assert JobBrowserPanel._derive_source_label(job) == "local"

    def test_other_source_returns_local(self) -> None:
        job = JobDescriptor(
            name="test", group=None, source="/home/user/project/jobs.py"
        )
        assert JobBrowserPanel._derive_source_label(job) == "local"


# =============================================================================
# TestDeriveDescription
# =============================================================================


class TestDeriveDescription:
    """Tests for _derive_description static method."""

    def test_no_docstring_returns_empty(self) -> None:
        job = JobDescriptor(name="test", group=None, docstring=None)
        assert JobBrowserPanel._derive_description(job) == ""

    def test_empty_docstring_returns_empty(self) -> None:
        job = JobDescriptor(name="test", group=None, docstring="")
        assert JobBrowserPanel._derive_description(job) == ""

    def test_short_docstring_returned_as_is(self) -> None:
        job = JobDescriptor(name="test", group=None, docstring="Short desc")
        assert JobBrowserPanel._derive_description(job) == "Short desc"

    def test_long_docstring_truncated_at_50_chars(self) -> None:
        long_doc = "A" * 60
        job = JobDescriptor(name="test", group=None, docstring=long_doc)
        result = JobBrowserPanel._derive_description(job)
        assert len(result) == 50
        assert result.endswith("...")
        assert result == "A" * 47 + "..."

    def test_multiline_uses_first_line(self) -> None:
        job = JobDescriptor(
            name="test", group=None, docstring="First line\nSecond line"
        )
        assert JobBrowserPanel._derive_description(job) == "First line"

    def test_exactly_50_chars_not_truncated(self) -> None:
        doc = "A" * 50
        job = JobDescriptor(name="test", group=None, docstring=doc)
        assert JobBrowserPanel._derive_description(job) == doc


# =============================================================================
# TestGetAvailableActions
# =============================================================================


class TestGetAvailableActions:
    """Tests for get_available_actions() key hints."""

    def test_focused_returns_navigate_and_select(self) -> None:
        panel = JobBrowserPanel(id="test")
        actions = panel.get_available_actions(focused=True)
        assert actions == [("j/k", "navigate"), ("/", "filter"), ("Enter", "select")]

    def test_unfocused_returns_esc_back(self) -> None:
        panel = JobBrowserPanel(id="test")
        actions = panel.get_available_actions(focused=False)
        assert actions == [("Esc", "back")]
