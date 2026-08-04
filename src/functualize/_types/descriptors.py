"""Frozen dataclass definitions for the functualize shared vocabulary.

Contains JobDescriptor, FieldDescriptor, JobResult, and CacheInfo — the
core data transfer objects used across all internal layers. Zero imports
from any _-prefixed internal package. Only stdlib imports.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._types.enums import ConfigFileRole

if TYPE_CHECKING:
    from functualize._types.enums import RunStatus
    from functualize._types.job_declaration import JobDeclaration
    from functualize._types.workflow import WorkflowShape

# Sentinel value used in serialized form to distinguish "required field
# (no default)" from "optional field with default=None".
_REQUIRED_SENTINEL = "__REQUIRED__"


@dataclass(frozen=True)
class FieldDescriptor:
    """Structured parameter schema for a job's configuration field.

    Attributes:
        name: Field name.
        type_annotation: Type string (e.g., "str", "int", "bool", "list[str]").
        default: Default value, or None if required.
        description: Field description text.
        required: True if the field has no default value.
        choices: Enum member values (non-empty list if type is enum, None otherwise).
        positional: True if marked with Arg() — a positional CLI argument.
        short_flag: Short flag alias (e.g., "-t") from Option() marker, or None.
        is_stdin: True if marked with Stdin() — reads from a pipe when available.
        stdin_flag: Explicit flag name from Stdin(flag=...), or None to derive
            from the field name.
    """

    name: str
    type_annotation: str
    default: Any | None
    description: str
    required: bool
    choices: list[str] | None = None
    positional: bool = False
    short_flag: str | None = None
    is_stdin: bool = False
    stdin_flag: str | None = None

    @property
    def type(self) -> str:
        """Backward-compatible alias for type_annotation."""
        return self.type_annotation

    @property
    def help(self) -> str:
        """Backward-compatible alias for description."""
        return self.description


@dataclass(frozen=True)
class GroupOptionsSpec:
    """A group's declared CLI flags, as pure cached data (S6a).

    Extracted from a ``GroupOptions`` subclass at scan time and persisted in
    the cache's ``group_options`` section. This — not the class — is what the
    non-booting surfaces read (dispatch's mid-path parse, completion, the
    TUI), so a warm boot resolves which flags a group accepts without
    importing the declaring module. The Pydantic class is imported only when
    a value must be validated/constructed, mirroring the lazy-class /
    cached-shape split used by ``workflow_shape_of``.

    ``fields`` reuses :class:`FieldDescriptor` deliberately: it is the same
    type the CLI param builder already consumes, so a group node and a job
    build their click params through one code path.

    Attributes:
        group: Dotted group path this declaration binds to (``"deploy"``).
        class_name: Name of the ``GroupOptions`` subclass, for lazy import.
        fields: The declared option fields.
        source_file: Absolute path of the declaring module (invalidation).
        source_mtime: os.path.getmtime() at scan time.
        content_hash: sha256 hex digest of the source at scan time.
        module_path: Dotted module path for lazy import, when known.
    """

    group: str
    class_name: str
    fields: list[FieldDescriptor] = field(default_factory=list)
    source_file: str = ""
    source_mtime: float = 0.0
    content_hash: str = ""
    module_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "group": self.group,
            "class_name": self.class_name,
            "fields": [_field_to_dict(f) for f in self.fields],
            "source_file": self.source_file,
            "source_mtime": self.source_mtime,
            "content_hash": self.content_hash,
            "module_path": self.module_path,
        }

    @classmethod
    def from_dict(cls, data: Any) -> GroupOptionsSpec:
        """Deserialize from a JSON dict.

        Raises:
            ValueError: If required keys are missing or values have wrong types.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"Expected a dict for GroupOptionsSpec, got {type(data).__name__}"
            )
        required_keys = {"group", "class_name", "fields"}
        missing = required_keys - set(data.keys())
        if missing:
            raise ValueError(
                f"Missing required keys in GroupOptionsSpec dict: {sorted(missing)}"
            )
        if not isinstance(data["group"], str):
            raise ValueError(
                f"Expected 'group' to be str, got {type(data['group']).__name__}"
            )
        if not isinstance(data["class_name"], str):
            raise ValueError(
                f"Expected 'class_name' to be str, got {type(data['class_name']).__name__}"
            )
        if not isinstance(data["fields"], list):
            raise ValueError(
                f"Expected 'fields' to be a list, got {type(data['fields']).__name__}"
            )
        fields = []
        for i, field_data in enumerate(data["fields"]):
            try:
                fields.append(_field_from_dict(field_data))
            except ValueError as e:
                raise ValueError(f"Invalid fields[{i}]: {e}") from e
        return cls(
            group=data["group"],
            class_name=data["class_name"],
            fields=fields,
            source_file=data.get("source_file", ""),
            source_mtime=float(data.get("source_mtime", 0.0)),
            content_hash=data.get("content_hash", ""),
            module_path=data.get("module_path", ""),
        )


@dataclass(frozen=True)
class JobDescriptor:
    """Serializable metadata for a discovered job.

    Attributes:
        name: Job function name.
        group: Job group name (None for top-level jobs).
        function: The callable job function (None for cache-only descriptors).
        docstring: Function docstring (None if absent).
        parameters: Config parameters for the job as FieldDescriptors.
        source: Module path or file path where the job was discovered.
        metadata: Additional metadata about the job.
        module_path: Dotted module path for lazy import (defaults to source).
        source_file: Filesystem path to source file (for cache invalidation).
        source_mtime: Last modification time of source file.
        content_hash: Content hash for cache invalidation.
        config_fields: Alias for parameters (backward-compatible).
        dependencies: First-level in-project imports {abs_path: sha256}.
        requires_tty: True if the signature declares a non-optional ``tty: TTY``
            capability — a HARD requirement forcing EXCLUSIVE surface resolution;
            refused pre-flight in non-terminal contexts (MCP/CI/piped).
        optional_tty: True if the signature declares ``tty: TTY | None`` — a
            preference: injected when EXCLUSIVE is grantable, else None, and the
            job degrades. Does not force EXCLUSIVE or trigger refusal.
        uses_live: True if the signature declares a ``live: Live`` capability — a
            live-display channel bound per surface (always injected, degrading).
    """

    name: str
    group: str | None
    function: Callable[..., Any] | None = None
    docstring: str | None = None
    parameters: list[FieldDescriptor] = field(default_factory=list)
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    module_path: str = ""
    source_file: str = ""
    source_mtime: float = 0.0
    content_hash: str = ""
    config_fields: list[FieldDescriptor] = field(default_factory=list)
    dependencies: dict[str, str] = field(default_factory=dict)
    requires_tty: bool = False
    optional_tty: bool = False
    uses_live: bool = False
    #: Names of ambient live constructs this job opts out of, from
    #: ``@job(suppress_live=[...])``. The declarative form of
    #: ``live.suppress(name)``.
    suppress_live: tuple[str, ...] = ()
    #: Decorator root names applied to the function, read from the source AST
    #: at extraction time (``@job`` → "job", ``@a.b(...)`` → "a"). Decorators
    #: are not reliably introspectable after import, so job-level filtering on
    #: ``require_job_decorators`` reads this instead of the live object.
    decorators: tuple[str, ...] = ()
    #: Per-job render-surface preference from ``@surface_hint(...)``
    #: ("stdout" | "panel"), consulted by the surface-resolution ladder.
    #: None means no preference (setting / framework default apply).
    surface_hint: str | None = None
    #: The frozen ``JobDeclaration`` from ``@job(...)`` (proposal §A.3), or None
    #: for convention-discovered jobs. Carries deps/cache/guards/exec/matrix and
    #: identity overrides. Read off ``func.__functualize_job__`` at extraction
    #: time and cached, so warm/lazy boot has it without importing the module.
    declaration: JobDeclaration | None = None
    #: The cache-serializable topology from ``@workflow(...)`` (§A.7), or None
    #: for ordinary jobs. Node names, kinds, and edges only — gate schemas and
    #: branch conditions materialize on demand, so listing and describing a
    #: workflow stays import-free on the warm path.
    workflow: WorkflowShape | None = None

    #: Names of jobs this one consumes via ``FromJob`` parameters (§D.5).
    #: Recorded at discovery because the edge lives in the *signature*, and on
    #: a warm boot the function is a deferred-import stand-in — so an engine
    #: that re-derived these would find none and silently drop the dependency.
    #: `Deps` needs no equivalent: it survives in the cached declaration.
    from_job_deps: tuple[str, ...] = ()

    #: The module attribute the function is actually bound to — its Python
    #: ``__name__``. Distinct from :attr:`func_name`, which is the canonical
    #: leaf of the *address* (``build-wheel``). Deriving one from the other
    #: works for ``build_wheel`` and silently fails for ``buildWheel``, and a
    #: warm boot has no function to ask, so the fact is recorded here.
    #: Empty means "same as func_name" (dynamic and synthetic descriptors).
    python_name: str = ""

    @property
    def func_name(self) -> str:
        """The leaf of the registered name — after the last dot, or all of it.

        This is the *canonical* leaf (``build-wheel``), not the Python
        ``__name__`` (``build_wheel``), because it is derived from ``name``.
        Callers wanting the module attribute want :attr:`python_name`.
        """
        return self.name.rsplit(".", 1)[-1]

    @property
    def attribute_name(self) -> str:
        """The module attribute to resolve this job's function from."""
        return self.python_name or self.func_name

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict for cache persistence.

        Uses config_fields if populated, otherwise falls back to parameters.
        Enum defaults are converted via .value attribute. Non-JSON-serializable
        defaults are converted to None.
        """
        fields = self.config_fields if self.config_fields else self.parameters
        # metadata now holds only plugin extension data (a JSON dict) — the
        # @job_metadata annotation is gone; consumer-facing description/tags/
        # category live on `declaration`.
        metadata_dict: Any = dict(self.metadata) if self.metadata else None

        return {
            "name": self.name,
            "group": self.group,
            "module_path": self.module_path,
            "source_file": self.source_file,
            "source_mtime": self.source_mtime,
            "content_hash": self.content_hash,
            "docstring": self.docstring,
            "config_fields": [_field_to_dict(f) for f in fields],
            "dependencies": dict(self.dependencies),
            "metadata": metadata_dict,
            "requires_tty": self.requires_tty,
            "optional_tty": self.optional_tty,
            "uses_live": self.uses_live,
            "suppress_live": list(self.suppress_live),
            "surface_hint": self.surface_hint,
            "decorators": list(self.decorators),
            "declaration": (
                self.declaration.to_dict() if self.declaration is not None else None
            ),
            "from_job_deps": list(self.from_job_deps),
            "python_name": self.python_name,
            "workflow": (
                self.workflow.to_dict() if self.workflow is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobDescriptor:
        """Deserialize from a JSON dict.

        Raises:
            ValueError: If required keys are missing or values have wrong types.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"Expected a dict for JobDescriptor, got {type(data).__name__}"
            )

        # Validate required top-level keys
        required_keys = {
            "name",
            "group",
            "module_path",
            "source_file",
            "source_mtime",
            "content_hash",
            "docstring",
            "config_fields",
            "dependencies",
        }
        missing = required_keys - set(data.keys())
        if missing:
            raise ValueError(
                f"Missing required keys in JobDescriptor dict: {sorted(missing)}"
            )

        # Validate types for scalar fields
        if not isinstance(data["name"], str):
            raise ValueError(
                f"Expected 'name' to be str, got {type(data['name']).__name__}"
            )
        if data["group"] is not None and not isinstance(data["group"], str):
            raise ValueError(
                f"Expected 'group' to be str or None, got {type(data['group']).__name__}"
            )
        if not isinstance(data["module_path"], str):
            raise ValueError(
                f"Expected 'module_path' to be str, got {type(data['module_path']).__name__}"
            )
        if not isinstance(data["source_file"], str):
            raise ValueError(
                f"Expected 'source_file' to be str, got {type(data['source_file']).__name__}"
            )
        if not isinstance(data["source_mtime"], int | float):
            raise ValueError(
                f"Expected 'source_mtime' to be a number, got {type(data['source_mtime']).__name__}"
            )
        if not isinstance(data["content_hash"], str):
            raise ValueError(
                f"Expected 'content_hash' to be str, got {type(data['content_hash']).__name__}"
            )
        if data["docstring"] is not None and not isinstance(data["docstring"], str):
            raise ValueError(
                f"Expected 'docstring' to be str or None, got {type(data['docstring']).__name__}"
            )
        if not isinstance(data["config_fields"], list):
            raise ValueError(
                f"Expected 'config_fields' to be a list, got {type(data['config_fields']).__name__}"
            )
        if not isinstance(data["dependencies"], dict):
            raise ValueError(
                f"Expected 'dependencies' to be a dict, got {type(data['dependencies']).__name__}"
            )

        # Deserialize config_fields
        config_fields = []
        for i, field_data in enumerate(data["config_fields"]):
            try:
                config_fields.append(_field_from_dict(field_data))
            except ValueError as e:
                raise ValueError(f"Invalid config_fields[{i}]: {e}") from e

        # Validate dependencies dict values
        for key, value in data["dependencies"].items():
            if not isinstance(key, str):
                raise ValueError(
                    f"Expected dependency key to be str, got {type(key).__name__}"
                )
            if not isinstance(value, str):
                raise ValueError(
                    f"Expected dependency value for '{key}' to be str, "
                    f"got {type(value).__name__}"
                )

        # Deserialize metadata (plugin extension dict; empty for most jobs).
        raw_metadata = data.get("metadata")
        metadata_value: Any = (
            dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        )

        # Deserialize the @job declaration (v9). Absent/None in pre-v9 entries
        # and for convention jobs, which carry no declaration.
        declaration = None
        raw_declaration = data.get("declaration")
        if isinstance(raw_declaration, dict):
            from functualize._types.job_declaration import JobDeclaration

            declaration = JobDeclaration.from_dict(raw_declaration)

        # Deserialize the @workflow graph shape (v10). Absent for ordinary jobs
        # and pre-v10 entries; a malformed entry yields None (cache rebuild).
        workflow = None
        raw_workflow = data.get("workflow")
        if isinstance(raw_workflow, dict):
            from functualize._types.workflow import WorkflowShape

            workflow = WorkflowShape.from_dict(raw_workflow)

        return cls(
            name=data["name"],
            group=data["group"],
            module_path=data["module_path"],
            source_file=data["source_file"],
            source_mtime=float(data["source_mtime"]),
            content_hash=data["content_hash"],
            docstring=data["docstring"],
            config_fields=config_fields,
            dependencies=data["dependencies"],
            metadata=metadata_value,
            # Capability markers (v5) — default False for pre-v5 cache entries.
            requires_tty=bool(data.get("requires_tty", False)),
            optional_tty=bool(data.get("optional_tty", False)),
            uses_live=bool(data.get("uses_live", False)),
            # v6 — absent in pre-v6 cache entries, which suppress nothing.
            suppress_live=tuple(data.get("suppress_live", ()) or ()),
            # v7 — absent in pre-v7 cache entries, which state no preference.
            surface_hint=(
                data["surface_hint"]
                if isinstance(data.get("surface_hint"), str)
                else None
            ),
            # v8 — absent in pre-v8 cache entries, which recorded no decorators.
            decorators=tuple(data.get("decorators", ()) or ()),
            # v9 — absent in pre-v9 cache entries and convention jobs (None).
            declaration=declaration,
            # v10 — absent in pre-v10 entries and for every non-workflow job.
            from_job_deps=tuple(data.get("from_job_deps") or ()),
            python_name=data.get("python_name") or "",
            workflow=workflow,
        )


@dataclass(frozen=True)
class JobResult:
    """Result of a job execution.

    Attributes:
        status: The final run status of the job.
        return_value: The value returned by the job function.
        duration_ms: Execution duration in milliseconds.
        metadata: Additional metadata about the execution.
        exception: The exception that caused failure, or None on success.
    """

    status: RunStatus
    return_value: Any
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)
    exception: BaseException | None = field(default=None, compare=False, hash=False)
    job_name: str = ""


@dataclass(frozen=True)
class CacheInfo:
    """Statistics about the job discovery cache.

    Attributes:
        entry_count: Number of entries currently in the cache.
        stale_count: Number of entries that are stale (source changed).
        file_size_bytes: Size of the cache file in bytes.
        cache_path: Path to the cache file, or None if no cache exists.
    """

    entry_count: int
    stale_count: int
    file_size_bytes: int
    cache_path: Path | None


@dataclass(frozen=True)
class ConfigFileInfo:
    """A discovered config file and the part it plays in resolution.

    Answers, for one file: where is it, which environment slot does it name,
    is it actually contributing under the active environment, and what did
    it contribute. Delivery layers need all of that together — knowing a
    file merely *exists* is not enough to explain why its values aren't
    winning.

    Attributes:
        path: Absolute path to the file.
        environment_slot: The ``<slot>`` in ``config.<slot>.<ext>``, or None
            for an unslotted ``config.<ext>``.
        role: Whether this file is merged always (BASE), merged on top for
            the active environment (OVERLAY), or belongs to a different
            environment and is never merged (INERT).
        precedence: Merge rank among *contributing* files — lower wins.
            None for INERT files, which never merge and so have no rank.
        values: The file's own parsed contents (not the merged view). Empty
            when the file could not be parsed.
        parsed: False when no FormatProvider matched the extension, or the
            file could not be read — the file is reported, not silently
            dropped, so a typo'd extension is diagnosable.
    """

    path: str
    environment_slot: str | None
    role: ConfigFileRole
    precedence: int | None
    values: dict[str, Any] = field(default_factory=dict)
    parsed: bool = True

    @property
    def is_active(self) -> bool:
        """True if this file contributes to the resolved configuration."""
        return self.role is not ConfigFileRole.INERT and self.parsed


@dataclass(frozen=True)
class PluginCommand:
    """A command registered by a capability plugin.

    Represents a CLI (or adapter) command contributed by a plugin during
    the boot phase. The active adapter retrieves these via
    ``app.get_plugin_commands()`` to include them in its command tree.

    Attributes:
        name: Command name (1-64 chars, lowercase alphanumeric + hyphens).
        callback: The callable to invoke when the command is executed.
        help_text: Help text for the command (max 256 chars).
        namespace: Optional flat CLI namespace the command is mounted under
            (e.g. ``"mcp"`` for ``func mcp serve``). None for top-level. This
            is deliberately NOT ``group`` — ``JobDescriptor.group`` is a dotted
            job hierarchy, a different concept.
    """

    name: str
    callback: Callable[..., Any]
    help_text: str
    namespace: str | None = None


@dataclass(frozen=True)
class RegisteredJob:
    """Metadata for a registered job, retained for programmatic invocation.

    Attributes:
        name: The registered job name (used for invoke() lookups).
        function: The callable job function.
        config_class: Optional Pydantic BaseModel subclass for config validation.
        group: Job group name (None for top-level jobs).
        module_path: Module path or file path where the job was defined.
        job_directory: Directory containing the job source file (None if unknown).
        dependencies: Names of the jobs this one depends on — declared `Deps`
            plus signature-derived `FromJob` parameters, already resolved.

            Resolved at registration and carried here rather than read from the
            function at execution time, because on a warm boot ``function`` is a
            deferred-import stand-in with no declaration on it. Reading deps
            from the function meant a cold run executed the whole chain and a
            warm run silently executed only the target.
    """

    name: str
    function: Callable[..., Any]
    config_class: type | None
    group: str | None
    module_path: str
    job_directory: Path | None = None
    dependencies: tuple[str, ...] = ()


# =============================================================================
# Serialization helpers for JobDescriptor.to_dict / from_dict
# =============================================================================


def _field_to_dict(fd: FieldDescriptor) -> dict[str, Any]:
    """Serialize a FieldDescriptor to a JSON-compatible dict."""
    default = _serialize_default(fd.default, fd.required)
    return {
        "name": fd.name,
        "type_annotation": fd.type_annotation,
        "choices": fd.choices,
        "default": default,
        "required": fd.required,
        "description": fd.description,
        "positional": fd.positional,
        "short_flag": fd.short_flag,
        "is_stdin": fd.is_stdin,
        "stdin_flag": fd.stdin_flag,
    }


def _serialize_default(default: Any, required: bool) -> Any:
    """Convert a default value to a JSON-serializable form."""
    if required and default is None:
        return _REQUIRED_SENTINEL
    if default == _REQUIRED_SENTINEL:
        return _REQUIRED_SENTINEL
    if isinstance(default, Enum):
        return default.value
    if default is None:
        return None
    try:
        json.dumps(default)
        return default
    except (TypeError, ValueError, OverflowError):
        return None


def _field_from_dict(data: Any) -> FieldDescriptor:
    """Deserialize a FieldDescriptor from a JSON dict.

    Supports both the new key names (type_annotation, description) and
    legacy key names (type, help) for backward compatibility with existing
    cache files.

    Raises:
        ValueError: If required keys are missing or values have wrong types.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a dict for FieldDescriptor, got {type(data).__name__}"
        )

    # Support both new and legacy key names
    type_key = "type_annotation" if "type_annotation" in data else "type"
    desc_key = "description" if "description" in data else "help"

    required_keys = {"name", type_key, "choices", "default", "required", desc_key}
    missing = required_keys - set(data.keys())
    if missing:
        raise ValueError(
            f"Missing required keys in FieldDescriptor dict: {sorted(missing)}"
        )

    if not isinstance(data["name"], str):
        raise ValueError(
            f"Expected 'name' to be str, got {type(data['name']).__name__}"
        )
    if not isinstance(data[type_key], str):
        raise ValueError(
            f"Expected '{type_key}' to be str, got {type(data[type_key]).__name__}"
        )
    if data["choices"] is not None and not isinstance(data["choices"], list):
        raise ValueError(
            f"Expected 'choices' to be list or None, got {type(data['choices']).__name__}"
        )
    if not isinstance(data["required"], bool):
        raise ValueError(
            f"Expected 'required' to be bool, got {type(data['required']).__name__}"
        )
    if not isinstance(data[desc_key], str):
        raise ValueError(
            f"Expected '{desc_key}' to be str, got {type(data[desc_key]).__name__}"
        )

    # Reconstruct default: reverse the sentinel encoding
    raw_default = data["default"]
    default = None if raw_default == _REQUIRED_SENTINEL else raw_default

    return FieldDescriptor(
        name=data["name"],
        type_annotation=data[type_key],
        choices=data["choices"],
        default=default,
        required=data["required"],
        description=data[desc_key],
        positional=data.get("positional", False),
        short_flag=data.get("short_flag"),
        is_stdin=data.get("is_stdin", False),
        stdin_flag=data.get("stdin_flag"),
    )
