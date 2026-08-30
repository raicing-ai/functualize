"""Job-to-MCP tool translator.

Translates functualize JobDescriptors into MCP tool definitions suitable
for FastMCP registration. Uses job docstrings, config model schemas,
tags, and examples to produce rich tool metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize_mcp._config import MCPConfig

__all__ = ["JobToolTranslator", "MCPToolDef", "read_cached_group_options"]


def read_cached_group_options() -> dict[str, Any]:
    """The cached ``{group path: GroupOptionsSpec}`` map, or empty (S6a).

    Read from the same discovery cache the CLI dispatcher reads, so the tool
    schema and the command line describe one set of flags. Every translator
    construction site calls this rather than the constructor doing it, so a
    translator built in a test does no I/O and sees no ambient project.

    Failures are not fatal: a project with no declarations, or a cache not yet
    written, exposes no group options — the server must still start.
    """
    try:
        from pathlib import Path

        from functualize.app.utils import (
            read_group_options_from_cache,
            resolve_cache_path,
        )

        return dict(read_group_options_from_cache(resolve_cache_path(Path.cwd())) or {})
    except Exception:  # pragma: no cover - defensive
        return {}


# Mapping from functualize type_annotation strings to JSON Schema types.
_TYPE_MAP: dict[str, dict[str, Any]] = {
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "list": {"type": "array"},
    "dict": {"type": "object"},
    "list[str]": {"type": "array", "items": {"type": "string"}},
    "list[int]": {"type": "array", "items": {"type": "integer"}},
    "list[float]": {"type": "array", "items": {"type": "number"}},
    "list[bool]": {"type": "array", "items": {"type": "boolean"}},
}


@dataclass(frozen=True)
class MCPToolDef:
    """MCP tool definition produced by translation.

    Attributes:
        name: Tool name (derived from job name).
        description: Tool description (first paragraph of job docstring).
        input_schema: JSON Schema for the tool's input parameters.
        annotations: Additional metadata (tags, examples).
    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    group_option_names: frozenset[str] = frozenset()
    """Which ``input_schema`` properties came from a group, not the job.

    An agent sees one flat argument list, but the two halves are delivered
    differently — a group field is not a parameter of the job function and
    must reach the engine as a group layer. Recording the split here is what
    lets the tool wrapper route each argument correctly.
    """


class JobToolTranslator:
    """Translates JobDescriptors into MCP tool definitions.

    Uses the job's ``__doc__`` first paragraph as the tool description,
    generates inputSchema as JSON Schema from the config model, and
    includes @job declaration tags as tool annotations.

    Args:
        group_options: ``{group path: GroupOptionsSpec}`` (S6a), as read from
            the discovery cache. A job's schema gains the fields declared by
            every group on its path, because those are exactly the flags a CLI
            caller may type — an agent that could not set them would be
            strictly less capable than a shell, for no reason a tool
            description could explain.
    """

    def __init__(self, group_options: dict[str, Any] | None = None) -> None:
        self._group_options = group_options or {}

    def translate(self, descriptor: Any) -> MCPToolDef:
        """Translate a single JobDescriptor into an MCPToolDef.

        Args:
            descriptor: A JobDescriptor containing job metadata.

        Returns:
            An MCPToolDef representing the job as an MCP tool.
        """
        name = descriptor.name
        description = self._extract_description(descriptor)
        input_schema = self._build_input_schema(descriptor)
        group_names = self._merge_group_options(descriptor, input_schema)
        annotations = self._build_annotations(descriptor)
        return MCPToolDef(
            name=name,
            description=description,
            input_schema=input_schema,
            annotations=annotations,
            group_option_names=group_names,
        )

    def _specs_on_path(self, group: str | None) -> list[Any]:
        """The group-options specs bound to ``group`` or any ancestor.

        Outermost first, mirroring ``GroupTrie.group_options_on_path`` — the
        dispatcher's inheritance order, so a nested group's field overrides
        its parent's here the same way it does on the command line.
        """
        if not group:
            return []
        segments = group.split(".")
        specs: list[Any] = []
        for depth in range(1, len(segments) + 1):
            spec = self._group_options.get(".".join(segments[:depth]))
            if spec is not None:
                specs.append(spec)
        return specs

    def _merge_group_options(
        self, descriptor: Any, schema: dict[str, Any]
    ) -> frozenset[str]:
        """Fold a job's inherited group options into its input schema.

        The job's own fields win a name clash and are left untouched: over MCP
        there is one flat argument namespace, and the job's parameter is the
        nearer declaration — the same rule position encodes on the command
        line, where a flag after the job name binds to the job (D-d).
        """
        specs = self._specs_on_path(getattr(descriptor, "group", None))
        if not specs:
            return frozenset()

        properties: dict[str, Any] = schema.setdefault("properties", {})
        own_fields = set(properties)
        added: set[str] = set()

        for spec in specs:
            for f in spec.fields:
                if f.name in own_fields:
                    continue
                properties[f.name] = self._field_property(f)
                added.add(f.name)

        # Deliberately never added to `required`: a group option always has a
        # resolved value (default < file < env), so demanding one from the
        # caller would make every tool call carry it.
        return frozenset(added)

    def translate_all(
        self, descriptors: list[Any], config: MCPConfig
    ) -> list[MCPToolDef]:
        """Translate multiple JobDescriptors, applying visibility filters.

        Applies include_tags, exclude_tags, and exclude_jobs filtering
        from the MCPConfig before translation.

        Args:
            descriptors: List of JobDescriptors to translate.
            config: MCPConfig with filtering options.

        Returns:
            List of MCPToolDefs for visible jobs only.
        """
        visible = self._filter_descriptors(descriptors, config)
        return [self.translate(d) for d in visible]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_description(self, descriptor: Any) -> str:
        """Extract tool description from the job's docstring.

        Uses the first paragraph (up to the first blank line) of the
        docstring. If an extra_description is available in metadata, it
        takes precedence. Examples from metadata are appended.
        """
        metadata = self._get_metadata(descriptor)

        # extra_description takes precedence over docstring
        ai_desc = _get_attr_or_key(metadata, "extra_description")
        base_desc = ai_desc or self._first_paragraph(descriptor.docstring)

        # Append examples to the description
        examples = _get_attr_or_key(metadata, "examples")
        if examples:
            examples_text = "\n\nExamples:\n" + "\n".join(
                f"  - {ex}" for ex in examples
            )
            base_desc = base_desc + examples_text

        return base_desc

    def _first_paragraph(self, docstring: str | None) -> str:
        """Extract the first paragraph from a docstring.

        The first paragraph is everything up to the first blank line.
        Strips leading/trailing whitespace.
        """
        if not docstring:
            return ""

        lines: list[str] = []
        for line in docstring.strip().splitlines():
            stripped = line.strip()
            if not stripped and lines:
                # Hit a blank line after content — end of first paragraph
                break
            if stripped:
                lines.append(stripped)

        return " ".join(lines)

    def _build_input_schema(self, descriptor: Any) -> dict[str, Any]:
        """Build a JSON Schema object from the job's config fields.

        Uses config_fields if populated, otherwise falls back to parameters.
        """
        fields = [
            f
            for f in (descriptor.config_fields or descriptor.parameters)
            if not self._is_group_options_param(f)
        ]
        if not fields:
            return {"type": "object", "properties": {}, "required": []}

        properties: dict[str, Any] = {}
        required: list[str] = []

        for f in fields:
            properties[f.name] = self._field_property(f)
            if f.required:
                required.append(f.name)

        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return schema

    def _is_group_options_param(self, f: Any) -> bool:
        """Is this parameter the *injection point* for a group's options?

        `def run(image: str, opts: DeployOptions)` — `opts` is where the
        resolved instance lands, not something a caller supplies. Exposed as a
        tool argument it would appear as a bare string an agent might fill in,
        and the flags it stands for are already published individually. The
        CLI excludes it by testing the live annotation; here the descriptor is
        cached, so the equivalent signal is the declared class name matching a
        known declaration.
        """
        if not self._group_options:
            return False
        annotation = (getattr(f, "type_annotation", "") or "").strip()
        if not annotation:
            return False
        known = {
            getattr(spec, "class_name", None) for spec in self._group_options.values()
        }
        return annotation in known

    def _field_property(self, f: Any) -> dict[str, Any]:
        """One ``FieldDescriptor`` as a JSON Schema property.

        Shared by the job's own fields and its inherited group options: the
        two are the same record type, and a group flag that described itself
        differently from an identical job flag would be a wart an agent has no
        way to interpret.
        """
        prop: dict[str, Any] = {}

        # Map type annotation to JSON Schema type
        type_annotation = f.type_annotation
        if type_annotation in _TYPE_MAP:
            prop.update(_TYPE_MAP[type_annotation])
        else:
            # For unknown types, use string as fallback
            prop["type"] = "string"

        # Add description if available
        if f.description:
            prop["description"] = f.description

        # Add default if present and not required
        if not f.required and f.default is not None:
            prop["default"] = f.default

        # Add enum choices if available
        if f.choices:
            prop["enum"] = f.choices

        return prop

    def _build_annotations(self, descriptor: Any) -> dict[str, Any]:
        """Build tool annotations from the @job declaration tags and metadata."""
        metadata = self._get_metadata(descriptor)
        annotations: dict[str, Any] = {}

        tags = _get_attr_or_key(metadata, "tags")
        if tags:
            annotations["tags"] = list(tags)

        category = _get_attr_or_key(metadata, "category")
        if category:
            annotations["category"] = category

        visibility = _get_attr_or_key(metadata, "visibility")
        if visibility:
            annotations["visibility"] = visibility

        if descriptor.group:
            # Structured over opaque (contracts §9): export the group as its
            # trie namespace — the path segments as an array, plus the node
            # kind — rather than a dotted string an agent has to re-split.
            # `"job"` mirrors `JobCommandProvider`, which labels every job row
            # `NodeKind.JOB.value` when it builds the same trie; the plugin and
            # builtin kinds are not distinguished at this (job-descriptor) layer.
            annotations["group"] = {
                "namespace": descriptor.group.split("."),
                "kind": "job",
            }

        return annotations

    def _get_metadata(self, descriptor: Any) -> Any:
        """Get the @job declaration for tool metadata (extra_description, tags,
        examples, category, visibility). Empty dict when the job is
        convention-discovered (no declaration)."""
        declaration = getattr(descriptor, "declaration", None)
        if declaration is None:
            return {}
        return declaration

    def _filter_descriptors(
        self, descriptors: list[Any], config: MCPConfig
    ) -> list[Any]:
        """Filter descriptors based on MCPConfig visibility rules.

        Filtering rules:
        1. Exclude jobs with visibility="internal"
        2. Exclude jobs listed in config.exclude_jobs
        3. Exclude jobs tagged with any tag in config.exclude_tags
        4. If config.include_tags is non-empty, include only jobs tagged
           with at least one of the specified tags
        """
        result: list[Any] = []

        for descriptor in descriptors:
            metadata = self._get_metadata(descriptor)

            # 1. Exclude internal jobs
            visibility = _get_attr_or_key(metadata, "visibility")
            if visibility == "internal":
                continue

            # 2. Exclude jobs by name
            if descriptor.name in config.exclude_jobs:
                continue

            # Get job tags for tag-based filtering
            tags = _get_attr_or_key(metadata, "tags") or []

            # 3. Exclude jobs with excluded tags
            if config.exclude_tags and any(t in config.exclude_tags for t in tags):
                continue

            # 4. Include-tags filter (if specified, job must have at least one)
            if config.include_tags and not any(t in config.include_tags for t in tags):
                continue

            result.append(descriptor)

        return result


def _get_attr_or_key(obj: Any, name: str) -> Any:
    """Get a value from an object by attribute or dict key.

    Handles both SimpleNamespace/dataclass-style objects and dicts.
    Returns None if the attribute/key doesn't exist.
    """
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
