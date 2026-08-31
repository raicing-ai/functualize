"""Public job authoring API for functualize.

This package is the primary import point for job authors:

    from functualize.job import RunContext, Log, Invoke, Prompt, Perf, State
    from functualize.job import JobContext, JobConfigView
    from functualize.job import Arg, Option, Stdin

It also exports job decorator utilities for metadata and hooks.
"""

from typing import TYPE_CHECKING, Any

from functualize._types.from_job import FromJob
from functualize._types.job_declaration import (
    Call,
    Deps,
    Exec,
    Fingerprint,
    Guards,
    JobDeclaration,
    Precondition,
    Retry,
    call,
)
from functualize.job.capabilities import (
    TTY,
    FailingResponder,
    Invoke,
    JobConfigView,
    JobContext,
    Live,
    Log,
    Perf,
    Prompt,
    Responder,
    Shell,
    ShellError,
    ShellResult,
    Sources,
    State,
    Stdout,
    TerminalUnavailable,
)
from functualize.job.context import RunContext, RunStatus
from functualize.job.decorators import (
    _make_global_only_decorator,
    _make_hook_decorator,
    _make_middleware_decorator,
    job,
    suppress_live,
    surface_hint,
)
from functualize.job.markers import Arg, Option, Stdin

if TYPE_CHECKING:
    from functualize._types.group_options import GroupOptions


def __getattr__(name: str) -> Any:
    """Lazily materialize ``GroupOptions`` on first access (PEP 562).

    Defining a Pydantic ``BaseModel`` subclass runs pydantic's plugin loader,
    which imports every installed pydantic plugin — ``logfire`` pulls in
    ``rich``, for instance. ``functualize/__init__.py`` reaches this package on
    *every* functualize import, so defining the class eagerly would drag those
    dependencies into every process and break the CLI-dependency isolation
    guarantee (``tests/test_typer_isolation.py``, now a CLI-dependency absence test).

    Deferring costs nothing: only a project that actually declares group
    options ever touches the class, and ``from functualize.job import
    GroupOptions`` still works — Python falls back to this hook.
    """
    if name == "GroupOptions":
        from functualize._types.group_options import GroupOptions

        return GroupOptions
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Public API — capability types and RunContext
    "RunContext",
    "RunStatus",
    "FromJob",
    "Log",
    "Invoke",
    "Prompt",
    "Perf",
    "Shell",
    "ShellError",
    "ShellResult",
    "Responder",
    "FailingResponder",
    "Sources",
    "State",
    "Stdout",
    "JobContext",
    "JobConfigView",
    "TTY",
    "Live",
    "TerminalUnavailable",
    # CLI annotation markers
    "Arg",
    "Option",
    "Stdin",
    # Per-group declared flags (S6a)
    "GroupOptions",
    # Job declaration decorator + value objects
    "job",
    "JobDeclaration",
    "Deps",
    "Fingerprint",
    "Guards",
    "Exec",
    "Retry",
    "Precondition",
    "Call",
    "call",
    # Decorator utilities
    "_make_global_only_decorator",
    "_make_hook_decorator",
    "_make_middleware_decorator",
    "suppress_live",
    "surface_hint",
]
