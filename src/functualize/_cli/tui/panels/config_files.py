"""ConfigFilesPanel — file-centric config source viewer with deferred population.

Displays a DataTable with columns: File, Status, and Fields. Provides
vim-style j/k row navigation (wrapping) and Filterable protocol support.
Includes the `discover_config_files` helper for config file discovery.

Enter on a row posts ``DrillDownRequested``; the app answers by pushing a
``SourceChainDetailView`` over that file. This panel deliberately owns no
detail state — see ``action_drill_down``.

Atomic TOML writes live in ``_cli/data/toml_writer.py``, shared with the TUI
settings store.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

from functualize.types import ConfigFileRole

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from functualize._cli.tui.panels.config_table import FieldDef
    from functualize.types import ConfigFileInfo

__all__ = [
    "ConfigFileEntry",
    "ConfigFilesPanel",
    "discover_config_files",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ConfigFileEntry:
    """A single config file entry for display in the ConfigFilesPanel.

    ``status`` answers "is this file contributing?", which is the question a
    user actually has. Whether the file is *writable* is a separate axis and
    rides along in ``writable`` rather than being folded into the status —
    the old status conflated the two ("exists" vs "read_only") while being
    unable to say the far more important thing: that a file which plainly
    exists is being ignored because it names another environment.
    """

    path: Path  # absolute file path
    section: str  # TOML section name
    display_name: str  # relative path for display
    status: str  # "active" | "inactive" | "not_found"
    fields_from_file: list[str] = field(default_factory=list)
    #: The ``<slot>`` in ``config.<slot>.<ext>``; None for unslotted files.
    environment_slot: str | None = None
    writable: bool = True


# ---------------------------------------------------------------------------
# Status formatting
# ---------------------------------------------------------------------------

_STATUS_DISPLAY: dict[str, str] = {
    "active": "★ active",
    "inactive": "○ inactive",
    "not_found": "○ not found",
}


def _format_status(status: str, *, writable: bool = True) -> str:
    """Convert a raw status string to a human-readable display string.

    Read-only files get a lock suffix rather than a separate status, so the
    active/inactive axis stays readable at a glance.
    """
    display = _STATUS_DISPLAY.get(status, status)
    if not writable:
        return f"{display} 🔒"
    return display


def _format_environment(slot: str | None) -> str:
    """Render a file's environment slot for the Env column."""
    return slot if slot else "—"


# ---------------------------------------------------------------------------
# Discovery helper
# ---------------------------------------------------------------------------


def _determine_section(
    job_name: str,
    job_group: str | None,
    is_pyproject: bool,
) -> str:
    """Determine the TOML section name based on job group and file type.

    Uses kernel-consistent logic: grouped jobs use the group path as their
    config section (accounting for custom config_prefix); ungrouped jobs
    use the job name directly.

    When a FunctualizeApp instance is available, callers should prefer
    ``app.get_job_config_section(job_name)`` for the base section and
    only wrap with ``tool.functualize.`` for pyproject.toml here.

    Section naming rules (R2-AC7):
    - ungrouped: section = job_name (e.g., [serve])
    - grouped: section = group path (e.g., [infra])
    - pyproject.toml: section = tool.functualize.<section>

    Args:
        job_name: The job's name (may be qualified like "infra.deploy").
        job_group: The group path (None for ungrouped jobs).
        is_pyproject: Whether this is a pyproject.toml file.

    Returns:
        The TOML section name string.
    """
    base_section = job_group if job_group else job_name

    if is_pyproject:
        return f"tool.functualize.{base_section}"
    return base_section


def _determine_file_status(path: Path, role: ConfigFileRole | None = None) -> str:
    """Determine whether a config file is contributing.

    Existence alone cannot answer this: a ``config.prod.toml`` sitting right
    there in the project is completely ignored when the active environment is
    ``dev``. The kernel is the authority on that, so its role comes in rather
    than being re-derived here.

    Args:
        path: The file path to check.
        role: The kernel's classification, or None when unknown (no kernel
            info available) — in which case an existing file is assumed to
            contribute, which is the pre-environment behavior.

    Returns:
        One of "active", "inactive", or "not_found".
    """
    if not path.exists():
        return "not_found"
    if role is ConfigFileRole.INERT:
        return "inactive"
    return "active"


def _is_writable(path: Path) -> bool:
    """Return True if the file can be edited in place."""
    return os.access(path, os.W_OK)


def _make_display_name(path: Path, cwd: Path) -> str:
    """Create a display-friendly name for a file path.

    Uses relative path if the file is under cwd, otherwise shows
    a shortened absolute path with ~ for home directory.
    """
    try:
        return str(path.relative_to(cwd))
    except ValueError:
        # Not under cwd — try home-relative
        try:
            home = Path.home()
            return "~/" + str(path.relative_to(home))
        except ValueError:
            return str(path)


def discover_config_files(
    fields: list[FieldDef],
    job_name: str,
    job_group: str | None,
    cwd: Path,
    kernel_file_paths: list[str] | None = None,
    *,
    kernel_files: list[ConfigFileInfo] | None = None,
    config_section: str | None = None,
) -> list[ConfigFileEntry]:
    """Discover config files relevant to the current job.

    Uses the kernel's FileSource discovered paths when available (exclusive),
    falling back to standard location discovery only when kernel paths are
    unavailable (no FunctualizeApp instance).

    Only CONFIG parameters contribute to file discovery (R5-AC5). PLAIN
    parameters are excluded since they don't participate in file resolution.

    Discovery strategy:
    1. When kernel_file_paths is provided: uses ONLY those paths (kernel's
       ResourceLocator results are authoritative)
    2. When kernel_file_paths is None: falls back to CWD standard locations
       (.functualize.toml, functualize.toml, pyproject.toml) + config.*.toml glob

    Section naming (R2-AC7):
    - When config_section is provided (from FunctualizeApp.get_job_config_section),
      uses that directly for kernel-consistent resolution.
    - Otherwise falls back to heuristic: group path for grouped, job_name for ungrouped.
    - pyproject.toml: section = tool.functualize.<section>

    Status:
    - contributing under the active environment → "active"
    - exists but names another environment → "inactive"
    - not exists → "not_found" (filtered out)
    Writability is reported separately on the entry, not folded into status.

    Args:
        fields: The FieldDef instances for the job (with populated chain).
        job_name: The job name.
        job_group: The group path (None for ungrouped jobs).
        cwd: The current working directory.
        kernel_file_paths: Optional list of file paths from the kernel. When
            provided, these are used exclusively (no hardcoded fallback paths
            added). Prefer ``kernel_files``, which also carries each file's
            role — paths alone cannot say whether a file is contributing.
        kernel_files: Optional ``ConfigFileInfo`` list from
            ``FunctualizeApp.config_files()``. Supersedes kernel_file_paths
            and is the only way entries get real active/inactive status.
        config_section: Optional section name from FunctualizeApp.get_job_config_section().
            When provided, overrides the _determine_section heuristic for
            kernel-consistent section resolution.

    Returns:
        A list of ConfigFileEntry instances for display in ConfigFilesPanel.
    """
    from functualize._cli.tui.panels.config_table import ParamKind

    # Only CONFIG params contribute to file discovery (R5-AC5)
    config_fields = [f for f in fields if f.param_kind == ParamKind.CONFIG]

    # The groups on the job's path that declared any of those fields, outermost
    # first — each is its own TOML section, and the field list is already in
    # that order (`build_group_field_defs`).
    group_sections: list[str] = []
    for f in config_fields:
        gp = f.group_path
        if gp and gp not in group_sections:
            group_sections.append(gp)

    # Build ordered path list
    all_paths: list[Path] = []
    roles: dict[Path, ConfigFileRole] = {}
    slots: dict[Path, str | None] = {}

    if kernel_files:
        for info in kernel_files:
            path = Path(info.path)
            all_paths.append(path)
            roles[path] = info.role
            slots[path] = info.environment_slot
    elif kernel_file_paths:
        # Kernel-discovered paths are authoritative — use them exclusively.
        # These are the actual files the kernel found during config resolution
        # via ResourceLocator, so no hardcoded fallback is needed.
        for p_str in kernel_file_paths:
            all_paths.append(Path(p_str))
    else:
        # Fallback: when kernel paths are unavailable (e.g., no FunctualizeApp
        # instance), use CWD standard locations for basic discovery.
        standard_paths: list[Path] = [
            cwd / ".functualize.toml",
            cwd / "functualize.toml",
            cwd / "pyproject.toml",
        ]
        all_paths.extend(standard_paths)

        # Discover config.*.toml files in CWD (matches kernel's FileSource pattern)
        import glob as glob_module

        for match in sorted(glob_module.glob(str(cwd / "config.*.toml"))):
            all_paths.append(Path(match))

    # Deduplicate, preserving order
    seen: set[Path] = set()
    ordered_paths: list[Path] = []
    for p in all_paths:
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            ordered_paths.append(p)

    # Build ConfigFileEntry for each path — only include files that exist
    entries: list[ConfigFileEntry] = []
    for file_path in ordered_paths:
        is_pyproject = file_path.name == "pyproject.toml"
        # Use kernel-provided section when available, otherwise fall back to heuristic
        if config_section is not None:
            if is_pyproject:
                section = f"tool.functualize.{config_section}"
            else:
                section = config_section
        else:
            section = _determine_section(job_name, job_group, is_pyproject)
        status = _determine_file_status(file_path, roles.get(file_path))

        # Skip files that don't exist — no value in showing phantom entries.
        # An *inactive* file is kept: that a real file is being ignored is
        # exactly what the user needs to see.
        if status == "not_found":
            continue

        display_name = _make_display_name(file_path, cwd)

        # Determine which fields this specific file defines by parsing it.
        # A group option is declared in the *group's* section, not the job's:
        # `[deploy]` holds `env` while the job resolves against `[deploy.web]`.
        # Reading one section therefore reported the file as contributing only
        # what the deepest group happened to declare, and an outer group's
        # fields — in the same file, two lines up — did not appear at all.
        fields_from_file: list[str] = _extract_fields_from_file(
            file_path, section, [f for f in config_fields if not f.group_path]
        )
        for group_path in group_sections:
            group_section = (
                f"tool.functualize.{group_path}" if is_pyproject else group_path
            )
            fields_from_file.extend(
                # `[deploy] env` — the same prefix the config table, the
                # pre-flight and the diff use, so the reader is not asked to
                # learn a fourth spelling for the same idea. Unescaped, unlike
                # those three: this column is a plain DataTable cell, not Rich
                # markup — the section in the File column beside it is written
                # the same way.
                f"[{group_path}] {name}"
                for name in _extract_fields_from_file(
                    file_path,
                    group_section,
                    [f for f in config_fields if f.group_path == group_path],
                )
            )

        entries.append(
            ConfigFileEntry(
                path=file_path,
                section=section,
                display_name=display_name,
                status=status,
                fields_from_file=fields_from_file,
                # Only the kernel knows the slot; without its info this stays
                # None and the Env column shows "—" rather than a guess.
                environment_slot=slots.get(file_path),
                writable=_is_writable(file_path),
            )
        )

    return entries


def _extract_fields_from_file(
    file_path: Path,
    section: str,
    config_fields: list[FieldDef],
) -> list[str]:
    """Parse a TOML file and return which config fields it defines.

    Reads the file, looks up the given section, and returns field names
    that are both present in the file's section AND in the config_fields list.

    Returns an empty list if the file can't be parsed or the section doesn't exist.
    """
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef, import-not-found]
        except ImportError:
            return []

    try:
        with open(file_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        # Narrower than Exception: file I/O errors (missing/unreadable
        # file) and TOML parse errors are the only failure modes of
        # open()+tomllib.load(); no widget/app context is available here
        # to log a warning, so this stays a silent best-effort parse.
        return []

    # Navigate to the section (supports dotted sections like "tool.functualize.deploy")
    parts = section.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return []
    if not isinstance(current, dict):
        return []

    # Match keys in the section to known config field names
    field_names = {fd.name for fd in config_fields}
    return [key for key in current if key in field_names]


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------


class ConfigFilesPanel(Widget):
    """File-centric config source panel with DataTable.

    Shows config file paths, their status (exists/not found/read-only),
    and which fields each file contributes. Provides j/k wrapping row
    navigation and Filterable protocol compatibility.

    Supports drill-down into individual files to show field values,
    stage edits (i key), and toggle removals (d key).
    """

    DEFAULT_CSS = """
    ConfigFilesPanel {
        height: auto;
        min-height: 3;
        max-height: 10;
    }
    ConfigFilesPanel DataTable {
        height: auto;
        min-height: 2;
        max-height: 10;
    }
    ConfigFilesPanel Static {
        height: auto;
        min-height: 2;
        max-height: 10;
    }
    """

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    class DrillDownRequested(Message):
        """Posted when Enter is pressed on a file row."""

        def __init__(self, file_entry: ConfigFileEntry) -> None:
            self.file_entry = file_entry
            super().__init__()

    class NewFileRequested(Message):
        """Posted when `n` is pressed — user wants to create a config file."""

    class FileSaved(Message):
        """Posted after a file's staged changes are written."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._files: list[ConfigFileEntry] = []
        self._filtered_files: list[ConfigFileEntry] = []
        self._active_filter_text: str = ""
        self._cursor_row: int = 0
        self._row_count: int = 0
        self._table: DataTable[str] | None = None
        self._populated: bool = False
        self._job_fields: list[FieldDef] = []  # all job fields (set externally)
        self._preset_notice: str | None = None

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Mount the inner DataTable with File, Status, Fields columns."""
        table: DataTable[str] = DataTable(cursor_type="row")
        table.add_columns("File", "Env", "Status", "Fields")
        self._table = table
        self._populated = False  # Reset since table is fresh
        yield table

    def on_mount(self) -> None:
        """Populate the table after mount if set_files was called pre-mount."""
        self._populate_table()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_files(self, files: list[ConfigFileEntry]) -> None:
        """Populate the table with config file entries.

        Clears existing rows and rebuilds. Resets cursor to row 0.
        """
        self._files = list(files)
        self._filtered_files = list(files)
        self._active_filter_text = ""
        self._row_count = len(files)
        self._cursor_row = 0
        self._populated = False
        self._populate_table()

    def set_fields(self, fields: list[FieldDef]) -> None:
        """Set the full list of job fields (used for detail view rendering).

        Must be called before drill-down to provide field metadata.
        """
        self._job_fields = list(fields)

    def set_preset_notice(self, notice: str) -> None:
        """Show a notice row instead of a file list (preset awareness).

        Used when the active ConfigSources preset (env_only, twelve_factor)
        has no FileSource — the panel then explains that file resolution is
        disabled instead of degrading to an empty list.
        """
        self._preset_notice = notice
        self._files = []
        self._filtered_files = []
        self._row_count = 0
        self._cursor_row = 0
        self._populated = False
        self._populate_table()

    @property
    def preset_notice(self) -> str | None:
        """The active preset notice, or None when files are listed."""
        return self._preset_notice

    @property
    def files(self) -> list[ConfigFileEntry]:
        """The config file entries this panel is showing.

        Public accessor so the app can build a chain provider without
        reaching into ``panel._files`` (R4 private-reach-in hygiene).
        """
        return list(self._files)

    @property
    def job_fields(self) -> list[FieldDef]:
        """The job's field definitions backing the detail view."""
        return list(self._job_fields)

    def _populate_table(self) -> None:
        """Actually add rows to the DataTable if it's ready and not yet populated."""
        if self._populated or self._table is None:
            return
        if self._preset_notice is not None:
            self._table.clear()
            self._table.add_row(self._preset_notice, "", "", "")
            self._populated = True
            return
        if not self._filtered_files:
            return
        self._table.clear()
        for entry in self._filtered_files:
            # No brackets for a file without a section scope (settings files
            # whose whole document is functualize's).
            file_display = (
                f"{entry.display_name} [{entry.section}]"
                if entry.section
                else entry.display_name
            )
            env_display = _format_environment(entry.environment_slot)
            status_display = _format_status(entry.status, writable=entry.writable)
            fields_display = (
                ", ".join(entry.fields_from_file) if entry.fields_from_file else ""
            )
            self._table.add_row(
                file_display, env_display, status_display, fields_display
            )
        self._populated = True
        self._sync_table_cursor()

    def get_cursor_file(self) -> ConfigFileEntry | None:
        """Return the ConfigFileEntry at the current cursor row, or None if empty."""
        if not self._filtered_files or self._cursor_row >= len(self._filtered_files):
            return None
        return self._filtered_files[self._cursor_row]

    # ------------------------------------------------------------------
    # Detail view — drill-down
    # ------------------------------------------------------------------

    def action_drill_down(self) -> None:
        """Drill down into the file at the current cursor row (Enter key).

        Posts DrillDownRequested; the app builds a SourceChainDetailView over
        this file and pushes it onto the PanelHost view stack.

        The panel used to own the detail view itself, via an ``_in_detail``
        mode flag plus a parallel set of staged-edit/cursor/save methods. That
        is what broke every key but Esc: the panel stayed the active target,
        so j/k moved *this* table's hidden cursor and the detail actions were
        unreachable. Detail state now lives in the pushed widget, which is the
        active panel while it is up.
        """
        file_entry = self.get_cursor_file()
        if file_entry is None:
            return
        self.post_message(self.DrillDownRequested(file_entry))

    def action_new_file(self) -> None:
        """Offer conventional locations for a new config file (`n`).

        Posts NewFileRequested; the app pushes a NewFilePickerView, because
        a user who doesn't know the filename conventions can only pick from
        a list, not type the right name into a prompt.
        """
        self.post_message(self.NewFileRequested())

    @property
    def active_filter(self) -> str:
        """The currently applied filter text. Empty string means no filter."""
        return self._active_filter_text

    def apply_filter(self, query: str) -> None:
        """Filter visible rows by file display name (case-insensitive substring match).

        An empty query resets the table to show all files.
        """
        self._active_filter_text = query
        if not query:
            self._filtered_files = list(self._files)
        else:
            q = query.lower()
            self._filtered_files = [
                f for f in self._files if q in f.display_name.lower()
            ]
        self._row_count = len(self._filtered_files)
        self._cursor_row = 0
        self._reload_table()

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
    # Actions
    # ------------------------------------------------------------------

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Return key hints for the PanelHost footer.

        Only the file-list hints live here now. The detail view is a separate
        widget and supplies its own hints once pushed — previously this method
        advertised i/d/Ctrl+S for the detail level while none of those keys
        were actually bound.
        """
        if not focused:
            return [("Ctrl+R", "focus"), ("Shift+Tab", "cycle")]

        hints: list[tuple[str, str]] = [("j/k", "navigate"), ("/", "filter")]
        # Add Enter hint if there are files to drill into
        if self._row_count > 0:
            hints.append(("Enter", "open file"))
        # `n` opens the new-file location picker — advertised even when files
        # already exist, since creating an overlay next to a base is the
        # common case, not the empty-list one.
        hints.append(("n", "new file"))
        return hints

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reload_table(self) -> None:
        """Clear and repopulate the DataTable with current filtered files."""
        if self._table is None:
            return
        self._table.clear()
        for entry in self._filtered_files:
            # No brackets for a file without a section scope (settings files
            # whose whole document is functualize's).
            file_display = (
                f"{entry.display_name} [{entry.section}]"
                if entry.section
                else entry.display_name
            )
            env_display = _format_environment(entry.environment_slot)
            status_display = _format_status(entry.status, writable=entry.writable)
            fields_display = (
                ", ".join(entry.fields_from_file) if entry.fields_from_file else ""
            )
            self._table.add_row(
                file_display, env_display, status_display, fields_display
            )
        self._populated = True
        self._sync_table_cursor()

    def _sync_table_cursor(self) -> None:
        """Synchronize the DataTable's visual cursor with internal state."""
        if self._table is None or self._row_count == 0:
            return
        with contextlib.suppress(Exception):
            self._table.move_cursor(row=self._cursor_row)
