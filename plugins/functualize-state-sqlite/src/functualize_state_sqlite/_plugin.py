"""The plugin: install a SQLite substrate, and nothing else.

`store-substrate`/T5, T6.

This used to be three things at once — a `StateBackend`, an `ExecutionStore`,
and a per-scope key-value store swapped in at `ON_SCOPE_CREATED`. All three are
gone, and the reason is the same one in all three cases: they were a *second*
storage vocabulary sitting beside the framework's own.

- The scope store swap happened one level below the real seam, so a scope could
  keep its job state in SQLite while the records describing it stayed on the
  filesystem. A resumed run then found its steps and not its variables.
- `StateBackend` and `ExecutionStore` were a backend-agnostic key-value
  protocol, which can only offer the intersection of every backend — worth
  least exactly where having a database is worth most. `contributor/adr/022`
  records that argument so it is not re-proposed.

What is left is one line of work: choose the substrate. Every store follows,
because there is one place that decides and one object handed to all of them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from functualize_state_sqlite.substrate import SQLiteSubstrate

__all__ = ["SQLiteStatePlugin"]

logger = logging.getLogger(__name__)

#: Where the database goes when nothing configures it. Beside the project's
#: other runtime state, so `func builtin data clear` and a `.gitignore` that
#: already covers `.functualize/` keep working.
DEFAULT_DB_NAME = "state.db"


class SQLiteStatePlugin:
    """Installs a :class:`SQLiteSubstrate` as the app's substrate at boot."""

    name: str = "sqlite-state"
    version: str = "0.2.0"
    description: str = "Keeps this project's runtime state in SQLite"

    def __init__(self) -> None:
        self._substrate: SQLiteSubstrate | None = None

    @property
    def substrate(self) -> SQLiteSubstrate | None:
        """The substrate this plugin installed, or None before APP_READY."""
        return self._substrate

    def __call__(self, app: Any) -> None:
        from functualize._events.hooks import HookEvent

        app.hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)

    def _on_app_ready(self, app: Any) -> None:
        """Choose the substrate, once, before anything has resolved one.

        `APP_READY` is the right moment and not an arbitrary one: the engine
        resolves its substrate lazily, on the first store access, which happens
        during a run. Installing later is **refused** by the app rather than
        allowed to half-apply — some of a run's documents in one backend and
        some in the other is exactly the state this feature exists to make
        unreachable.

        A failure to install is logged and left alone. The app then uses the
        filesystem default, which is a working program with a note in the log
        rather than a boot that dies over a storage preference.
        """
        try:
            self._substrate = SQLiteSubstrate(self._db_path(app))
            app.substrate = self._substrate
        except Exception:
            logger.exception(
                "sqlite-state could not install its substrate; this project "
                "will use the filesystem default"
            )
            return
        logger.debug("sqlite-state installed a substrate at %s", self._substrate.path)

    def _db_path(self, app: Any) -> Path:
        """``plugin.sqlite-state.db_path``, or beside the project's other state.

        Resolved from :attr:`fresh_root` rather than the cwd, so a later
        ``chdir`` cannot move a run's database out from under it — the same
        rule the filesystem substrate follows.
        """
        configured = self._configured_path(app)
        if configured:
            return Path(configured)
        return Path(app.fresh_root) / ".functualize" / DEFAULT_DB_NAME

    @staticmethod
    def _configured_path(app: Any) -> str | None:
        try:
            from pydantic import BaseModel, Field

            class _SqliteConfig(BaseModel):
                db_path: str | None = Field(
                    default=None,
                    description="Where this project's SQLite state lives.",
                )

            resolved = app.configuration.resolve_model(
                "plugin.sqlite-state", _SqliteConfig
            )
            return resolved.db_path
        except Exception:
            return None
