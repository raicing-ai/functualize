"""Unit tests for MCPTaskToolRegistry — MCP task management tools.

Tests add_task, list_tasks, update_task, and plan_tasks tools
with conditional exposure and error handling.
"""

from __future__ import annotations

import asyncio
from typing import Any

from functualize_mcp._task_tools import MCPTaskToolRegistry

# ---------------------------------------------------------------------------
# Test helpers — minimal app fake
# ---------------------------------------------------------------------------


class FakeApp:
    """Minimal fake FunctualizeApp for testing MCPTaskToolRegistry."""

    def __init__(self) -> None:
        self._resolved: dict[type, Any] = {}

    def resolve(self, cls: type) -> Any:
        if cls in self._resolved:
            return self._resolved[cls]
        raise KeyError(f"No provider for {cls}")

    def provide(self, cls: type, instance: Any) -> None:
        self._resolved[cls] = instance


class FakeMCP:
    """Fake FastMCP that tracks registered tools."""

    def __init__(self) -> None:
        self.tools: list[Any] = []

    def add_tool(self, fn: Any) -> None:
        self.tools.append(fn)


# ---------------------------------------------------------------------------
# Tests for conditional registration
# ---------------------------------------------------------------------------


class TestTaskToolRegistration:
    """Tests for conditional task tool registration."""

    def test_registers_tools_when_tasks_domain_available(self):
        """Task tools are registered when functualize-tasks is importable."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)
        mcp = FakeMCP()

        registry.register_tools(mcp)

        # functualize-tasks is installed in the workspace
        assert len(mcp.tools) == 4
        tool_names = [t.__name__ for t in mcp.tools]
        assert "add_task" in tool_names
        assert "list_tasks" in tool_names
        assert "update_task" in tool_names
        assert "plan_tasks" in tool_names


# ---------------------------------------------------------------------------
# Tests for add_task
# ---------------------------------------------------------------------------


class TestAddTask:
    """Tests for the add_task tool."""

    def test_add_task_returns_task_id(self):
        """add_task creates a task and returns its ID."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        result = asyncio.run(registry._add_task("Buy groceries"))

        assert "task_id" in result
        assert isinstance(result["task_id"], str)
        assert len(result["task_id"]) > 0

    def test_add_task_with_link(self):
        """add_task creates a task with a link when kind and target provided."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        result = asyncio.run(
            registry._add_task(
                "Deploy service",
                linked_to_kind="job",
                linked_to_target="deploy",
            )
        )

        assert "task_id" in result

    def test_add_task_without_link(self):
        """add_task creates a task without link when no kind/target."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        result = asyncio.run(registry._add_task("Simple task"))

        assert "task_id" in result
        assert "error" not in result


# ---------------------------------------------------------------------------
# Tests for list_tasks
# ---------------------------------------------------------------------------


class TestListTasks:
    """Tests for the list_tasks tool."""

    def test_list_tasks_empty(self):
        """list_tasks returns empty list when no tasks exist."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        result = asyncio.run(registry._list_tasks())

        assert "tasks" in result
        assert result["tasks"] == []

    def test_list_tasks_after_adding(self):
        """list_tasks returns all tasks after adding some."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        asyncio.run(registry._add_task("Task 1"))
        asyncio.run(registry._add_task("Task 2"))

        result = asyncio.run(registry._list_tasks())

        assert "tasks" in result
        assert len(result["tasks"]) == 2

    def test_list_tasks_filter_by_status(self):
        """list_tasks filters by status when provided."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        asyncio.run(registry._add_task("Pending task"))
        # Add a task and complete it
        add_result = asyncio.run(registry._add_task("Done task"))
        asyncio.run(registry._update_task(add_result["task_id"], status="done"))

        result = asyncio.run(registry._list_tasks(status="done"))

        assert "tasks" in result
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["title"] == "Done task"

    def test_list_tasks_filter_by_title(self):
        """list_tasks filters by title substring when filter provided."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        asyncio.run(registry._add_task("Buy milk"))
        asyncio.run(registry._add_task("Buy bread"))
        asyncio.run(registry._add_task("Clean house"))

        result = asyncio.run(registry._list_tasks(filter="Buy"))

        assert "tasks" in result
        assert len(result["tasks"]) == 2

    def test_list_tasks_invalid_status(self):
        """list_tasks returns error for invalid status value."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        result = asyncio.run(registry._list_tasks(status="invalid_status"))

        assert "error" in result
        assert result["error"]["code"] == "invalid_status"


# ---------------------------------------------------------------------------
# Tests for update_task
# ---------------------------------------------------------------------------


class TestUpdateTask:
    """Tests for the update_task tool."""

    def test_update_task_status(self):
        """update_task changes task status."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        add_result = asyncio.run(registry._add_task("My task"))
        task_id = add_result["task_id"]

        result = asyncio.run(registry._update_task(task_id, status="in_progress"))

        assert result["updated"] is True
        assert result["task_id"] == task_id

    def test_update_task_notes(self):
        """update_task sets notes on a task."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        add_result = asyncio.run(registry._add_task("My task"))
        task_id = add_result["task_id"]

        result = asyncio.run(registry._update_task(task_id, notes="Some notes"))

        assert result["updated"] is True

    def test_update_task_invalid_status(self):
        """update_task returns error for invalid status."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        add_result = asyncio.run(registry._add_task("My task"))
        task_id = add_result["task_id"]

        result = asyncio.run(registry._update_task(task_id, status="bogus"))

        assert "error" in result
        assert result["error"]["code"] == "invalid_status"

    def test_update_task_not_found(self):
        """update_task returns error for nonexistent task."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)
        # Force the Tasks instance to be created
        registry._get_tasks()

        result = asyncio.run(registry._update_task("nonexistent_id", status="done"))

        assert "error" in result
        assert result["error"]["code"] == "task_not_found"


# ---------------------------------------------------------------------------
# Tests for plan_tasks
# ---------------------------------------------------------------------------


class TestPlanTasks:
    """Tests for the plan_tasks tool."""

    def test_plan_tasks_replaces_all(self):
        """plan_tasks deletes existing tasks and creates the batch."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        # Add some existing tasks
        asyncio.run(registry._add_task("Old task 1"))
        asyncio.run(registry._add_task("Old task 2"))

        # Plan new tasks
        new_tasks = [
            {"title": "New task A"},
            {"title": "New task B"},
            {"title": "New task C"},
        ]
        result = asyncio.run(registry._plan_tasks(new_tasks))

        assert result["planned"] is True
        assert result["count"] == 3
        assert len(result["task_ids"]) == 3

        # Verify old tasks are gone and new ones exist
        list_result = asyncio.run(registry._list_tasks())
        titles = [t["title"] for t in list_result["tasks"]]
        assert "Old task 1" not in titles
        assert "Old task 2" not in titles
        assert "New task A" in titles
        assert "New task B" in titles
        assert "New task C" in titles

    def test_plan_tasks_with_status(self):
        """plan_tasks applies status when specified."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        new_tasks = [
            {"title": "Done task", "status": "done"},
            {"title": "Pending task"},
        ]
        result = asyncio.run(registry._plan_tasks(new_tasks))

        assert result["planned"] is True
        assert result["count"] == 2

        # Verify status
        done_list = asyncio.run(registry._list_tasks(status="done"))
        assert len(done_list["tasks"]) == 1
        assert done_list["tasks"][0]["title"] == "Done task"

    def test_plan_tasks_with_links(self):
        """plan_tasks creates linked tasks."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        new_tasks = [
            {
                "title": "Linked task",
                "linked_to_kind": "job",
                "linked_to_target": "deploy",
            },
        ]
        result = asyncio.run(registry._plan_tasks(new_tasks))

        assert result["planned"] is True
        assert result["count"] == 1

    def test_plan_tasks_skips_empty_titles(self):
        """plan_tasks skips task entries with empty titles."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        new_tasks = [
            {"title": "Valid task"},
            {"title": ""},
            {"title": "Another valid task"},
        ]
        result = asyncio.run(registry._plan_tasks(new_tasks))

        assert result["count"] == 2

    def test_plan_tasks_empty_batch(self):
        """plan_tasks with empty batch deletes all tasks."""
        app = FakeApp()
        registry = MCPTaskToolRegistry(app)

        # Add existing tasks
        asyncio.run(registry._add_task("Existing"))

        result = asyncio.run(registry._plan_tasks([]))

        assert result["planned"] is True
        assert result["count"] == 0

        # Verify all tasks are gone
        list_result = asyncio.run(registry._list_tasks())
        assert len(list_result["tasks"]) == 0
