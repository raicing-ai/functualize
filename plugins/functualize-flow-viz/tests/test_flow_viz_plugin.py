"""Tests for the flow-viz plugin as a hosted LiveConstruct.

The plugin used to be a self-rendering Surface with two hand-rolled renderers
(``PlainTextRenderer`` / ``InlineTTYRenderer``); this suite replaced the tests
written around those. What matters now is:

- ``handle_event`` builds the right tree state from the event stream,
- ``__rich__`` renders that state as a ``rich.tree.Tree``,
- the plugin registers as an *ambient* construct with a sensible predicate,
- the config lever actually suppresses registration.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from functualize_flow_viz import FlowVizConstruct, FlowVizPlugin, TreeNode
from rich.console import Console


class _Event:
    """Minimal stand-in for a StructuredEvent."""

    def __init__(self, event_name: str, resource: str = "", **payload: Any) -> None:
        self.event_name = event_name
        self.resource = resource
        self.payload = payload


def _render(construct: FlowVizConstruct) -> str:
    console = Console(file=io.StringIO(), width=100, force_terminal=False)
    console.print(construct.__rich__())
    return console.file.getvalue()  # type: ignore[union-attr]


# ─── Tree state from events ───────────────────────────────────────────


def test_job_started_creates_the_root() -> None:
    c = FlowVizConstruct()
    c.handle_event(_Event("job.execute.start", job_name="deploy", invoke_depth=0))

    assert c._root is not None
    assert c._root.label == "deploy"
    assert c._root.status == "running"
    assert "deploy" in _render(c)


def test_job_completed_marks_the_root_successful() -> None:
    c = FlowVizConstruct()
    c.handle_event(_Event("job.execute.start", job_name="deploy", invoke_depth=0))
    c.handle_event(_Event("job.execute.end", job_name="deploy", status="success"))

    assert c._root is not None
    assert c._root.status == "success"
    assert c._root.end_time is not None


def test_job_failed_marks_the_root_failed() -> None:
    c = FlowVizConstruct()
    c.handle_event(_Event("job.execute.start", job_name="deploy", invoke_depth=0))
    c.handle_event(_Event("job.execute.error", job_name="deploy"))

    assert c._root is not None
    assert c._root.status == "failure"


def test_invoke_depth_nests_a_child_under_the_job() -> None:
    c = FlowVizConstruct()
    c.handle_event(_Event("job.execute.start", job_name="deploy", invoke_depth=0))
    c.handle_event(_Event("job.execute.start", job_name="migrate", invoke_depth=1))
    c.handle_event(_Event("job.execute.end", job_name="migrate", status="success"))

    assert c._root is not None
    assert [child.label for child in c._root.children] == ["migrate"]
    assert c._root.children[0].status == "success"

    rendered = _render(c)
    assert "deploy" in rendered
    assert "migrate" in rendered


def test_deeper_invoke_depth_nests_and_unwinds() -> None:
    c = FlowVizConstruct()
    c.handle_event(_Event("job.execute.start", job_name="deploy", invoke_depth=0))
    c.handle_event(_Event("job.execute.start", job_name="migrate", invoke_depth=1))
    c.handle_event(_Event("job.execute.start", job_name="seed", invoke_depth=2))

    assert c.current_node is not None
    assert c.current_node.label == "seed"

    c.handle_event(_Event("job.execute.end", job_name="seed", status="success"))
    assert c.current_node is not None
    assert c.current_node.label == "migrate"

    c.handle_event(_Event("job.execute.end", job_name="migrate", status="success"))
    assert c.current_node is c._root

    assert c._root is not None
    migrate = c._root.children[0]
    assert [g.label for g in migrate.children] == ["seed"]


def test_failed_child_is_marked_failure() -> None:
    c = FlowVizConstruct()
    c.handle_event(_Event("job.execute.start", job_name="deploy", invoke_depth=0))
    c.handle_event(_Event("job.execute.start", job_name="migrate", invoke_depth=1))
    c.handle_event(_Event("job.execute.error", job_name="migrate"))

    assert c._root is not None
    assert c._root.children[0].status == "failure"


def test_custom_events_attach_to_the_current_node() -> None:
    c = FlowVizConstruct()
    c.handle_event(_Event("job.execute.start", job_name="deploy", invoke_depth=0))
    c.handle_event(_Event("upload.chunk", resource="s3://bucket"))

    assert c._root is not None
    assert any("upload.chunk" in e for e in c._root.events)
    assert "upload.chunk" in _render(c)


def test_progress_payload_renders_a_bar() -> None:
    c = FlowVizConstruct()
    c.handle_event(_Event("job.execute.start", job_name="deploy", invoke_depth=0))
    c.handle_event(_Event("upload.progress", progress=50))

    assert c._root is not None
    recorded = c._root.events[0]
    assert "█" in recorded and "░" in recorded
    assert "50%" in recorded


def test_custom_event_before_any_job_still_renders() -> None:
    """Events with no job scope must not be silently dropped."""
    c = FlowVizConstruct()
    c.handle_event(_Event("standalone.thing"))

    assert c._root is not None
    assert "standalone.thing" in _render(c)


def test_empty_construct_renders_without_error() -> None:
    assert _render(FlowVizConstruct()) is not None


def test_each_construct_has_independent_state() -> None:
    """The plugin registers a factory, so runs must not share a tree."""
    a, b = FlowVizConstruct(), FlowVizConstruct()
    a.handle_event(_Event("job.execute.start", job_name="first", invoke_depth=0))

    assert b._root is None


# ─── Node rendering ───────────────────────────────────────────────────


def test_node_line_includes_icon_and_duration() -> None:
    node = TreeNode(label="deploy", status="success", start_time=0.0, end_time=1.5)
    line = node.render_line()

    assert "deploy" in line
    assert "✓" in line
    assert "1.5s" in line


def test_pending_node_has_no_duration_suffix() -> None:
    assert TreeNode(label="deploy").render_line().strip().endswith("deploy")


# ─── Plugin registration ──────────────────────────────────────────────


class _FakeSettings:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values = values or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


class _FakeApp:
    def __init__(self, settings: _FakeSettings | None = None) -> None:
        self.settings = settings
        self.registered: list[tuple[Any, str, Any]] = []

    def register_ambient_construct(
        self, factory: Any, *, name: str | None = None, predicate: Any = None
    ) -> None:
        self.registered.append((factory, name or "", predicate))


class _Descriptor:
    def __init__(self, uses_invoke: bool = False, workflow_steps: Any = None) -> None:
        self.uses_invoke = uses_invoke
        self.workflow_steps = workflow_steps or []


def test_plugin_registers_an_ambient_construct() -> None:
    app = _FakeApp()
    FlowVizPlugin()(app)

    assert len(app.registered) == 1
    factory, name, predicate = app.registered[0]
    assert factory is FlowVizConstruct
    assert name == "flow-viz"
    assert predicate is not None


def test_plugin_registers_a_factory_not_an_instance() -> None:
    """Each run needs fresh tree state, so registration must pass the class."""
    app = _FakeApp()
    FlowVizPlugin()(app)

    factory = app.registered[0][0]
    assert isinstance(factory(), FlowVizConstruct)
    assert factory() is not factory()


@pytest.mark.parametrize(
    ("descriptor", "expected"),
    [
        (_Descriptor(uses_invoke=True), True),
        (_Descriptor(workflow_steps=["a", "b"]), True),
        (_Descriptor(uses_invoke=False), False),
        (_Descriptor(workflow_steps=["only-one"]), False),
        (None, False),
    ],
)
def test_predicate_targets_jobs_with_branches(descriptor: Any, expected: bool) -> None:
    """The tree renders only where it has something to show."""
    app = _FakeApp()
    FlowVizPlugin()(app)
    predicate = app.registered[0][2]

    assert predicate(descriptor) is expected


def test_disabled_by_config_skips_registration() -> None:
    app = _FakeApp(_FakeSettings({"flow-viz.enabled": False}))
    FlowVizPlugin()(app)

    assert app.registered == []


def test_disabled_by_string_config_skips_registration() -> None:
    app = _FakeApp(_FakeSettings({"flow-viz.enabled": "false"}))
    FlowVizPlugin()(app)

    assert app.registered == []


def test_enabled_by_default_without_settings() -> None:
    app = _FakeApp(_FakeSettings({}))
    FlowVizPlugin()(app)

    assert len(app.registered) == 1


def test_plugin_is_not_a_prompt_collector() -> None:
    """It draws; it must never win prompt resolution."""
    assert not hasattr(FlowVizPlugin(), "collect")
