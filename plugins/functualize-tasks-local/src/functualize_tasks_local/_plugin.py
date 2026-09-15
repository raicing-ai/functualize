"""Local Tasks Plugin — DI registration.

Registers LocalTaskProvider as TaskProvider with the DI registry via
app.di.provide(). Uses the app's substrate for task storage with
keys prefixed ``tasks:``.

Registered via entry point ``functualize.tasks_providers`` with name "local".
"""

from __future__ import annotations

import logging
from typing import Any

from functualize_tasks import TaskProvider

from functualize_tasks_local._provider import LocalTaskProvider, TaskDocument

__all__ = ["LocalTasksPlugin"]

logger = logging.getLogger(__name__)


class LocalTasksPlugin:
    """Plugin that registers a local substrate-backed TaskProvider.

    At boot time (APP_READY), takes the app's substrate, wraps it in a
    `TaskDocument`, and registers a `LocalTaskProvider` over that as the
    TaskProvider implementation via app.di.provide().

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

        Backed by the **app's own substrate** (`store-substrate`/T6), not by a
        `StateBackend` resolved from DI. That protocol is retired, and with it
        the failure it allowed: tasks written while a database plugin was
        installed were invisible to a reader without one, because the two
        answered "where does state live" separately.
        """
        try:
            backend = TaskDocument(app.execution_engine.substrate)
            self._provider = LocalTaskProvider(backend=backend)

            # Register as TaskProvider
            app.di.provide(TaskProvider, self._provider)

            logger.debug(
                "LocalTasksPlugin: Registered TaskProvider (substrate-backed, "
                "prefix='tasks:')"
            )
        except Exception as e:
            logger.error("LocalTasksPlugin: Failed to initialize: %s", e)
