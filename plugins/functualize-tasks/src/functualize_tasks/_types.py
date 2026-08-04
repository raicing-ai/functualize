"""Shared types for the Tasks Domain SDK."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TaskStatus(StrEnum):
    """Status of a task item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class TaskLink:
    """Specifies what a task is optionally linked to.

    Attributes:
        kind: The type of link — "job", "workflow_step", or "job_phase".
        target: The identifier of the linked entity.
    """

    kind: str  # "job" | "workflow_step" | "job_phase"
    target: str


@dataclass(frozen=True)
class TaskItem:
    """A single task with id, title, status, and optional metadata.

    Attributes:
        id: Unique identifier of the task.
        title: Human-readable title of the task.
        status: Current status of the task.
        linked_to: Optional link to a job, workflow step, or job phase.
        notes: Optional free-form notes.
        creator: Optional identifier of who created the task.
        created_at: Optional UNIX timestamp of creation time.
    """

    id: str
    title: str
    status: TaskStatus
    linked_to: TaskLink | None = None
    notes: str | None = None
    creator: str | None = None
    created_at: float | None = None
