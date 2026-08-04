"""SQLite State Plugin — DI registration and scope lifecycle integration.

Registers SQLiteStateBackend as StateBackend and SQLiteExecutionStore as
ExecutionStore with the DI registry via app.provide(). Hooks into
ON_SCOPE_CREATED to replace the scope's in-memory state with persistent
SQLite-backed storage.

Registered via entry point `functualize.state_providers` with name "sqlite".
"""

from __future__ import annotations

import logging
from typing import Any

from functualize_state import ExecutionStore, StateBackend

from functualize_state_sqlite._backend import SQLiteStateBackend
from functualize_state_sqlite._execution_store import SQLiteExecutionStore
from functualize_state_sqlite.sqlite_backend import SQLiteBackend
from functualize_state_sqlite.state_store import SQLiteStateStore

__all__ = ["SQLiteStatePlugin"]

logger = logging.getLogger(__name__)


class SQLiteStatePlugin:
    """Plugin that registers SQLite-backed StateBackend and ExecutionStore.

    At boot time (APP_READY), creates SQLiteStateBackend and SQLiteExecutionStore
    instances sharing the same database path, and registers them with the DI
    registry via app.provide().

    When a WorkflowScope is created, replaces its in-memory state store with
    a persistent SQLiteStateStore backed by the shared SQLiteBackend.

    Implements the plugin callable protocol expected by functualize's plugin
    discovery system.
    """

    name: str = "sqlite-state"
    version: str = "0.1.0"
    description: str = "SQLite-backed StateBackend and ExecutionStore provider"

    def __init__(self) -> None:
        self._backend: SQLiteStateBackend | None = None
        self._execution_store: SQLiteExecutionStore | None = None
        self._scope_backend: SQLiteBackend | None = None
        self._app: Any = None

    @property
    def backend(self) -> SQLiteStateBackend | None:
        """The SQLiteStateBackend instance (available after APP_READY)."""
        return self._backend

    @property
    def execution_store(self) -> SQLiteExecutionStore | None:
        """The SQLiteExecutionStore instance (available after APP_READY)."""
        return self._execution_store

    def __call__(self, app: Any) -> None:
        """Register the plugin with the application instance.

        Hooks into APP_READY for initialization and DI registration,
        and ON_SCOPE_CREATED for scope state replacement.
        """
        self._app = app
        hook_registry = app.hook_registry

        from functualize._events.hooks import HookEvent

        # APP_READY: initialize backend, execution store, and register with DI
        hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)

        # ON_SCOPE_CREATED: replace scope state with SQLite-backed store
        hook_registry.register_global(
            HookEvent.ON_SCOPE_CREATED, self._on_scope_created
        )

    def on_shutdown(self, app: Any) -> None:
        """Close database connections on application shutdown."""
        if self._backend is not None:
            try:
                self._backend.close()
                logger.debug("SQLiteStatePlugin: SQLiteStateBackend closed.")
            except Exception as e:
                logger.error("SQLiteStatePlugin: Error closing backend: %s", e)
            finally:
                self._backend = None

        if self._execution_store is not None:
            try:
                self._execution_store.close()
                logger.debug("SQLiteStatePlugin: SQLiteExecutionStore closed.")
            except Exception as e:
                logger.error("SQLiteStatePlugin: Error closing execution store: %s", e)
            finally:
                self._execution_store = None

        if self._scope_backend is not None:
            try:
                self._scope_backend.close()
                logger.debug("SQLiteStatePlugin: scope SQLiteBackend closed.")
            except Exception as e:
                logger.error("SQLiteStatePlugin: Error closing scope backend: %s", e)
            finally:
                self._scope_backend = None

    # ─── Hook Handlers ────────────────────────────────────────────────

    def _on_app_ready(self, app: Any) -> None:
        """Initialize SQLite instances and register with DI registry.

        Creates SQLiteStateBackend and SQLiteExecutionStore sharing the same
        database path, runs schema migrations, and registers both with the
        app's DI registry as their respective protocol types.

        Also initializes the scope-level SQLiteBackend (old-style) for use
        in ON_SCOPE_CREATED to replace scope state stores.
        """
        try:
            # Resolve db_path from config if available
            db_path = self._resolve_db_path(app)

            # Initialize the scope-level backend (old-style) first.
            # This uses the composite-key state table (scope_id, job_namespace, key)
            # which is the format SQLiteStateStore expects.
            # It owns the primary database file.
            scope_db_path = db_path
            self._scope_backend = SQLiteBackend(db_path=scope_db_path)
            self._scope_backend.initialize()

            # Create the protocol-conforming StateBackend and ExecutionStore.
            # These share the same database as the scope backend. The
            # SQLiteStateBackend uses a separate table name to avoid conflicts
            # with the old-style composite-key state table.
            self._backend = SQLiteStateBackend(db_path=str(self._scope_backend.db_path))
            self._execution_store = SQLiteExecutionStore(
                db_path=str(self._scope_backend.db_path)
            )

            # Run schema migrations
            from functualize_state_sqlite._migrations import migrate

            migrate(self._scope_backend.connection)

            # Register with DI registry via app.provide()
            app.provide(StateBackend, self._backend)
            app.provide(ExecutionStore, self._execution_store)

            logger.debug(
                "SQLiteStatePlugin: Registered StateBackend and ExecutionStore (db=%s)",
                self._scope_backend.db_path,
            )
        except Exception as e:
            logger.error("SQLiteStatePlugin: Failed to initialize: %s", e)

    def _on_scope_created(self, scope: Any) -> None:
        """Replace the scope's in-memory state store with SQLite-backed state.

        Creates a SQLiteStateStore scoped to the workflow scope's ID, backed
        by the shared SQLiteBackend (old-style) that uses the composite-key
        state table for proper namespace isolation per scope.
        """
        if self._scope_backend is None:
            return

        try:
            scope_id = scope.scope_id if hasattr(scope, "scope_id") else str(id(scope))

            sqlite_store = SQLiteStateStore(
                backend=self._scope_backend,
                scope_id=scope_id,
                job_namespace="__scope__",
            )
            scope.replace_state_store(sqlite_store)
            logger.debug(
                "SQLiteStatePlugin: Replaced state store for scope '%s'",
                scope_id,
            )
        except Exception as e:
            logger.error("SQLiteStatePlugin: Error in ON_SCOPE_CREATED handler: %s", e)

    # ─── Internal Helpers ─────────────────────────────────────────────

    def _resolve_db_path(self, app: Any) -> str | None:
        """Resolve database path from app configuration.

        Returns None to use the default path if no configuration is found.
        """
        try:
            from pydantic import BaseModel, Field

            class _SqliteConfig(BaseModel):
                db_path: str | None = Field(
                    default=None,
                    description="Path to the SQLite database file.",
                )

            config = app.resolve_model("plugin.sqlite-state", _SqliteConfig)
            return config.db_path
        except Exception:
            # No config available — use default path
            return None
