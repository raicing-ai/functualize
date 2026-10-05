"""The plugin: make the SQLite runtime store selectable, and nothing else.

Installing this package used to *choose* storage: the plugin offered a
`SQLiteSubstrate` at boot, so every document of every project quietly moved
into ``state.db``. Selection is now configuration. The plugin registers
:class:`SqliteRuntimeStoreFactory` under the scheme ``sqlite``, and boot step
6.5 prepares it only when ``runtime_store.url`` names that scheme::

    [runtime_store]
    url = "sqlite:"      # the project's state.db; absent → the document store

Selected, the store migrates its schema and refuses to start rather than
degrade; not selected, the plugin changes nothing — except that a ``state.db``
already holding this project's runtime data stops boot with the remedy, rather
than letting the document store come up and leave that data unread (D-3).

The former setting ``plugin.substrate-sqlite.db_path`` is gone: the location
is part of the URL (``sqlite:///abs/path.db``, ``sqlite:rel/path.db``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory

if TYPE_CHECKING:
    from functualize.plugin import PluginHost

__all__ = ["SQLiteSubstratePlugin"]


class SQLiteSubstratePlugin:
    """Registers the SQLite runtime store; selecting it is configuration."""

    name: str = "substrate-sqlite"
    version: str = "0.2.0"
    description: str = "Keeps this project's documents in SQLite"

    def __call__(self, app: PluginHost) -> None:
        app.register_runtime_store_factory(SqliteRuntimeStoreFactory())
