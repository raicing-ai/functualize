"""Functualize Flow Viz Plugin — inline execution tree visualization.

Renders a live job execution tree — status icons, durations, nested
``rc.invoke()`` children, custom ``rc.emit`` events — as a hosted
``LiveConstruct``.

Architecture note: this plugin used to be a self-rendering ``Surface`` with two
hand-rolled renderers (a non-TTY plain-text printer and a TTY renderer doing
its own ANSI cursor math on a 0.5s daemon thread). That made it a second writer
competing for the cursor with whatever else was drawing — the collision class
the surface architecture exists to remove.

Now it is a construct **hosted by a live zone**. The zone (``StdoutSurface`` on
a direct run, ``PanelLiveZone`` in the TUI) owns the cursor and the refresh
cadence, and Rich's own ``Live`` handles non-TTY degradation by printing final
state only. That deletes the daemon thread, the cursor math, and the two-renderer
split in one move.

It registers as an **ambient construct**: it renders by default for jobs that
invoke children (where a tree has something to show), with no job-author code.
Users turn it off with ``[flow-viz] enabled = false``, ``[live] suppress``,
``@job(suppress_live=["flow-viz"])``, or ``live.suppress("flow-viz")``.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["FlowVizConstruct", "FlowVizPlugin", "TreeNode"]


# ─── Status Icons ─────────────────────────────────────────────────────

ICON_RUNNING = "⏳"
ICON_SUCCESS = "✓"
ICON_FAILURE = "✗"
ICON_PENDING = "○"
ICON_TIMEOUT = "⊘"

_STATUS_STYLES = {
    "running": "yellow",
    "success": "green",
    "failure": "red",
    "timeout": "red",
    "pending": "dim",
}


def _status_icon(status: str) -> str:
    """Return the icon for a status string."""
    return {
        "running": ICON_RUNNING,
        "success": ICON_SUCCESS,
        "failure": ICON_FAILURE,
        "timeout": ICON_TIMEOUT,
        "pending": ICON_PENDING,
    }.get(status, ICON_PENDING)


def _format_duration(duration_ms: float) -> str:
    """Format a duration in ms as a compact human string."""
    if duration_ms < 1000:
        return f"{duration_ms:.0f}ms"
    if duration_ms < 60_000:
        return f"{duration_ms / 1000:.1f}s"
    minutes = int(duration_ms // 60_000)
    seconds = (duration_ms % 60_000) / 1000
    return f"{minutes}m{seconds:.1f}s"


# ─── Tree Node ────────────────────────────────────────────────────────


@dataclass
class TreeNode:
    """A node in the execution tree representing a job or step."""

    label: str
    status: str = "pending"  # pending, running, success, failure, timeout
    start_time: float | None = None
    end_time: float | None = None
    children: list[TreeNode] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    depth: int = 0

    @property
    def duration_ms(self) -> float:
        """Elapsed duration in milliseconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time is not None else time.time()
        return (end - self.start_time) * 1000

    def render_line(self) -> str:
        """Render this node as a single line with icon, label, and duration."""
        icon = _status_icon(self.status)
        # `is not None`, not truthiness — matches `duration_ms` above, which
        # already treats 0.0 as a real start time rather than "unstarted".
        duration = (
            _format_duration(self.duration_ms) if self.start_time is not None else ""
        )
        suffix = f" ({duration})" if duration else ""
        return f"{icon} {self.label}{suffix}"


# ─── Live Construct ───────────────────────────────────────────────────


class FlowVizConstruct:
    """A ``LiveConstruct`` that renders the execution tree.

    ``__rich__()`` builds a ``rich.tree.Tree`` from current state;
    ``handle_event()`` mutates that state from the structured event stream.
    The hosting live zone decides when to repaint, so there is no refresh
    thread and no cursor management here.
    """

    name: str = "flow-viz"

    def __init__(self) -> None:
        self._root: TreeNode | None = None
        self._node_stack: list[TreeNode] = []

    # ─── Rendering ────────────────────────────────────────────────────

    def __rich__(self) -> Any:
        """Return a ``rich.tree.Tree`` for the current execution state."""
        from rich.tree import Tree

        if self._root is None:
            return Tree("")
        tree = Tree(self._styled(self._root))
        self._attach(tree, self._root)
        return tree

    def _styled(self, node: TreeNode) -> str:
        """Render one node's line with a status-appropriate style."""
        style = _STATUS_STYLES.get(node.status, "")
        line = node.render_line()
        return f"[{style}]{line}[/{style}]" if style else line

    def _attach(self, branch: Any, node: TreeNode) -> None:
        """Recursively attach a node's events and children to a Rich branch."""
        for event in node.events:
            branch.add(f"[dim]◆ {event}[/dim]")
        for child in node.children:
            child_branch = branch.add(self._styled(child))
            self._attach(child_branch, child)

    # ─── Event handling ───────────────────────────────────────────────

    @property
    def current_node(self) -> TreeNode | None:
        """The node currently receiving events (deepest open scope)."""
        if self._node_stack:
            return self._node_stack[-1]
        return self._root

    def handle_event(self, event: Any) -> None:
        """Update tree state from one structured event.

        The engine's job vocabulary is ``job.execute.start`` /
        ``job.execute.end`` / ``job.execute.error`` (see
        ``_events/_catalog_entries.py``). Nesting is **not** a separate
        ``invoke.*`` event pair — a child started via ``rc.invoke()`` emits the
        same ``job.execute.*`` names carrying an ``invoke_depth`` payload, so
        the tree is built from that depth rather than from an open/close stack.

        Caveat — the lifecycle branch is currently unreachable: ``job.execute.``
        is one of ``RunContext._FRAMEWORK_EVENT_PREFIXES``, which
        ``_dispatch_to_surfaces`` filters out, so surfaces (and therefore
        hosted constructs) only ever see custom ``rc.emit`` events. The
        handling is kept because it is the correct mapping the moment lifecycle
        events are surfaced, and because it costs nothing meanwhile. See
        ``contributor/architecture/event-vocabulary.md``.

        Unrecognized events are recorded on the current node rather than
        dropped, so a domain's custom ``rc.emit`` still shows up in the tree.
        """
        event_name = str(getattr(event, "event_name", "") or "")
        payload = getattr(event, "payload", {}) or {}
        resource = getattr(event, "resource", "") or ""

        if event_name == "job.execute.start":
            self._job_started(event_name, resource, payload)
        elif event_name in ("job.execute.end", "job.execute.error"):
            self._job_ended(event_name, resource, payload)
        else:
            self._record_custom(event_name, resource, payload)

    # ─── State transitions ────────────────────────────────────────────

    def _label_for(self, resource: str, payload: dict[str, Any], fallback: str) -> str:
        for key in ("job_name", "name", "step", "child_job_name"):
            value = payload.get(key)
            if value:
                return str(value)
        return resource or fallback

    def _job_started(
        self, event_name: str, resource: str, payload: dict[str, Any]
    ) -> None:
        """Open a node at the event's ``invoke_depth``.

        Depth 0 is the top-level job (the root); deeper events are children
        started by ``rc.invoke()``. Unwinding to the right parent by depth is
        what makes nesting work without paired invoke events.
        """
        label = self._label_for(resource, payload, "job")
        depth = _depth_of(payload)
        node = TreeNode(
            label=label, status="running", start_time=time.time(), depth=depth
        )

        if self._root is None or depth == 0:
            if self._root is None:
                self._root = node
                self._node_stack = [node]
            else:
                # A second depth-0 job in one window (a fresh run against a
                # reused construct): restart rather than graft onto the old
                # tree, which would misreport the previous run as this one.
                self._root = node
                self._node_stack = [node]
            return

        # Unwind to this node's parent, then attach.
        while self._node_stack and self._node_stack[-1].depth >= depth:
            self._node_stack.pop()
        parent = self._node_stack[-1] if self._node_stack else self._root
        parent.children.append(node)
        self._node_stack.append(node)

    def _job_ended(
        self, event_name: str, resource: str, payload: dict[str, Any]
    ) -> None:
        """Close the node this event terminates, matched by name then depth."""
        status = _status_from(event_name, payload)
        label = self._label_for(resource, payload, "job")

        for index in range(len(self._node_stack) - 1, -1, -1):
            node = self._node_stack[index]
            if node.label == label:
                node.status = status
                node.end_time = time.time()
                del self._node_stack[index:]
                return

        # No open node matched (a end without its start) — fall back to the
        # root so a completed run is never left rendering as still running.
        if self._root is not None and self._root.end_time is None:
            self._root.status = status
            self._root.end_time = time.time()

    def _record_custom(
        self, event_name: str, resource: str, payload: dict[str, Any]
    ) -> None:
        """Attach a custom ``rc.emit`` event to the current node."""
        node = self.current_node
        if node is None:
            # No job scope yet — start one so custom events are still visible.
            self._root = TreeNode(
                label="events", status="running", start_time=time.time()
            )
            node = self._root

        if "progress" in payload:
            progress = payload["progress"]
            bar_width = 20
            try:
                filled = int(bar_width * float(progress) / 100)
            except (TypeError, ValueError):
                filled = 0
            filled = max(0, min(bar_width, filled))
            bar = "█" * filled + "░" * (bar_width - filled)
            node.events.append(f"{event_name}: [{bar}] {progress}%")
        elif resource:
            node.events.append(f"{event_name} ({resource})")
        elif event_name:
            node.events.append(event_name)


def _depth_of(payload: dict[str, Any]) -> int:
    """Read ``invoke_depth`` off a job event payload (0 when absent)."""
    try:
        return max(0, int(payload.get("invoke_depth", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _status_from(event_name: str, payload: dict[str, Any]) -> str:
    """Derive a node status from a terminal event name or its payload."""
    if event_name.endswith(".error") or event_name.endswith(".failed"):
        return "failure"
    status = payload.get("status")
    if status is not None:
        value = getattr(status, "value", status)
        text = str(value).lower()
        if text in _STATUS_STYLES:
            return text
    return "success"


# ─── Plugin Class ─────────────────────────────────────────────────────


class FlowVizPlugin:
    """Registers the flow-viz tree as an ambient live construct.

    Implements PluginConfigProtocol (``__call__``) for auto-registration via
    the ``functualize.plugins`` entry point.

    Deliberately not a ``PromptCollector``: it draws, it does not ask. Giving
    it a stub ``collect`` would make it win prompt resolution and swallow
    prompts it cannot answer — and it auto-loads, so that would break
    prompting for every project that installs it.
    """

    name: str = "flow-viz"
    version: str = "0.2.0"
    description: str = "Inline flow visualization for job execution"

    def __call__(self, app: Any) -> None:
        """Register the construct as an ambient default, unless disabled."""
        if not _enabled(app):
            return
        with contextlib.suppress(Exception):
            app.register_ambient_construct(
                FlowVizConstruct,
                name="flow-viz",
                predicate=_renders_for,
            )


def _renders_for(descriptor: Any) -> bool:
    """Only render for jobs that invoke children — a tree needs branches.

    A single-step job's tree is one line that repeats what the log already
    says, so the default stays out of the way.
    """
    if descriptor is None:
        return False
    if getattr(descriptor, "uses_invoke", False):
        return True
    steps = getattr(descriptor, "workflow_steps", None)
    return bool(steps) and len(steps) > 1


def _enabled(app: Any) -> bool:
    """Whether ``[flow-viz] enabled`` permits registration (default True)."""
    try:
        settings = getattr(app, "settings", None)
        if settings is None:
            return True
        value = settings.get("flow-viz.enabled", True)
        if isinstance(value, str):
            return value.strip().lower() not in {"false", "0", "no", "off"}
        return bool(value)
    except Exception:
        return True
