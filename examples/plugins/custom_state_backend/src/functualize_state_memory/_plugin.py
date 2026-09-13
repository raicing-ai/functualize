"""Plugin boot class for the in-memory substrate.

Discovered through the ``functualize.state_providers`` entry point and called
with the app at boot. It registers **one** thing — the substrate — and every
store follows, because there is one place that decides where documents live.

This used to register a `StateBackend` into the DI registry, which is a seam
that no longer exists: `contributor/adr/022` records why a backend-agnostic
key-value domain was retired. The shape here mirrors
`functualize-state-sqlite`'s plugin exactly, which is the point — a substrate
in a dict and a substrate in a database are installed the same way.
"""

from __future__ import annotations

import logging
from typing import Any

from functualize_state_memory._backend import MemorySubstrate

__all__ = ["MemoryStatePlugin"]

logger = logging.getLogger(__name__)


class MemoryStatePlugin:
    """Installs a :class:`MemorySubstrate` as the app's substrate at boot.

    Entry point configuration in pyproject.toml::

        [project.entry-points."functualize.state_providers"]
        memory-ttl = "functualize_state_memory:MemoryStatePlugin"
    """

    name: str = "state-memory"
    version: str = "0.2.0"
    description: str = "Keeps this project's runtime state in memory"

    def __init__(self) -> None:
        self._substrate: MemorySubstrate | None = None

    @property
    def substrate(self) -> MemorySubstrate | None:
        """The substrate this plugin installed, or None before APP_READY."""
        return self._substrate

    def __call__(self, app: Any) -> None:
        from functualize._events.hooks import HookEvent

        app.hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)

    def _on_app_ready(self, app: Any) -> None:
        """Choose the substrate once, before anything has resolved one.

        `APP_READY` and not later: the engine resolves its substrate lazily, on
        the first store access, and installing after that is **refused** rather
        than half-applied — some of a run's documents in one backend and some in
        another is the state the substrate seam exists to make unreachable.
        """
        self._substrate = MemorySubstrate()
        app.substrate = self._substrate
        logger.debug("state-memory installed an in-memory substrate")
