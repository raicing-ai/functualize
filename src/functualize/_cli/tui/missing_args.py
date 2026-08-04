"""Missing required arguments detection for the inline TUI.

Analyzes current tokens against a job's required parameters to determine
which are missing, enabling the TUI to show what needs filling before
execution can proceed.

This module is in the ``_cli/`` layer — it imports ONLY from public API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize._cli.introspect import InProcessIntrospector
    from functualize.types import FieldDescriptor


@dataclass(frozen=True)
class MissingArgsResult:
    """Result of analyzing which required args are missing."""

    job_name: str
    missing_fields: list[FieldDescriptor]
    provided_fields: dict[str, str]  # field_name -> value
    is_executable: bool  # True if no required fields are missing

    @property
    def missing_count(self) -> int:
        """Number of missing required fields."""
        return len(self.missing_fields)


def _parse_provided_fields(tokens: list[str]) -> dict[str, str]:
    """Parse --key value and --key=value pairs from tokens into a dict.

    Converts flag names from CLI format (--my-flag) to Python field names
    (my_flag) by replacing hyphens with underscores.
    """
    provided: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("--"):
            if "=" in token:
                # --key=value syntax
                key, _, value = token[2:].partition("=")
                field_name = key.replace("-", "_")
                provided[field_name] = value
            else:
                # --key value syntax
                field_name = token[2:].replace("-", "_")
                if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                    provided[field_name] = tokens[i + 1]
                    i += 1
                else:
                    # Flag without value (boolean flag or missing value)
                    provided[field_name] = ""
        i += 1
    return provided


async def get_missing_required_args(
    introspector: InProcessIntrospector,
    tokens: list[str],
) -> MissingArgsResult | None:
    """Analyze tokens to find missing required arguments.

    Returns None if tokens[0] is not a recognized job name.
    Parses --key value pairs from tokens[1:] and compares against the
    job's required parameters to identify missing fields.
    """
    if not tokens:
        return None

    job_name = tokens[0]

    # Return None if not a recognized job
    if job_name not in introspector.job_names:
        return None

    # Find the matching job's effective fields (config_fields preferred)
    jobs = introspector._app.get_jobs()
    job_params: list[FieldDescriptor] = []
    for job in jobs:
        if job.name == job_name:
            job_params = job.config_fields if job.config_fields else job.parameters
            break

    # Parse provided --key value pairs from remaining tokens
    raw_provided = _parse_provided_fields(tokens[1:])

    # Filter provided_fields to only include valid parameter names
    valid_param_names = {p.name for p in job_params}
    provided_fields = {k: v for k, v in raw_provided.items() if k in valid_param_names}

    # Find missing required fields
    missing_fields = [
        p for p in job_params if p.required and p.name not in provided_fields
    ]

    is_executable = len(missing_fields) == 0

    return MissingArgsResult(
        job_name=job_name,
        missing_fields=missing_fields,
        provided_fields=provided_fields,
        is_executable=is_executable,
    )
