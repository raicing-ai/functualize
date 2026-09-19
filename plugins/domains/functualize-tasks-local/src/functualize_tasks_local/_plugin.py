"""Local Tasks Plugin — DI registration.

Registers LocalTaskProvider as TaskProvider with the DI registry via
app.di.provide(). Uses the app's substrate for task storage with
keys prefixed ``tasks:``.

Registered via entry point ``functualize.tasks_providers`` with name "local".
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from functualize_tasks import TaskProvider

from functualize_tasks_local._provider import LocalTaskProvider

if TYPE_CHECKING:
    from functualize.plugin import PluginHost

__all__ = ["LocalTasksPlugin"]

logger = logging.getLogger(__name__)


class LocalTasksPlugin:
    """Plugin that registers a local substrate-backed TaskProvider.

    At boot time (APP_READY) it registers a `LocalTaskProvider` as the
    TaskProvider implementation via `app.di.provide()`. The provider reads the
    app's substrate lazily, on first use, so installing this plugin cannot
    decide which storage the project ends up with.

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

    def __call__(self, app: PluginHost) -> None:
        """Register the plugin with the application instance.

        Hooks into APP_READY for initialization and DI registration.
        """
        app.hooks.on_ready(self._on_app_ready)

    def _on_app_ready(self, app: PluginHost) -> None:
        """Register a `LocalTaskProvider` over the app's substrate.

        Backed by the **app's own substrate** (`store-substrate`/T6), not by a
        `StateBackend` resolved from DI. That protocol is retired, and with it
        the failure it allowed: tasks written while a database plugin was
        installed were invisible to a reader without one, because the two
        answered "where does state live" separately.

        **The substrate is passed as a callable, not read here**
        (`plugin-taxonomy`/T7, AC-8). Reading `app.substrate` at `APP_READY`
        *resolves and caches* the engine's substrate, after which a plugin
        installing a database is refused — and the refusal used to be swallowed.
        So whether a project got SQLite or the filesystem depended on which
        plugin's hook ran first, which is the loader's topological sort with an
        **alphabetical** tiebreak: it came down to the spelling of a plugin's
        name. Measured, before the fix — the same two plugins, only the name
        changed::

            name 'tasks-local'    (sorts after  substrate-sqlite) -> SQLiteSubstrate
            name 'a-tasks-local'  (sorts before substrate-sqlite) -> JsonFileSubstrate

        Deferring the read removes the coupling rather than ordering it, and
        matches the engine, which resolves lazily for exactly this reason.
        """
        try:
            self._provider = LocalTaskProvider(lambda: app.substrate)
            app.di.provide(TaskProvider, self._provider)
            logger.debug("LocalTasksPlugin: registered a substrate-backed TaskProvider")
        except Exception as e:
            logger.error("LocalTasksPlugin: Failed to initialize: %s", e)
