"""JobContext frozen dataclass — immutable execution context metadata.

Re-exports from the canonical implementation in _engine/capabilities.
"""

from functualize._engine.capabilities.job_context import JobContext

__all__ = ["JobContext"]
