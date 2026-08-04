"""Plugin boot class for the Memory TTL state backend.

This class is discovered via the entry point and called with
the FunctualizeApp instance during boot. It registers the
backend implementation with the DI registry.
"""

from __future__ import annotations

from typing import Any

from functualize_state_memory._backend import MemoryTTLBackend


class MemoryTTLPlugin:
    """Plugin boot class — registered via functualize.state_providers entry point.

    Entry point configuration in pyproject.toml:
        [project.entry-points."functualize.state_providers"]
        memory-ttl = "functualize_state_memory:MemoryTTLPlugin"
    """

    name = "state-memory-ttl"
    domain = "state"

    def __call__(self, app: Any) -> None:
        """Boot the plugin — register MemoryTTLBackend with DI.

        Args:
            app: The FunctualizeApp instance.
        """
        from functualize_state import StateBackend

        # Read TTL from config (default: 1 hour)
        default_ttl = 3600.0  # Could read from app config

        backend = MemoryTTLBackend(default_ttl=default_ttl)
        app.provide(StateBackend, backend)
