"""Freshness capability — the verdict a job's own ``Fingerprint`` produced.

Re-exports from the canonical implementation in _engine/capabilities.
"""

from functualize._engine.capabilities.freshness import Freshness, FreshnessVerdict

__all__ = ["Freshness", "FreshnessVerdict"]
