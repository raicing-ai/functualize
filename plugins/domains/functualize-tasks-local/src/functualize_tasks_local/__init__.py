"""Functualize Tasks Local Plugin — state-backed task storage.

Provides a TaskProvider implementation that stores tasks in the active
StateBackend using keys prefixed with ``tasks:``. Zero external dependencies.
"""

from functualize_tasks_local._plugin import LocalTasksPlugin
from functualize_tasks_local._provider import LocalTaskProvider

__all__ = [
    "LocalTasksPlugin",
    "LocalTaskProvider",
]
