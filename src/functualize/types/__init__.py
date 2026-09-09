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
from functualize._types.http_status import http_status_for_status
from functualize._types.run_request import RUN_SURFACES, RunRequest, RunSurface

__all__ = [
    "RUN_SURFACES",
    "RunRequest",
    "RunSurface",
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
    # Every delivery surface that answers over HTTP maps a terminal RunStatus
    # to a status code. Exported here, beside RunStatus itself, so a trigger
    # plugin consumes the one table instead of writing a second opinion.
    "http_status_for_status",
]
