"""Ambient display for the Surface Showcase — a Git branch indicator.

Dropped in the project's CWD, discovered by the TUI's display scan and shown in
the above-header display slot. Demonstrates a host-level DisplayProvider (as
opposed to a job-scoped `live: Live` construct): it is always present when the
CWD is a git repo, and it is *linked* to the `report` job so the TUI can surface
it when that job is selected (the display names the job, never the reverse).

Both displays subclass `functualize.ui.Display`, which supplies defaults for
every optional hook (priority, refresh interval, job links, footer actions).
Subclassing is optional — discovery duck-types — but it means a display only
declares what it actually overrides.

`should_show` runs on the event loop for every provider on every CWD change, so
it stays a path check. `refresh` runs on a **thread worker** and is bounded by
`refresh_timeout`, so shelling out to git here is safe: a slow or hung git call
costs this display a cycle, not the whole TUI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from functualize.ui import Display

if TYPE_CHECKING:
    from textual.app import ComposeResult


class GitBranchDisplay(Display):
    display_id = "git-branch"
    display_title = "Git"
    display_priority = 50
    refresh_interval = 5.0  # re-poll every 5s
    linked_jobs = ["report"]  # surfaces when `report` is the pending job

    def __init__(self) -> None:
        self._label = _branch()
        self._widget = None

    def should_show(self, cwd: Path, app: object) -> bool:
        # A git worktree is detected by any ancestor holding `.git` (a directory
        # in a normal clone, a file in a linked worktree/submodule) — mirroring
        # how `_branch()` relies on git walking up from a subdirectory. A bare
        # `(cwd / ".git")` check would miss running from a subfolder of the repo
        # (e.g. this example in-place inside the functualize monorepo).
        return any((parent / ".git").exists() for parent in (cwd, *cwd.parents))

    def compose_display(self) -> ComposeResult:
        from textual.widgets import Static

        self._widget = Static(f"⎇ {self._label}", id="git-branch-body")
        yield self._widget

    def refresh(self) -> None:
        # Runs on a thread worker, so the subprocess call is free to block.
        # Only provider state is touched here; the TUI repaints from it on the
        # loop thread once this returns.
        self._label = _branch()
        if self._widget is not None:
            self._widget.update(f"⎇ {self._label}")

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        return [("Ctrl+U/O", "displays")]


class PythonDisplay(Display):
    """A second ambient display — the running Python version.

    Always present (no CWD gate) and unlinked to any job. It exists so the
    example has *two* displays in the ring: focus the slot with Shift+Tab, then
    cycle between them with Ctrl+U / Ctrl+O. A higher priority number than the
    Git display keeps it second in the ring.

    Shows how little a static display has to declare: no `should_show` (the
    base defaults to always-visible), no `refresh`, no job links.
    """

    display_id = "python"
    display_title = "Python"
    display_priority = 60  # after Git (50)

    def compose_display(self) -> ComposeResult:
        import platform

        from textual.widgets import Static

        yield Static(f"\N{SNAKE} Python {platform.python_version()}")

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        return [("Ctrl+U/O", "displays")]


def _branch() -> str:
    try:
        out = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return out.stdout.strip() or "(detached)"
    except Exception:
        return "(no git)"
