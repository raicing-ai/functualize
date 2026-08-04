"""JobBrowserPanel — row-navigable job browser with Enter-to-select.

Provides a DataTable-based panel for browsing discovered jobs. Row navigation
uses j/k (wrapping). Enter selects the current row and posts JobSelected.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from functualize._types.descriptors import JobDescriptor

__all__ = ["JobBrowserPanel"]


class JobBrowserPanel(Widget):
    """Row-navigable job browser with DataTable.

    Wraps a DataTable with cursor_type="row" and provides vim-style
    row navigation (j/k wrap). Enter selects the current job and posts
    a JobSelected message for the parent app to handle.
    """

    DEFAULT_CSS = """
    JobBrowserPanel {
        height: auto;
        min-height: 3;
        max-height: 10;
    }
    JobBrowserPanel DataTable {
        height: auto;
        min-height: 2;
        max-height: 10;
    }
    """

    class JobSelected(Message):
        """Posted when a job row is selected via Enter."""

        def __init__(self, job_name: str) -> None:
            self.job_name = job_name
            super().__init__()

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._jobs: list[JobDescriptor] = []
        self._filtered_jobs: list[JobDescriptor] = []
        self._active_filter_text: str = ""
        self._cursor_row: int = 0
        self._row_count: int = 0
        self._table: DataTable[str] | None = None
        self._populated: bool = False

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Mount the inner DataTable."""
        table: DataTable[str] = DataTable(cursor_type="row")
        table.add_columns("Job Name", "Source", "Description")
        self._table = table
        self._populated = False  # Reset since table is fresh
        yield table

    def on_mount(self) -> None:
        """Populate the table after mount if set_jobs was called pre-mount."""
        self._populate_table()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_jobs(self, jobs: list[JobDescriptor]) -> None:
        """Populate the table with job descriptors.

        Clears existing rows and rebuilds. Resets cursor to row 0.
        """
        self._jobs = list(jobs)
        self._filtered_jobs = list(jobs)
        self._row_count = len(jobs)
        self._cursor_row = 0
        self._populated = False
        self._populate_table()

    def _populate_table(self) -> None:
        """Actually add rows to the DataTable if it's ready and not yet populated."""
        if self._populated or not self._filtered_jobs or self._table is None:
            return
        self._table.clear()
        for job in self._filtered_jobs:
            name = job.name
            source = self._derive_source_label(job)
            description = self._derive_description(job)
            self._table.add_row(name, source, description)
        self._populated = True
        self._sync_table_cursor()

    @property
    def active_filter(self) -> str:
        """The currently applied filter text. Empty string means no filter."""
        return self._active_filter_text

    def apply_filter(self, query: str) -> None:
        """Filter visible rows by query string (case-insensitive substring match).

        An empty query resets the table to show all jobs.
        """
        self._active_filter_text = query
        if not query:
            # Reset: show all jobs
            self._filtered_jobs = list(self._jobs)
        else:
            q = query.lower()
            self._filtered_jobs = [j for j in self._jobs if q in j.name.lower()]
        self._row_count = len(self._filtered_jobs)
        self._cursor_row = 0
        self._reload_filtered_table()

    def _reload_filtered_table(self) -> None:
        """Repopulate the DataTable with the current filtered job list."""
        if self._table is None:
            return
        self._table.clear()
        for job in self._filtered_jobs:
            name = job.name
            source = self._derive_source_label(job)
            description = self._derive_description(job)
            self._table.add_row(name, source, description)
        self._sync_table_cursor()

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Return key hints for the PanelHost footer."""
        if not focused:
            return [("Esc", "back")]
        return [("j/k", "navigate"), ("/", "filter"), ("Enter", "select")]

    # ------------------------------------------------------------------
    # Row navigation — wrapping
    # ------------------------------------------------------------------

    def action_cursor_down(self) -> None:
        """Move cursor down one row, wrapping from last to first."""
        if self._row_count == 0:
            return
        self._cursor_row = (self._cursor_row + 1) % self._row_count
        self._sync_table_cursor()

    def action_cursor_up(self) -> None:
        """Move cursor up one row, wrapping from first to last."""
        if self._row_count == 0:
            return
        self._cursor_row = (self._cursor_row - 1) % self._row_count
        self._sync_table_cursor()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def action_select_job(self) -> None:
        """Select the current row and post JobSelected message."""
        if not self._filtered_jobs or self._cursor_row >= len(self._filtered_jobs):
            return
        job = self._filtered_jobs[self._cursor_row]
        self.post_message(self.JobSelected(job.name))

    def action_drill_down(self) -> None:
        """Handle Enter key — alias for action_select_job.

        In the NORMAL/PANEL keymap, Enter maps to 'drill_down'. For the
        job browser, drilling down means selecting the current job.
        """
        self.action_select_job()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_source_label(job: JobDescriptor) -> str:
        """Derive a human-readable source label for a browser row.

        The row **carries** its label when the command tree already knows the
        node's kind (``source_label``). That replaces two guesses this method
        used to make — a reserved-name membership test, and a
        ``"functualize/_cli" in source`` path sniff — both of which mislabel a
        real job that happens to live under a matching path or share a name.
        """
        carried = getattr(job, "source_label", None)
        if carried:
            return str(carried)
        return "local"

    @staticmethod
    def _derive_description(job: JobDescriptor) -> str:
        """Extract first line of docstring as description."""
        doc = job.docstring or ""
        if not doc:
            return ""
        first_line = doc.strip().split("\n")[0]
        if len(first_line) > 50:
            return first_line[:47] + "..."
        return first_line

    def _sync_table_cursor(self) -> None:
        """Synchronize the DataTable's visual cursor with internal state."""
        if self._table is None or self._row_count == 0:
            return
        with contextlib.suppress(Exception):
            self._table.move_cursor(row=self._cursor_row)
