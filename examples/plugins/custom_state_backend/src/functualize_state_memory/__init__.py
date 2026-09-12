"""functualize-state-memory: an in-memory `StoreSubstrate`, as a plugin.

Demonstrates the one seam a storage plugin fills — *give me this document, put
this document back, and stop anyone else while I do both*. Everything above it
(what a scope is, which document refuses an unreadable read) stays on the
stores.

`contributor/adr/022` is why this is the seam: it used to be a key-value
`StateBackend`, and a backend-agnostic key-value protocol can only offer the
intersection of every backend.
"""

from functualize_state_memory._backend import MemorySubstrate
from functualize_state_memory._plugin import MemoryStatePlugin

__all__ = ["MemoryStatePlugin", "MemorySubstrate"]
