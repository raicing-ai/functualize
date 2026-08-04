"""Execution context — the input to the middleware chain.

ExecutionContext carries all information needed by middleware and the
execution engine to process a single job invocation: job identity,
resolved kwargs, timing, and references to capabilities and hooks.

Only imports from `_types/`, `_primitives/`, `_events/`, and stdlib.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from functualize._types.enums import RunStatus


@dataclass
class ExecutionContext:
    """Context object passed through the execution middleware chain.

    Carries all state needed for a single job execution lifecycle:
    identity, resolved arguments, timing, and mutable metadata.

    Middleware can inspect and modify call_kwargs before execution,
    set metadata, or block execution by setting status to FAILURE.

    Attributes:
        job_name: Name of the job being executed.
        function: The callable job function.
        call_kwargs: Resolved keyword arguments for the job function.
        invoke_depth: Current recursion depth for nested invokes.
        cwd: Working directory for this execution.
        job_directory: Directory containing the job source file.
        start_time: Perf counter start time (set at context creation).
        status: Current execution status (middleware can set to block).
        metadata: Mutable metadata dict carried through execution.
        capabilities: Per-invocation capability instances (type → instance).
        config_class: Optional Pydantic model class for job config validation.
        parent_scope: Optional workflow scope propagated from parent invoke.
    """

    job_name: str
    function: Callable[..., Any]
    call_kwargs: dict[str, Any]
    invoke_depth: int = 0
    cwd: Path | None = None
    job_directory: Path | None = None
    start_time: float = field(default_factory=time.perf_counter)
    status: RunStatus = RunStatus.RUNNING
    metadata: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[type, Any] = field(default_factory=dict)
    config_class: type | None = None
    parent_scope: Any | None = None

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time in milliseconds since context creation."""
        return (time.perf_counter() - self.start_time) * 1000

    @property
    def is_blocked(self) -> bool:
        """Whether execution has been blocked by middleware."""
        return self.status == RunStatus.FAILURE

    def set_result_metadata(self, key: str, value: Any) -> None:
        """Store a key-value pair in the execution metadata dict.

        Enforces a maximum of 64 keys. Writes beyond the limit are
        silently discarded unless updating an existing key.

        Args:
            key: Metadata key.
            value: Metadata value.
        """
        if key in self.metadata or len(self.metadata) < 64:
            self.metadata[key] = value
