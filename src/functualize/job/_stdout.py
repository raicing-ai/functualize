"""Stdout capability — the explicit stdout data channel for job functions.

Re-exports the protocol from the shared vocabulary in ``_types``. The engine
injects a concrete implementation per invocation.
"""

from functualize._types.stdout import Stdout

__all__ = ["Stdout"]
