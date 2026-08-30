"""JobContext frozen dataclass — immutable execution context metadata.

Provides per-invocation identity (name, trace_id, span_id), deadline tracking,
working directory paths, invoke depth tracking, scope identification,
and arbitrary read-only metadata via MappingProxyType.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from functualize._engine.capabilities.spec import CapabilitySpec


@dataclass(frozen=True)
class JobContext:
    """Immutable execution context for the current job invocation.

    Attributes:
        name: The job name being executed.
        trace_id: Optional distributed trace identifier.
        span_id: Optional 16 hex-character span identifier from PropagationContext.
        deadline: Optional deadline after which the job should abort.
        cwd: Optional working directory for the job execution.
        job_directory: Optional filesystem directory containing the job's source module.
        invoke_depth: Nesting depth of invocations (0 at top-level, increments per nest).
        scope_id: Optional active WorkflowScope ID.
        metadata: Read-only mapping of arbitrary key-value metadata.
    """

    name: str
    trace_id: str | None = None
    span_id: str | None = None
    deadline: datetime | None = None
    cwd: Path | None = None
    job_directory: Path | None = None
    invoke_depth: int = 0
    scope_id: str | None = None
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if self.invoke_depth < 0:
            raise ValueError(f"invoke_depth must be >= 0, got {self.invoke_depth}")


# ── Registry entry (ADR-014) ───────────────────────────────────────────────


def _make_job_context(ctx: Any) -> JobContext:
    """Wire JobContext with the identity of the invocation in progress."""
    from functualize._events.tracing import current_context as _current_ctx

    prop_ctx = _current_ctx()
    span_id = prop_ctx.span_id if prop_ctx.is_active else None

    scope_id: str | None = None
    if ctx.context.parent_scope is not None:
        scope_id = getattr(ctx.context.parent_scope, "scope_id", None)

    return JobContext(
        name=ctx.context.job_name,
        span_id=span_id,
        cwd=ctx.context.cwd,
        job_directory=ctx.context.job_directory,
        invoke_depth=ctx.context.invoke_depth,
        scope_id=scope_id,
    )


CAPABILITY = CapabilitySpec(
    name="JobContext",
    type=JobContext,
    factory=_make_job_context,
)
