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


def _parse_provided_fields(
    tokens: list[str],
    positional_names: list[str] | None = None,
) -> dict[str, str]:
    """Parse the job's own arguments into ``{field_name: value}``.

    Handles ``--key value`` and ``--key=value``, converting CLI flag names
    (``--my-flag``) to Python field names (``my_flag``). Bare tokens bind to
    ``positional_names`` in order — a required positional is *given* by being
    typed, not by being named, and without this it was reported missing while
    sitting in plain sight on the bar.

    Args:
        tokens: The job's own arguments — the walk's remainder, never the raw
            tail, which for a grouped job still holds the path segments.
        positional_names: The job's positional fields, in declaration order.
    """
    provided: dict[str, str] = {}
    remaining_positionals = list(positional_names or [])
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
        elif not token.startswith("-") and remaining_positionals:
            provided[remaining_positionals.pop(0)] = token
        i += 1
    return provided


async def get_missing_required_args(
    introspector: InProcessIntrospector,
    tokens: list[str],
) -> MissingArgsResult | None:
    """Analyze tokens to find missing required arguments.

    The tokens are walked to a job the way the shell navigates — one path
    segment per token, group flags consumed where they are declared — so
    ``deploy --env prod web run`` finds `deploy.web.run`. Matching the bar's
    first token against the job list instead returned ``None`` for every
    grouped job, which reads as "not a command" and silently switched the whole
    analysis off rather than reporting anything missing.

    Returns None when the tokens do not reach a runnable job. The job's own
    arguments — the walk's remainder, never the raw tail — are parsed for
    ``--key value`` pairs and compared against its required parameters.
    """
    if not tokens:
        return None

    from functualize._cli.tui.cli_arg_parser import (
        build_group_option_trie,
        resolve_tui_command,
    )

    resolution = resolve_tui_command(build_group_option_trie(introspector._app), tokens)
    job_name = resolution.job_name

    # Return None if the walk did not reach a job
    if job_name is None or job_name not in introspector.job_names:
        return None

    # Find the matching job's effective fields (config_fields preferred)
    jobs = introspector._app.get_jobs()
    job_params: list[FieldDescriptor] = []
    for job in jobs:
        if job.name == job_name:
            job_params = job.config_fields if job.config_fields else job.parameters
            break

    # Parse the job's own arguments — named flags and bare positionals alike.
    raw_provided = _parse_provided_fields(
        resolution.args,
        [p.name for p in job_params if getattr(p, "positional", False)],
    )

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
