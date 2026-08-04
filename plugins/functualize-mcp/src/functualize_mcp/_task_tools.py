"""MCP Task tools — manage tasks via MCP when the Tasks domain is active.

Provides add_task, list_tasks, update_task, and plan_tasks MCP tools.
These tools are conditionally exposed only when the functualize-tasks
domain SDK is installed.

plan_tasks replaces the entire task list with the provided batch.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import asdict
from typing import Any

__all__ = ["MCPTaskToolRegistry"]

logger = logging.getLogger(__name__)


def _task_item_to_dict(task: Any) -> dict[str, Any]:
    """Convert a TaskItem to a serializable dict.

    Args:
        task: A TaskItem instance.

    Returns:
        A dict representation suitable for MCP responses.
    """
    data = asdict(task)
    # Convert TaskStatus enum to string value
    if hasattr(data.get("status"), "value"):
        data["status"] = data["status"].value
    elif isinstance(data.get("status"), str):
        pass  # Already a string
    else:
        data["status"] = str(data.get("status", ""))
    return data


class MCPTaskToolRegistry:
    """Registers MCP task management tools when the Tasks domain is available.

    Tools are only registered if the functualize-tasks package can be
    imported. This ensures the MCP server doesn't fail when the Tasks
    domain is not installed.

    Args:
        app: The FunctualizeApp instance providing DI and job registry.
    """

    def __init__(self, app: Any) -> None:
        self._app = app
        self._tasks: Any = None

    def _get_tasks(self) -> Any:
        """Resolve the Tasks capability from the app's DI registry.

        Returns:
            The Tasks capability instance, or None if unavailable.
        """
        if self._tasks is not None:
            return self._tasks

        try:
            from functualize_tasks import Tasks

            # Try to resolve from DI
            if hasattr(self._app, "resolve"):
                self._tasks = self._app.resolve(Tasks)
            elif hasattr(self._app, "_tasks"):
                self._tasks = self._app._tasks
        except Exception:
            pass

        # Fallback: create an in-memory Tasks instance
        if self._tasks is None:
            try:
                from functualize_tasks import Tasks

                self._tasks = Tasks()
            except ImportError:
                pass

        return self._tasks

    def register_tools(self, mcp: Any) -> None:
        """Register task MCP tools with the FastMCP server instance.

        Only registers if functualize-tasks is importable.

        Args:
            mcp: The FastMCP instance to register tools with.
        """
        try:
            from functualize_tasks import Tasks  # noqa: F401
        except ImportError:
            logger.debug(
                "MCPTaskToolRegistry: functualize-tasks not installed, "
                "skipping task tool registration."
            )
            return

        mcp.add_tool(self._add_task)
        mcp.add_tool(self._list_tasks)
        mcp.add_tool(self._update_task)
        mcp.add_tool(self._plan_tasks)
        logger.info("MCPTaskToolRegistry: Registered 4 task MCP tools")

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _add_task(
        self,
        title: str,
        linked_to_kind: str | None = None,
        linked_to_target: str | None = None,
    ) -> dict[str, Any]:
        """Create a new task with an optional link.

        Args:
            title: Human-readable title for the task.
            linked_to_kind: Optional link kind ("job", "workflow_step", or "job_phase").
            linked_to_target: Optional link target identifier.

        Returns:
            Dict with the new task_id, or an error response.
        """
        tasks = self._get_tasks()
        if tasks is None:
            return _error_response(
                "tasks_not_available",
                "Tasks domain is not available.",
            )

        try:
            from functualize_tasks import TaskLink

            linked_to = None
            if linked_to_kind and linked_to_target:
                linked_to = TaskLink(kind=linked_to_kind, target=linked_to_target)

            task_id = tasks.add(title, linked_to=linked_to)
            return {"task_id": task_id}
        except Exception as e:
            logger.error("MCPTaskToolRegistry: Error adding task: %s", e)
            return _error_response("task_error", f"Failed to add task: {e}")

    _add_task.__name__ = "add_task"
    _add_task.__qualname__ = "add_task"
    _add_task.__doc__ = (
        "Create a new task. Returns the generated task_id. "
        "Args: title — task title; linked_to_kind — optional link kind "
        "(job, workflow_step, job_phase); linked_to_target — optional link target."
    )

    async def _list_tasks(
        self,
        status: str | None = None,
        filter: str | None = None,
    ) -> dict[str, Any]:
        """List tasks, optionally filtered by status or title substring.

        Args:
            status: Optional status filter (pending, in_progress, done, skipped, blocked).
            filter: Optional title substring filter.

        Returns:
            Dict with "tasks" key containing list of task dicts.
        """
        tasks = self._get_tasks()
        if tasks is None:
            return _error_response(
                "tasks_not_available",
                "Tasks domain is not available.",
            )

        try:
            from functualize_tasks import TaskStatus

            task_status = None
            if status is not None:
                try:
                    task_status = TaskStatus(status)
                except ValueError:
                    return _error_response(
                        "invalid_status",
                        f"Invalid status '{status}'. Valid values: "
                        f"{[s.value for s in TaskStatus]}",
                    )

            items = tasks.list(status=task_status, filter=filter)
            return {"tasks": [_task_item_to_dict(item) for item in items]}
        except Exception as e:
            logger.error("MCPTaskToolRegistry: Error listing tasks: %s", e)
            return _error_response("task_error", f"Failed to list tasks: {e}")

    _list_tasks.__name__ = "list_tasks"
    _list_tasks.__qualname__ = "list_tasks"
    _list_tasks.__doc__ = (
        "List tasks with optional filtering. "
        "Args: status — filter by status (pending, in_progress, done, skipped, blocked); "
        "filter — filter by title substring."
    )

    async def _update_task(
        self,
        task_id: str,
        status: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Update a task's status and/or notes.

        Args:
            task_id: The unique identifier of the task to update.
            status: Optional new status (pending, in_progress, done, skipped, blocked).
            notes: Optional new notes.

        Returns:
            Dict with "updated" key on success, or an error response.
        """
        tasks = self._get_tasks()
        if tasks is None:
            return _error_response(
                "tasks_not_available",
                "Tasks domain is not available.",
            )

        try:
            from functualize_tasks import TaskStatus

            task_status = None
            if status is not None:
                try:
                    task_status = TaskStatus(status)
                except ValueError:
                    return _error_response(
                        "invalid_status",
                        f"Invalid status '{status}'. Valid values: "
                        f"{[s.value for s in TaskStatus]}",
                    )

            tasks.update(task_id, status=task_status, notes=notes)
            return {"updated": True, "task_id": task_id}
        except Exception as e:
            if "TaskNotFoundError" in type(e).__name__ or "not found" in str(e).lower():
                return _error_response(
                    "task_not_found",
                    f"Task '{task_id}' does not exist.",
                )
            logger.error("MCPTaskToolRegistry: Error updating task: %s", e)
            return _error_response("task_error", f"Failed to update task: {e}")

    _update_task.__name__ = "update_task"
    _update_task.__qualname__ = "update_task"
    _update_task.__doc__ = (
        "Update a task's status or notes. "
        "Args: task_id — ID of the task; status — new status "
        "(pending, in_progress, done, skipped, blocked); notes — new notes."
    )

    async def _plan_tasks(
        self,
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace the entire task list with the provided batch.

        Deletes all existing tasks and creates new ones from the provided
        list. Each task dict should have at minimum a "title" key.
        Optional keys: "linked_to_kind", "linked_to_target", "status", "notes".

        Args:
            tasks: List of task dicts to replace the current task list.

        Returns:
            Dict with "planned" key containing count and new task_ids.
        """
        tasks_cap = self._get_tasks()
        if tasks_cap is None:
            return _error_response(
                "tasks_not_available",
                "Tasks domain is not available.",
            )

        try:
            from functualize_tasks import TaskLink, TaskStatus

            # Step 1: Delete all existing tasks
            existing = tasks_cap.list()
            for item in existing:
                with contextlib.suppress(Exception):
                    tasks_cap.delete(item.id)

            # Step 2: Add all tasks from the provided batch
            new_ids: list[str] = []
            for task_spec in tasks:
                title = task_spec.get("title", "")
                if not title:
                    continue

                linked_to = None
                kind = task_spec.get("linked_to_kind")
                target = task_spec.get("linked_to_target")
                if kind and target:
                    linked_to = TaskLink(kind=kind, target=target)

                task_id = tasks_cap.add(title, linked_to=linked_to)

                # Apply status if specified (default is PENDING)
                status_str = task_spec.get("status")
                if status_str and status_str != "pending":
                    try:
                        task_status = TaskStatus(status_str)
                        tasks_cap.update(task_id, status=task_status)
                    except (ValueError, Exception):
                        pass  # Keep default status on error

                # Apply notes if specified
                notes = task_spec.get("notes")
                if notes:
                    tasks_cap.update(task_id, notes=notes)

                new_ids.append(task_id)

            return {
                "planned": True,
                "count": len(new_ids),
                "task_ids": new_ids,
            }
        except Exception as e:
            logger.error("MCPTaskToolRegistry: Error planning tasks: %s", e)
            return _error_response("task_error", f"Failed to plan tasks: {e}")

    _plan_tasks.__name__ = "plan_tasks"
    _plan_tasks.__qualname__ = "plan_tasks"
    _plan_tasks.__doc__ = (
        "Replace the entire task list with a new batch. Deletes all existing "
        "tasks and creates new ones from the provided list. "
        "Args: tasks — list of task objects with 'title' (required), "
        "'linked_to_kind', 'linked_to_target', 'status', 'notes' (optional)."
    )


def _error_response(error_code: str, message: str) -> dict[str, Any]:
    """Build a structured error response dict.

    Args:
        error_code: Machine-readable error code.
        message: Human-readable error message.

    Returns:
        Dict with "error" key containing code and message.
    """
    return {
        "error": {
            "code": error_code,
            "message": message,
        }
    }
