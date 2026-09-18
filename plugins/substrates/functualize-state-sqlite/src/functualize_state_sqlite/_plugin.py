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
from typing import TYPE_CHECKING, cast

from functualize_state_sqlite.substrate import SQLiteSubstrate

if TYPE_CHECKING:
    from functualize.plugin import PluginHost

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

    def __call__(self, app: PluginHost) -> None:
        app.hooks.on_ready(self._on_app_ready)

    def _on_app_ready(self, app: PluginHost) -> None:
        """Choose the substrate, once, before anything has resolved one.

        `APP_READY` is the right moment and not an arbitrary one: the engine
        resolves its substrate lazily, on the first store access, which happens
        during a run. Installing later is **refused** by the app rather than
        allowed to half-apply — some of a run's documents in one backend and
        some in the other is exactly the state this feature exists to make
        unreachable.

        **A failure to install is raised, not logged** (`plugin-taxonomy`/T7,
        AC-4). This reverses an earlier decision, and the reversal is the point:
        the swallow read as "a working program with a note in the log rather
        than a boot that dies over a storage preference", which is only true if
        the fallback is harmless. It is not. A user who installed a storage
        plugin and silently got the filesystem has their project's data in a
        place they did not choose and were not told about — and
        `install_substrate`'s own refusal message says why that matters: some of
        a run's documents in one backend and some in the other.

        The log line was also unreachable as a diagnostic. The failure it hid
        was the ordering bug T7 fixes, and `logger.exception` at boot goes to a
        stream most users never see; the symptom they *did* see was a database
        that stayed empty.
        """
        self._substrate = SQLiteSubstrate(self._db_path(app))
        app.install_substrate(self._substrate)
        logger.debug("sqlite-state installed a substrate at %s", self._substrate.path)

    def _db_path(self, app: PluginHost) -> Path:
        """``plugin.sqlite-state.db_path``, or wherever this project's state goes.

        Resolved from :attr:`fresh_root` rather than the cwd, so a later
        ``chdir`` cannot move a run's database out from under it — and routed
        through ``resolve_fresh_location``, which is **the same call the
        filesystem substrate makes** (``_primitives/substrate.py``:
        ``JsonFileSubstrate.for_project``). The two backends therefore put a
        project's documents in the same directory, and disagreeing about *where*
        a project's state lives is not a thing a storage plugin can do.

        **This used to be ``fresh_root / ".functualize"``, and that was a bug**
        — unreachable until `plugin-taxonomy`/T5 made this plugin load at all.
        Creating ``.functualize/`` is the documented switch from *standalone*
        mode to *project* mode, so merely installing this plugin silently
        promoted every directory a user ran in, and littered a database beside
        every loose script. ``func`` is meant to run over loose scripts
        anywhere; standalone mode keeps their state in the XDG cache keyed by
        project id, which is exactly what ``resolve_fresh_location`` returns
        when there is no project.
        """
        configured = self._configured_path(app)
        if configured:
            return Path(configured)

        # `functualize.app.utils` is public API — a plugin is entitled to it,
        # and this is the one question a substrate plugin must not answer for
        # itself.
        from functualize.app.utils import resolve_fresh_location

        return resolve_fresh_location(Path(app.fresh_root))[0].parent / DEFAULT_DB_NAME

    @staticmethod
    def _configured_path(app: PluginHost) -> str | None:
        try:
            from pydantic import BaseModel, Field

            class _SqliteConfig(BaseModel):
                db_path: str | None = Field(
                    default=None,
                    description="Where this project's SQLite state lives.",
                )

            # `resolve_model` is declared `-> object` on the facade and so on
            # the port, so the caller narrows -- it is the one that named the
            # model class. Under `app: Any` this read was unchecked; the cast
            # is where that check now happens.
            resolved = cast(
                "_SqliteConfig",
                app.configuration.resolve_model("plugin.sqlite-state", _SqliteConfig),
            )
            return resolved.db_path
        except Exception:
            return None
