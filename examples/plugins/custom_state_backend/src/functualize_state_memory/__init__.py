"""functualize-state-memory-ttl: In-memory StateBackend with TTL support.

A custom state backend plugin demonstrating how to implement the
StateBackend protocol from functualize-state.
"""

from functualize_state_memory._backend import MemoryTTLBackend
from functualize_state_memory._plugin import MemoryTTLPlugin

__all__ = ["MemoryTTLBackend", "MemoryTTLPlugin"]
