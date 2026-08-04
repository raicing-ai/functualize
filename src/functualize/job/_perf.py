"""Perf capability — performance measurement interface.

Re-exports from the canonical implementation in _engine/capabilities.
"""

from functualize._engine.capabilities.perf import Perf, Phase

__all__ = ["Perf", "Phase"]
