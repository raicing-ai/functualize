"""Tasks testing doubles — MockTasks.

Provides a deterministic, operation-capturing testing double for the Tasks
capability, suitable for unit and integration testing of jobs that use
task management features.
"""

from functualize_tasks.testing._mock_tasks import MockTaskOperation, MockTasks

__all__ = [
    "MockTaskOperation",
    "MockTasks",
]
