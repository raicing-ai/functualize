"""Shared types for the State Domain SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutionRecord:
    """A record of a single job execution."""

    execution_id: str
    job_name: str
    session_id: str
    status: str  # "running" | "success" | "failure"
    started_at: float
    ended_at: float | None = None
    duration_ms: float | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)
    result: Any = None


@dataclass(frozen=True)
class PhaseRecord:
    """A record of a phase within an execution."""

    name: str
    status: str
    started_at: float
    ended_at: float | None = None
    duration_ms: float | None = None


@dataclass(frozen=True)
class SessionRecord:
    """A record of a session."""

    session_id: str
    started_at: float
    metadata: dict[str, Any] = field(default_factory=dict)
