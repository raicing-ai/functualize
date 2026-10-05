"""SQLite-backed runtime state for functualize.

Registers the ``sqlite`` runtime store (`_factory.py`); a project selects it
with ``runtime_store.url = "sqlite:"``. `substrate.py` keeps the derived
documents (freshness, shell history) in the same file. See
`contributor/adr/022` for why a key-value `StateBackend` is retired rather
than deferred.
"""

from functualize_substrate_sqlite._factory import (
    LegacyImportRequired,
    SqliteRuntimeStoreFactory,
)
from functualize_substrate_sqlite._plugin import SQLiteSubstratePlugin
from functualize_substrate_sqlite._runtime_store import (
    SQLITE_PROFILE,
    SqliteRuntimeStore,
)
from functualize_substrate_sqlite.substrate import SQLiteSubstrate

__all__ = [
    "SQLITE_PROFILE",
    "LegacyImportRequired",
    "SQLiteSubstrate",
    "SQLiteSubstratePlugin",
    "SqliteRuntimeStore",
    "SqliteRuntimeStoreFactory",
]
