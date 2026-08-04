"""In-process command introspection for the inline TUI.

Replaces subprocess-based CommandIntrospector with direct queries to the
booted FunctualizeApp instance. Provides the same interface (completions,
help, executability) without shelling out.

This module is in the ``_cli/`` layer — it imports ONLY from public API.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from functualize._cli.builtins import builtin_descriptions

if TYPE_CHECKING:
    from functualize._cli.data.argument_history import ArgumentHistory
    from functualize.app.core import FunctualizeApp
    from functualize.types import FieldDescriptor


@dataclass(frozen=True)
class ValueCompletion:
    """A suggested value for a field."""

    value: str
    source: str  # "choices" | "history" | "path"
    description: str


class InProcessIntrospector:
    """Introspects CLI commands directly from a booted FunctualizeApp.

    Queries app.get_jobs() for command metadata, extracts options from
    function signatures, and determines executability without subprocess calls.
    """

    def __init__(
        self,
        app: FunctualizeApp,
        history: ArgumentHistory | None = None,
    ) -> None:
        self._app = app
        self._history = history
        self._job_names: list[str] | None = None

    @property
    def job_names(self) -> list[str]:
        """Lazily compute and cache job names."""
        if self._job_names is None:
            self._job_names = [j.name for j in self._app.get_jobs()]
        return self._job_names

    async def get_help_async(self, tokens: list[str]) -> str:
        """Get help text for a partial command from in-process metadata.

        For job commands, generates help from the JobDescriptor's docstring
        and parameters. For builtins, returns a minimal description.
        """
        if not tokens:
            return self._format_top_level_help()

        command_name = tokens[0]

        # Check if it's a discovered job
        jobs = self._app.get_jobs()
        for job in jobs:
            if job.name == command_name:
                return self._format_job_help(job)

        # Check builtins
        if command_name in _BUILTIN_DESCRIPTIONS:
            return (
                f"Usage: func {command_name}\n\n  {_BUILTIN_DESCRIPTIONS[command_name]}"
            )

        return ""

    def _format_top_level_help(self) -> str:
        """Format top-level help showing available commands."""
        lines = [
            "Usage: func [OPTIONS] COMMAND [ARGS]...",
            "",
            "  Functualize CLI — run jobs from anywhere.",
            "",
            "Commands:",
        ]

        jobs = self._app.get_jobs()
        for job in sorted(jobs, key=lambda j: j.name):
            desc = ""
            if job.docstring:
                desc = job.docstring.strip().split("\n")[0][:60]
            lines.append(f"  {job.name:<20} {desc}")

        lines.append("")
        lines.append("Built-in:")
        for name, desc in sorted(_BUILTIN_DESCRIPTIONS.items()):
            lines.append(f"  {name:<20} {desc}")

        return "\n".join(lines)

    def _get_effective_fields(self, job: object) -> list[FieldDescriptor]:
        """Get the effective field list for a job.

        Prefers config_fields (expanded Pydantic BaseModel fields) when available,
        falling back to parameters (raw function signature params).
        """
        from functualize.types import JobDescriptor

        assert isinstance(job, JobDescriptor)
        if job.config_fields:
            return job.config_fields
        return job.parameters

    def _format_job_help(self, job: object) -> str:
        """Format help text for a specific job."""
        from functualize.types import JobDescriptor

        assert isinstance(job, JobDescriptor)

        lines = [f"Usage: func {job.name} [OPTIONS]", ""]

        if job.docstring:
            for line in job.docstring.strip().splitlines():
                lines.append(f"  {line}")
            lines.append("")

        fields = self._get_effective_fields(job)
        if fields:
            lines.append("Options:")
            for param in fields:
                type_str = param.type_annotation or "str"
                default_str = ""
                if param.default is not None:
                    default_str = f"  [default: {param.default}]"
                required_str = "  [required]" if param.required else ""
                desc = param.description or ""
                lines.append(
                    f"  --{param.name:<16} {type_str:<10} {desc}{default_str}{required_str}"
                )

        return "\n".join(lines)

    def _parse_executability(self, help_text: str) -> tuple[bool, str]:
        """Parse help text to determine if command is executable."""
        if not help_text:
            return False, "Unknown command"

        if "Commands:" in help_text or "commands:" in help_text.lower():
            return False, "Needs sub-command"

        lower = help_text.lower()
        if "error:" in lower or "missing" in lower:
            return False, "Missing required arguments"

        if "Usage:" in help_text or "usage:" in help_text.lower():
            return True, "Ready to run"

        return False, "Unknown command"

    async def is_executable_async(self, tokens: list[str]) -> tuple[bool, str]:
        """Check if command is executable.

        A command is executable if it matches a known job name or builtin
        AND all required arguments are provided in the tokens.
        """
        if not tokens:
            return False, "Type a command"

        command_name = tokens[0]

        # Check builtins (always executable by name alone)
        if command_name in _BUILTIN_DESCRIPTIONS:
            return True, "Ready to run"

        # Check if it's a .py file path
        if command_name.endswith(".py"):
            from pathlib import Path

            if Path(command_name).is_file():
                return True, "Ready to run (single-file mode)"

        # Check jobs — must also verify required args are provided
        if command_name in self.job_names:
            jobs = self._app.get_jobs()
            for job in jobs:
                if job.name == command_name:
                    fields = self._get_effective_fields(job)
                    required_fields = [f for f in fields if f.required]
                    if not required_fields:
                        return True, "Ready to run"

                    # Parse provided --key value pairs from remaining tokens
                    provided = set()
                    i = 1
                    while i < len(tokens):
                        token = tokens[i]
                        if token.startswith("--"):
                            if "=" in token:
                                # --key=value — always counts as provided
                                key = token[2:].partition("=")[0].replace("-", "_")
                                provided.add(key)
                            else:
                                # --key value — only counts if followed by a value
                                key = token[2:].replace("-", "_")
                                if i + 1 < len(tokens) and not tokens[i + 1].startswith(
                                    "--"
                                ):
                                    provided.add(key)
                                    i += 1  # skip the value token
                                # else: bare --flag with no value, don't count as provided
                        i += 1

                    missing = [f for f in required_fields if f.name not in provided]
                    if missing:
                        names = ", ".join(f.name for f in missing[:3])
                        return False, f"Missing: {names}"
                    return True, "Ready to run"

            return True, "Ready to run"

        return False, "Unknown command"

    def _parse_subcommands(self, help_text: str) -> list[tuple[str, str, str]]:
        """Parse sub-commands from help text."""
        completions: list[tuple[str, str, str]] = []
        if not help_text:
            return completions

        in_commands = False
        for line in help_text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("commands:"):
                in_commands = True
                continue
            if in_commands:
                if not stripped or stripped.startswith("─"):
                    in_commands = False
                    continue
                parts = stripped.split(None, 1)
                if parts:
                    name = parts[0]
                    desc = parts[1] if len(parts) > 1 else ""
                    completions.append((name, desc, "subcommand"))
        return completions

    async def get_completions_async(
        self, tokens: list[str], all_commands: list[str]
    ) -> list[tuple[str, str, str]]:
        """Get completion suggestions from in-process job metadata.

        Returns list of (name, description, kind) tuples.
        """
        if not tokens:
            # Return all commands with descriptions
            result: list[tuple[str, str, str]] = []
            jobs = self._app.get_jobs()
            job_map = {j.name: j for j in jobs}
            for cmd in all_commands:
                if cmd in job_map:
                    job = job_map[cmd]
                    desc = ""
                    if job.docstring:
                        desc = job.docstring.strip().split("\n")[0][:60]
                    result.append((cmd, desc, "job"))
                elif cmd in _BUILTIN_DESCRIPTIONS:
                    result.append((cmd, _BUILTIN_DESCRIPTIONS[cmd], "builtin"))
                else:
                    result.append((cmd, "", "command"))
            return result

        # If we have tokens, generate completions
        partial = tokens[-1] if tokens else ""
        prefix = tokens[:-1] if tokens else []

        if not prefix:
            # Completing the first command word
            result = []
            jobs = self._app.get_jobs()
            job_map = {j.name: j for j in jobs}
            for cmd in all_commands:
                if cmd in job_map:
                    job = job_map[cmd]
                    desc = ""
                    if job.docstring:
                        desc = job.docstring.strip().split("\n")[0][:60]
                    result.append((cmd, desc, "job"))
                elif cmd in _BUILTIN_DESCRIPTIONS:
                    result.append((cmd, _BUILTIN_DESCRIPTIONS[cmd], "builtin"))
                else:
                    result.append((cmd, "", "command"))

            if partial:
                partial_lower = partial.lower()
                result = [
                    (n, d, k)
                    for n, d, k in result
                    if partial_lower in n.lower() or n.lower().startswith(partial_lower)
                ]
            return result

        # For deeper tokens, get options from job parameters
        command_name = prefix[0] if prefix else tokens[0]
        jobs = self._app.get_jobs()
        for job in jobs:
            if job.name == command_name:
                # Return parameter names as completions
                result = []
                fields = self._get_effective_fields(job)
                for param in fields:
                    result.append(
                        (f"--{param.name}", param.description or "", "option")
                    )
                if partial:
                    partial_lower = partial.lower()
                    result = [
                        (n, d, k)
                        for n, d, k in result
                        if partial_lower in n.lower()
                        or n.lower().startswith(partial_lower)
                    ]
                return result

        return []

    async def get_value_completions_async(
        self,
        job_name: str,
        field_name: str,
        partial: str = "",
    ) -> list[ValueCompletion]:
        """Get value completions for a specific field.

        Sources (in priority order):
        1. FieldDescriptor.choices (enum values)
        2. ArgumentHistory values (reverse chronological)
        3. File path completions (for Path-typed fields)

        Results are fuzzy-filtered by partial when non-empty.
        """
        # Find the job and field
        jobs = self._app.get_jobs()
        target_field: FieldDescriptor | None = None
        for job in jobs:
            if job.name == job_name:
                fields = self._get_effective_fields(job)
                for param in fields:
                    if param.name == field_name:
                        target_field = param
                        break
                break

        if target_field is None:
            return []

        completions: list[ValueCompletion] = []

        # Source 1: choices from FieldDescriptor (enum values)
        if target_field.choices:
            for choice in target_field.choices:
                completions.append(
                    ValueCompletion(
                        value=choice,
                        source="choices",
                        description="enum value",
                    )
                )

        # Source 2: history values from ArgumentHistory
        if self._history is not None:
            history_values = self._history.get_history(job_name, field_name)
            for val in history_values:
                completions.append(
                    ValueCompletion(
                        value=val,
                        source="history",
                        description="from history",
                    )
                )

        # Source 3: path completions for Path-typed fields
        type_ann = target_field.type_annotation.lower()
        name_lower = field_name.lower()
        if "path" in type_ann or "path" in name_lower or "file" in name_lower:
            try:
                cwd = Path.cwd()
                for entry in cwd.iterdir():
                    completions.append(
                        ValueCompletion(
                            value=str(entry.name),
                            source="path",
                            description="path completion",
                        )
                    )
            except OSError:
                pass

        # Fuzzy filter when partial is non-empty
        if partial:
            partial_lower = partial.lower()
            completions = [
                c
                for c in completions
                if partial_lower in c.value.lower()
                or c.value.lower().startswith(partial_lower)
            ]

        return completions


# Known builtin command descriptions — derived from the single registry
# in _cli/builtins.py so they cannot drift.
_BUILTIN_DESCRIPTIONS: dict[str, str] = builtin_descriptions()
