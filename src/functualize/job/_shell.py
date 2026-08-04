"""Shell capability — subprocess execution for job functions.

Re-exports the protocol and value types from the shared vocabulary in
``_types``. The engine injects a concrete implementation per invocation.
"""

from functualize._types.shell import (
    FailingResponder,
    Responder,
    Shell,
    ShellError,
    ShellResult,
)

__all__ = [
    "FailingResponder",
    "Responder",
    "Shell",
    "ShellError",
    "ShellResult",
]
