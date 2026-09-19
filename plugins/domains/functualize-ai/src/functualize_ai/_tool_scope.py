"""ToolScope builder — deny-by-default tool visibility for AI calls.

Provides a composable, provider-agnostic mechanism for restricting which
tools an AI call can access. ToolScope instances are immutable builders:
each method returns a new ToolScope or a modified copy.

Zero dependencies on any AI implementation plugin.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from functualize_ai._types import ToolDef


@dataclass(frozen=True)
class _ScopeFilter:
    """Internal representation of a single scope restriction."""

    kind: str  # "only", "tagged", "group", "functions"
    job_names: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    group_name: str = ""
    functions: list[Callable[..., Any]] = field(default_factory=list)


class ToolScope:
    """Deny-by-default tool visibility builder for AI calls.

    ToolScope restricts which tools are visible to an AI call by filtering
    jobs from a registry based on names, tags, groups, or by including
    plain Python callables directly.

    All factory methods return a new ToolScope instance. Instances can be
    combined with the ``+`` operator to produce a union of both scopes.
    """

    def __init__(
        self,
        *,
        _filters: list[_ScopeFilter] | None = None,
        _instructions: str | None = None,
        _approval_required: bool = False,
        _approval_gate: Callable[..., Any] | None = None,
    ) -> None:
        self._filters: list[_ScopeFilter] = _filters or []
        self._instructions: str | None = _instructions
        self._approval_required: bool = _approval_required
        self._approval_gate: Callable[..., Any] | None = _approval_gate

    # ------------------------------------------------------------------
    # Factory class methods
    # ------------------------------------------------------------------

    @classmethod
    def only(cls, job_names: list[str]) -> ToolScope:
        """Restrict AI tool visibility to only the listed job names.

        Args:
            job_names: List of job names to include.

        Returns:
            A new ToolScope restricted to the given job names.
        """
        return cls(_filters=[_ScopeFilter(kind="only", job_names=list(job_names))])

    @classmethod
    def tagged(cls, *tags: str) -> ToolScope:
        """Restrict AI tool visibility to jobs decorated with ALL specified tags.

        Args:
            *tags: Tags that jobs must have (ALL must match).

        Returns:
            A new ToolScope restricted to jobs with all given tags.
        """
        return cls(_filters=[_ScopeFilter(kind="tagged", tags=list(tags))])

    @classmethod
    def group(cls, group_name: str) -> ToolScope:
        """Restrict AI tool visibility to jobs in the specified group.

        Args:
            group_name: The group name to filter by.

        Returns:
            A new ToolScope restricted to jobs in the given group.
        """
        return cls(_filters=[_ScopeFilter(kind="group", group_name=group_name)])

    @classmethod
    def functions(cls, fns: list[Callable[..., Any]]) -> ToolScope:
        """Include plain Python callables as available tools.

        Args:
            fns: List of callables to expose as tools.

        Returns:
            A new ToolScope containing the given functions.
        """
        return cls(_filters=[_ScopeFilter(kind="functions", functions=list(fns))])

    # ------------------------------------------------------------------
    # Combinators
    # ------------------------------------------------------------------

    def __add__(self, other: ToolScope) -> ToolScope:
        """Produce a new ToolScope representing the union of both scopes.

        The resulting scope includes tools from both operands. Instructions
        from both scopes are concatenated (if both present). Approval is
        required if either scope requires it.

        Args:
            other: Another ToolScope to combine with.

        Returns:
            A new ToolScope that is the union of self and other.
        """
        if not isinstance(other, ToolScope):
            return NotImplemented

        # Merge instructions
        instructions: str | None = None
        if self._instructions and other._instructions:
            instructions = f"{self._instructions}\n{other._instructions}"
        elif self._instructions:
            instructions = self._instructions
        elif other._instructions:
            instructions = other._instructions

        # Merge approval: required if either requires it
        approval_required = self._approval_required or other._approval_required
        # Use the first non-None gate
        approval_gate = self._approval_gate or other._approval_gate

        return ToolScope(
            _filters=self._filters + other._filters,
            _instructions=instructions,
            _approval_required=approval_required,
            _approval_gate=approval_gate,
        )

    # ------------------------------------------------------------------
    # Modifiers
    # ------------------------------------------------------------------

    def with_instructions(self, text: str) -> ToolScope:
        """Attach usage instructions shown to the AI alongside the tools.

        Args:
            text: Instruction text for the AI.

        Returns:
            A new ToolScope with the instructions attached.
        """
        return ToolScope(
            _filters=self._filters,
            _instructions=text,
            _approval_required=self._approval_required,
            _approval_gate=self._approval_gate,
        )

    def approval_required(self, gate: Callable[..., Any] | None = None) -> ToolScope:
        """Mark that tool calls from this scope require approval.

        Args:
            gate: Optional callable that performs the approval check.

        Returns:
            A new ToolScope with approval required.
        """
        return ToolScope(
            _filters=self._filters,
            _instructions=self._instructions,
            _approval_required=True,
            _approval_gate=gate,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def instructions(self) -> str | None:
        """The usage instructions attached to this scope, or None."""
        return self._instructions

    @property
    def requires_approval(self) -> bool:
        """Whether tool calls from this scope require approval."""
        return self._approval_required

    @property
    def approval_gate(self) -> Callable[..., Any] | None:
        """The approval gate callable, if any."""
        return self._approval_gate

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def to_tool_defs(self, job_registry: Any) -> list[ToolDef]:
        """Resolve this scope against a job registry into provider-agnostic ToolDefs.

        The job_registry is duck-typed. It must provide:
        - ``get_descriptors() -> list``: returns all job descriptors
        - Each descriptor must have: ``name``, ``docstring``, ``group``,
          ``metadata`` (with optional ``tags`` attribute), and
          ``config_fields`` or ``parameters`` (list of field descriptors).

        Args:
            job_registry: A duck-typed registry providing job descriptors.

        Returns:
            A list of ToolDef instances representing the resolved tools.
        """
        tool_defs: list[ToolDef] = []
        seen_names: set[str] = set()

        for filt in self._filters:
            if filt.kind == "functions":
                for fn in filt.functions:
                    tool_def = _callable_to_tool_def(fn)
                    if tool_def.name not in seen_names:
                        tool_defs.append(tool_def)
                        seen_names.add(tool_def.name)
            else:
                descriptors = _get_descriptors(job_registry)
                matching = _filter_descriptors(descriptors, filt)
                for desc in matching:
                    if desc.name not in seen_names:
                        tool_defs.append(_descriptor_to_tool_def(desc))
                        seen_names.add(desc.name)

        return tool_defs


# ===========================================================================
# Internal helpers
# ===========================================================================


def _get_descriptors(job_registry: Any) -> list[Any]:
    """Get job descriptors from a duck-typed registry."""
    if hasattr(job_registry, "get_descriptors"):
        return job_registry.get_descriptors()
    # Fallback: if it's iterable, treat as list of descriptors
    if hasattr(job_registry, "__iter__"):
        return list(job_registry)
    return []


def _get_tags(descriptor: Any) -> list[str]:
    """Extract tags from a job descriptor's metadata."""
    metadata = getattr(descriptor, "metadata", None)
    if metadata is None:
        return []
    # metadata may be a dict or an object with a 'tags' attribute
    if isinstance(metadata, dict):
        tags = metadata.get("tags")
    else:
        tags = getattr(metadata, "tags", None)
    return tags if isinstance(tags, list) else []


def _filter_descriptors(descriptors: list[Any], filt: _ScopeFilter) -> list[Any]:
    """Filter descriptors based on a scope filter."""
    if filt.kind == "only":
        name_set = set(filt.job_names)
        return [d for d in descriptors if d.name in name_set]
    elif filt.kind == "tagged":
        required_tags = set(filt.tags)
        return [d for d in descriptors if required_tags.issubset(set(_get_tags(d)))]
    elif filt.kind == "group":
        return [d for d in descriptors if d.group == filt.group_name]
    return []


def _descriptor_to_tool_def(descriptor: Any) -> ToolDef:
    """Convert a job descriptor to a ToolDef."""
    name = descriptor.name
    docstring = getattr(descriptor, "docstring", None) or ""
    # Use config_fields if available, fall back to parameters
    config_fields = getattr(descriptor, "config_fields", None)
    if not config_fields:
        config_fields = getattr(descriptor, "parameters", None) or []

    # Build parameters schema from field descriptors
    parameters_schema = _fields_to_schema(config_fields)

    # Determine config_class if available
    config_class = getattr(descriptor, "config_class", None)

    return ToolDef(
        name=name,
        description=docstring,
        parameters_schema=parameters_schema,
        job_name=name,
        function=None,
        config_class=config_class,
    )


def _fields_to_schema(fields: list[Any]) -> dict[str, Any]:
    """Convert a list of field descriptors to a JSON Schema-like dict.

    Each field descriptor is expected to have: name, type_annotation (or type),
    description (or help), required, and optionally choices.
    """
    if not fields:
        return {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for f in fields:
        name = f.name
        type_ann = getattr(f, "type_annotation", None) or getattr(f, "type", "string")
        description = getattr(f, "description", None) or getattr(f, "help", "")
        is_required = getattr(f, "required", False)
        choices = getattr(f, "choices", None)

        prop: dict[str, Any] = {
            "type": _python_type_to_json_type(type_ann),
            "description": description,
        }
        if choices:
            prop["enum"] = choices

        properties[name] = prop
        if is_required:
            required.append(name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _python_type_to_json_type(type_str: str) -> str:
    """Map a Python type annotation string to a JSON Schema type."""
    type_lower = type_str.lower().strip()
    if type_lower in ("str", "string"):
        return "string"
    elif type_lower in ("int", "integer"):
        return "integer"
    elif type_lower in ("float", "number"):
        return "number"
    elif type_lower in ("bool", "boolean"):
        return "boolean"
    elif type_lower.startswith("list") or type_lower.startswith("sequence"):
        return "array"
    elif type_lower.startswith("dict") or type_lower.startswith("mapping"):
        return "object"
    return "string"


def _callable_to_tool_def(fn: Callable[..., Any]) -> ToolDef:
    """Convert a plain Python callable to a ToolDef.

    Introspects the function's signature and docstring to produce
    a provider-agnostic tool definition.
    """
    name = getattr(fn, "__name__", str(fn))
    description = inspect.getdoc(fn) or ""
    parameters_schema = _signature_to_schema(fn)

    return ToolDef(
        name=name,
        description=description,
        parameters_schema=parameters_schema,
        job_name=None,
        function=fn,
        config_class=None,
    )


def _signature_to_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Build a JSON Schema-like dict from a callable's signature."""
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        # Skip 'self', 'cls', and *args/**kwargs
        if param_name in ("self", "cls"):
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        annotation = param.annotation
        json_type = "string"  # default
        if annotation is not inspect.Parameter.empty:
            json_type = _annotation_to_json_type(annotation)

        prop: dict[str, Any] = {"type": json_type}
        properties[param_name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    if not properties:
        return {}

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _annotation_to_json_type(annotation: Any) -> str:
    """Convert a Python type annotation to a JSON Schema type string."""
    if annotation is str:
        return "string"
    elif annotation is int:
        return "integer"
    elif annotation is float:
        return "number"
    elif annotation is bool:
        return "boolean"
    elif annotation is list:
        return "array"
    elif annotation is dict:
        return "object"

    # Handle typing generics
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        return "array"
    elif origin is dict:
        return "object"

    # Fallback: try string representation
    ann_str = str(annotation)
    if "list" in ann_str.lower():
        return "array"
    elif "dict" in ann_str.lower():
        return "object"
    elif "int" in ann_str.lower():
        return "integer"
    elif "float" in ann_str.lower():
        return "number"
    elif "bool" in ann_str.lower():
        return "boolean"

    return "string"
