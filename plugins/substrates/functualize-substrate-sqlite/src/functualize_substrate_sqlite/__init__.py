"""SQLite-backed runtime state for functualize.

One substrate, installed at boot. See `substrate.py` for why this replaced a
key-value `StateBackend`, and `contributor/adr/022` for why that idea is
retired rather than deferred.
"""

from functualize_substrate_sqlite._plugin import SQLiteSubstratePlugin
from functualize_substrate_sqlite.substrate import SQLiteSubstrate

__all__ = [
    "SQLiteSubstratePlugin",
    "SQLiteSubstrate",
]
