"""Audit job — opted in via the module-level marker variable.

The ``__functualize__`` assignment makes this the only file that passes
require_file_marker = "__functualize__". It deliberately has no "job_"
prefix, no functualize import, and no decorators.
"""

__functualize__ = True


def audit(strict: bool = False) -> str:
    """Audit the project configuration."""
    mode = "strict" if strict else "lenient"
    print(msg := f"Audit passed ({mode})")
    return msg
