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
from functualize._types.exit_codes import ExitCode, exit_code_for_status
from functualize._types.flag_grammar import (
    GLOBAL_BOOL_FLAGS,
    GLOBAL_OPTIONS_ALWAYS_VALUE,
    GLOBAL_OPTIONS_OPTIONAL_VALUE,
    GLOBAL_OPTIONS_WITH_VALUE,
    OPTIONAL_VALUE_VALID_SET,
    flag_aliases,
    match_group_flag,
    negative_aliases,
    negative_flag_for,
)
from functualize._types.http_status import http_status_for_status
from functualize._types.outcome import (
    Family,
    is_failure,
    report_line,
    status_from_wire,
    wire_value,
)
from functualize._types.run_request import RUN_SURFACES, RunRequest, RunSurface

__all__ = [
    "ExitCode",
    "exit_code_for_status",
    "Family",
    "is_failure",
    "report_line",
    "status_from_wire",
    "wire_value",
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
    "GLOBAL_OPTIONS_ALWAYS_VALUE",
    "GLOBAL_OPTIONS_OPTIONAL_VALUE",
    "OPTIONAL_VALUE_VALID_SET",
    "GLOBAL_OPTIONS_WITH_VALUE",
    "GLOBAL_BOOL_FLAGS",
    "flag_aliases",
    "negative_aliases",
    "match_group_flag",
    "negative_flag_for",
]
