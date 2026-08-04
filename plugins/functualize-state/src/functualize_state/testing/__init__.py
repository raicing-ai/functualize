"""Testing doubles for the State Domain SDK.

Provides in-memory implementations usable without installing any implementation plugin.
"""

from functualize_state.testing._in_memory import InMemoryState

__all__ = [
    "InMemoryState",
]
