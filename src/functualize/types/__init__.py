"""Public types directory — shared vocabulary for functualize users.

This module re-exports frozen dataclasses and enums that form the shared
type vocabulary for job authors, plugin authors, and app constructors.

Usage::

    from functualize.types import JobResult, JobDescriptor, RunStatus
"""

from functualize._types import (
    CacheInfo,
    ConfigFileInfo,
    FieldDescriptor,
    JobDescriptor,
    JobResult,
    Secret,
)
from functualize._types.enums import (
    ConfigFileRole,
    EnvironmentSource,
    JobPhase,
    RunStatus,
    RunType,
)

__all__ = [
    "JobResult",
    "JobDescriptor",
    "FieldDescriptor",
    "RunStatus",
    "RunType",
    "JobPhase",
    "CacheInfo",
    "ConfigFileInfo",
    "ConfigFileRole",
    "EnvironmentSource",
    "Secret",
]
