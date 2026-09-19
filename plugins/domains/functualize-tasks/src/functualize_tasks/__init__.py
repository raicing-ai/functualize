"""functualize-tasks — Tasks Domain SDK.

Provides the Tasks capability class, TaskProvider protocol, shared types,
errors, event constants, and testing doubles for task management.
"""

from functualize_tasks._errors import TaskNotFoundError
from functualize_tasks._events import (
    TASKS_COMPLETED,
    TASKS_CREATED,
    TASKS_DELETED,
    TASKS_UPDATED,
)
from functualize_tasks._metadata import domain_metadata
from functualize_tasks._protocols import TaskProvider
from functualize_tasks._tasks import Tasks
from functualize_tasks._types import TaskItem, TaskLink, TaskStatus
from functualize_tasks.testing._mock_tasks import MockTaskOperation, MockTasks

__all__ = [
    # Capability Class
    "Tasks",
    # Protocols
    "TaskProvider",
    # Types
    "TaskItem",
    "TaskLink",
    "TaskStatus",
    # Errors
    "TaskNotFoundError",
    # Event Constants
    "TASKS_CREATED",
    "TASKS_UPDATED",
    "TASKS_COMPLETED",
    "TASKS_DELETED",
    # Testing Doubles
    "MockTaskOperation",
    "MockTasks",
    # Metadata
    "domain_metadata",
]
