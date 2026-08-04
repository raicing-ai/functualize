"""Job middleware system — re-exports from canonical internal location.

The implementation lives in _engine/job_middleware.py. This module
provides backward-compatible imports for the public API surface.
"""

from functualize._engine.job_middleware import (
    MiddlewareEntry,
    MiddlewareRegistry,
    execute_middleware_chain,
)

__all__ = [
    "MiddlewareEntry",
    "MiddlewareRegistry",
    "execute_middleware_chain",
]
