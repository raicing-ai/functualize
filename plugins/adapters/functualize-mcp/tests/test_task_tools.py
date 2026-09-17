"""Coverage for `MCPTaskToolRegistry`, which had none.

The registry once probed the host for a `resolve` method and then for a
private tasks attribute, inside a bare `except Exception: pass`. Neither
attribute exists on `FunctualizeApp`, so the probe could only ever fall
through to the in-memory `Tasks()` below it — and no test noticed, because no
test reached `_get_tasks` at all. Breaking that constructor left the whole
suite green (plugin-host-protocol/T1 sabotage, 2026-09-17).

These tests close that hole. The first is the regression guard for the
deletion itself: the registry must serve tasks without touching the host.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("functualize_tasks")

from functualize_mcp._task_tools import MCPTaskToolRegistry  # noqa: E402


class HostileApp:
    """An app that raises on *any* attribute access.

    The registry reads nothing from its app, so it must survive this. Before
    the probe was deleted, `hasattr` swallowed the raise and the DI branch was
    skipped — the same observable outcome by accident rather than by design.
    """

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the task registry must not read app.{name}")


class RecordingMCP:
    """Captures what `register_tools` hands to FastMCP."""

    def __init__(self) -> None:
        self.tools: list[Any] = []

    def add_tool(self, fn: Any) -> None:
        self.tools.append(fn)


def test_registry_serves_tasks_without_reading_the_app() -> None:
    registry = MCPTaskToolRegistry(HostileApp())

    tasks = registry._get_tasks()

    assert tasks is not None
    assert registry._get_tasks() is tasks, "the capability is built once"


def test_register_tools_registers_the_four_task_tools() -> None:
    mcp = RecordingMCP()

    MCPTaskToolRegistry(HostileApp()).register_tools(mcp)

    assert [fn.__name__ for fn in mcp.tools] == [
        "add_task",
        "list_tasks",
        "update_task",
        "plan_tasks",
    ]


@pytest.mark.asyncio
async def test_add_then_list_round_trips_through_the_tools() -> None:
    registry = MCPTaskToolRegistry(HostileApp())

    added = await registry._add_task("write the missing test")
    listed = await registry._list_tasks()

    assert "task_id" in added, added
    titles = [t["title"] for t in listed["tasks"]]
    assert "write the missing test" in titles


@pytest.mark.asyncio
async def test_update_reports_a_missing_task_rather_than_raising() -> None:
    registry = MCPTaskToolRegistry(HostileApp())

    result = await registry._update_task("no-such-task", status="done")

    assert result.get("error") is not None, result
