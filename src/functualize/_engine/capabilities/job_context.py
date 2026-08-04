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
