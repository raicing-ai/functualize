"""Custom Textual widgets for the fullscreen TUI shell.

Provides the flow tree widget for displaying job execution hierarchy
and the log panel widget for streaming log messages. Part of
``functualize.ui`` (the [cli] extra).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog, Static, Tree

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.widgets.tree import TreeNode

# ─── Status Icons ─────────────────────────────────────────────────────


STATUS_ICONS: dict[str, str] = {
    "running": "⏳",
    "success": "✓",
    "failure": "✗",
    "pending": "○",
    "timeout": "⏱",
    "cancelled": "⊘",
    "unknown": "?",
}


def _status_icon(status: str) -> str:
    """Get the status icon for a given status string."""
    return STATUS_ICONS.get(status.lower(), STATUS_ICONS["unknown"])


# ─── Flow Tree Widget ─────────────────────────────────────────────────


class FlowTreeWidget(Widget):
    """Displays job execution hierarchy as a tree with status icons.

    Shows the root job and nested invocations as indented children,
    each with a status icon prefix.
    """

    DEFAULT_CSS = """
    FlowTreeWidget {
        width: 100%;
        height: 100%;
        border: solid $accent;
        padding: 0 1;
    }
    FlowTreeWidget > Static {
        color: $text;
        text-style: bold;
        padding: 0 0 1 0;
    }
    FlowTreeWidget > Tree {
        width: 100%;
        height: 1fr;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tree: Tree[str] | None = None
        self._node_map: dict[str, TreeNode[str]] = {}

    def compose(self) -> ComposeResult:
        yield Static("[bold]Flow Tree[/bold]")
        tree: Tree[str] = Tree("Jobs")
        tree.show_root = False
        tree.guide_depth = 3
        self._tree = tree
        yield tree

    def add_job(self, job_name: str, parent_job: str | None = None) -> None:
        """Add a job node to the tree.

        Args:
            job_name: The name of the job to add.
            parent_job: The parent job name if this is a nested invocation.
        """
        if self._tree is None:
            return

        label = f"{_status_icon('running')} {job_name}"

        if parent_job and parent_job in self._node_map:
            parent_node = self._node_map[parent_job]
            node = parent_node.add(label, data=job_name)
            parent_node.expand()
        else:
            node = self._tree.root.add(label, data=job_name)
            self._tree.root.expand()

        self._node_map[job_name] = node
        node.expand()

    def update_job_status(self, job_name: str, status: str, message: str = "") -> None:
        """Update a job node's status icon and optional message.

        Args:
            job_name: The job whose status to update.
            status: The new status string (running, success, failure, etc.).
            message: Optional message to append after the job name.
        """
        if job_name not in self._node_map:
            return

        node = self._node_map[job_name]
        icon = _status_icon(status)
        suffix = f" — {message}" if message else ""
        node.set_label(f"{icon} {job_name}{suffix}")

    def add_step(self, job_name: str, step_name: str, status: str) -> None:
        """Add or update a workflow step under a job node.

        Args:
            job_name: The parent job name.
            step_name: The step name.
            status: The step status.
        """
        if job_name not in self._node_map:
            return

        step_key = f"{job_name}::{step_name}"
        icon = _status_icon(status)
        label = f"  {icon} {step_name}"

        if step_key in self._node_map:
            self._node_map[step_key].set_label(label)
        else:
            parent_node = self._node_map[job_name]
            node = parent_node.add(label, data=step_key)
            self._node_map[step_key] = node


# ─── Log Panel Widget ─────────────────────────────────────────────────


class LogPanelWidget(Widget):
    """Streaming log panel that displays log messages with level styling."""

    DEFAULT_CSS = """
    LogPanelWidget {
        width: 100%;
        height: 100%;
        border: solid $accent;
        padding: 0 1;
    }
    LogPanelWidget > Static {
        color: $text;
        text-style: bold;
        padding: 0 0 1 0;
    }
    LogPanelWidget > RichLog {
        width: 100%;
        height: 1fr;
    }
    """

    # Level to Rich markup color mapping
    LEVEL_STYLES: dict[str, str] = {
        "debug": "dim",
        "info": "white",
        "warning": "yellow",
        "error": "red bold",
        "critical": "red bold reverse",
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._rich_log: RichLog | None = None

    def compose(self) -> ComposeResult:
        yield Static("[bold]Logs[/bold]")
        rich_log = RichLog(highlight=True, markup=True, wrap=True, max_lines=5000)
        self._rich_log = rich_log
        yield rich_log

    def write_log(self, level: str, message: str) -> None:
        """Write a styled log message to the panel.

        Args:
            level: The log level (debug, info, warning, error, critical).
            message: The log message text.
        """
        if self._rich_log is None:
            return

        style = self.LEVEL_STYLES.get(level.lower(), "white")
        level_tag = level.upper().ljust(8)
        self._rich_log.write(f"[{style}]{level_tag}[/] {message}")

    def write_error(self, message: str) -> None:
        """Write an error message prominently to the log panel."""
        if self._rich_log is None:
            return
        self._rich_log.write(f"[red bold]ERROR    {message}[/]")

    def write_info(self, message: str) -> None:
        """Write an informational system message to the log panel."""
        if self._rich_log is None:
            return
        self._rich_log.write(f"[dim]{message}[/]")


# ─── Status Bar Widget ────────────────────────────────────────────────


class StatusBarWidget(Widget):
    """Bottom status bar showing current job status and key bindings."""

    DEFAULT_CSS = """
    StatusBarWidget {
        dock: bottom;
        height: 1;
        width: 100%;
        background: $accent;
        color: $text;
        padding: 0 1;
    }
    """

    status_text: reactive[str] = reactive("Ready")

    def render(self) -> str:
        return f" {self.status_text} │ q: quit │ Ctrl+C: cancel"

    def set_status(self, text: str) -> None:
        """Update the status bar text."""
        self.status_text = text
