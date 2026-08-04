"""Job/builtin-command listing helpers for the inline TUI.

Builds the "general" panels (job browser + settings) that are always
available regardless of which job is currently typed in the SmartBar,
Rows come from the shell's **one command tree** (``app.commands``), so jobs and
the reserved ``builtin`` subtree are listed by the same code path. The synthetic
builtin descriptors this module used to fabricate are gone — a row now carries
its own ``source_label`` because the tree already knows what kind of node it is,
which is strictly better than re-deriving it from a name or a path substring.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from textual.widgets import RichLog

if TYPE_CHECKING:
    from functualize._cli.tui.app import FunctualizeInlineTUI


def command_tree_rows(app: FunctualizeInlineTUI) -> list[Any]:
    """Job-browser rows for every top-level node in the one command tree.

    A real job keeps its own descriptor (the browser reads `source`, module
    path, parameters off it). A node with no descriptor — the reserved
    ``builtin`` subtree — gets a lightweight row carrying the same fields plus
    an explicit ``source_label``.
    """
    from functualize.app.commands import build_command_tree

    rows: list[Any] = []
    descriptors = {d.name: d for d in app._func_app.get_jobs()}
    for node in build_command_tree(app._func_app):
        descriptor = descriptors.get(node.name)
        if descriptor is not None:
            rows.append(descriptor)
            continue
        rows.append(
            SimpleNamespace(
                name=node.name,
                source="",
                docstring=node.help_text,
                group=None,
                parameters=[],
                config_fields=[],
                source_label="builtin",
            )
        )
    return rows


def count_jobs_in_cwd(jobs: list[Any], cwd: Path) -> int:
    """Count jobs whose source/module path is under cwd."""
    cwd_count = 0
    for j in jobs:
        source = getattr(j, "source_path", None) or getattr(j, "module_path", None)
        if source and str(cwd) in str(source):
            cwd_count += 1
    return cwd_count


def build_general_panels(app: FunctualizeInlineTUI) -> list[tuple[str, Any]]:
    """Build general panels (always available, not job-specific).

    Returns panels for: Job Browser (list of all discovered jobs + builtins)
    and Settings.
    """
    from functualize._cli.tui.panels.job_browser import JobBrowserPanel

    app._panel_id_seq += 1
    seq = app._panel_id_seq
    panels: list[tuple[str, Any]] = []

    # Panel 1: Job Browser — interactive DataTable
    job_browser = JobBrowserPanel(id=f"job-browser-panel-{seq}")
    try:
        job_browser.set_jobs(command_tree_rows(app))
    except Exception as exc:
        # Job discovery (get_jobs) is a domain call that can fail for many
        # reasons unrelated to widget mounting — log and fall back to an
        # empty table, which is an acceptable degraded state.
        app.log.warning(
            f"build_general_panels: failed to load jobs ({type(exc).__name__}): {exc}"
        )
    panels.append(("Jobs", job_browser))

    # Panel 2: Settings — the full func-settings catalog
    try:
        from functualize._cli.tui.settings_panel import SettingsPanel

        settings = SettingsPanel(id=f"settings-panel-{seq}")
        panels.append(("Settings", settings))
    except Exception as exc:
        # SettingsPanel import/construction can fail for many reasons
        # unrelated to widget mounting — log and fall back to a plain
        # RichLog placeholder, which is an acceptable degraded state.
        app.log.warning(
            f"build_general_panels: failed to build settings panel "
            f"({type(exc).__name__}): {exc}"
        )
        settings_log = RichLog(id=f"settings-panel-{seq}", wrap=True, markup=True)
        settings_log.write("[dim]Settings panel not available[/dim]")
        panels.append(("Settings", settings_log))

    # Panel 3: Settings Files — the files those settings resolve through,
    # mirroring the Config Files panel on the command ring.
    try:
        from functualize._cli.tui.panels.settings_files import (
            SettingsFilesPanel,
            build_settings_file_entries,
        )

        settings_files = SettingsFilesPanel(id=f"settings-files-panel-{seq}")
        settings_files.set_files(
            build_settings_file_entries(app._settings_store, Path.cwd())
        )
        panels.append(("Settings Files", settings_files))
    except Exception as exc:
        # Same degraded-state contract as the Settings panel above.
        app.log.warning(
            f"build_general_panels: failed to build settings files panel "
            f"({type(exc).__name__}): {exc}"
        )

    return panels
