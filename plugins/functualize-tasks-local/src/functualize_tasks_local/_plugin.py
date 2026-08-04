"""Local Tasks Plugin — DI registration.

Registers LocalTaskProvider as TaskProvider with the DI registry via
app.provide(). Uses the active StateBackend for task storage with
keys prefixed ``tasks:``.

Registered via entry point ``functualize.tasks_providers`` with name "local".
"""

from __future__ import annotations

import logging
from typing import Any

from functualize_state import StateBackend
from functualize_tasks import TaskProvider

from functualize_tasks_local._provider import LocalTaskProvider

__all__ = ["LocalTasksPlugin"]

logger = logging.getLogger(__name__)


class LocalTasksPlugin:
    """Plugin that registers a local StateBackend-backed TaskProvider.

    At boot time (APP_READY), resolves the active StateBackend from the DI
    registry, creates a LocalTaskProvider wrapping it, and registers the
    provider as the TaskProvider implementation via app.provide().

    Implements the plugin callable protocol expected by functualize's plugin
    discovery system.
    """

    name: str = "tasks-local"
    version: str = "0.1.0"
    description: str = "Local state-backed TaskProvider using tasks: prefix"

    def __init__(self) -> None:
        self._provider: LocalTaskProvider | None = None

    @property
    def provider(self) -> LocalTaskProvider | None:
        """The LocalTaskProvider instance (available after APP_READY)."""
        return self._provider

    def __call__(self, app: Any) -> None:
        """Register the plugin with the application instance.

        Hooks into APP_READY for initialization and DI registration.
        """
        from functualize._events.hooks import HookEvent

        app.hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)

    def _on_app_ready(self, app: Any) -> None:
        """Initialize LocalTaskProvider and register with DI registry.

        Resolves the StateBackend from the DI registry and creates a
        LocalTaskProvider backed by it. Registers the provider as
        TaskProvider via app.provide().
        """
        try:
            # Resolve the active StateBackend from DI
            backend = app.resolve(StateBackend)

            # Create local provider backed by the state backend
            self._provider = LocalTaskProvider(backend=backend)

            # Register as TaskProvider
            app.provide(TaskProvider, self._provider)

            logger.debug(
                "LocalTasksPlugin: Registered TaskProvider (state-backed, "
                "prefix='tasks:')"
            )
        except Exception as e:
            logger.error("LocalTasksPlugin: Failed to initialize: %s", e)
