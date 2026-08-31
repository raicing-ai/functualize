"""JSON Schema for a job's inputs — one renderer, every surface.

A job's published inputs are asked for by more than one consumer: the MCP
tool's ``inputSchema``, ``func builtin info schema``, and anything else that
needs to tell a caller what a job accepts. Each of those rendering the schema
itself is how the surfaces drift — the MCP plugin owned this code alone, and
it published ``Stdout`` and ``Shell`` as required string arguments while the
CLI filtered them correctly (see ``_primitives/capability_names.py``).

So the rendering lives here, in a layer both the CLI and a plugin can reach
through ``functualize.app.utils``, and there is exactly one definition of what
a job's inputs look like as JSON Schema.

Pure and dependency-free: descriptors in, plain dicts out. No app, no engine,
no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from functualize._types.descriptors import FieldDescriptor

__all__ = [
    "TYPE_MAP",
    "field_property",
    "input_schema",
    "job_input_schema",
]

#: Type annotation (as written) → JSON Schema fragment.
#:
#: **Two vocabularies, one map.** A ``FieldDescriptor`` reaches this renderer
#: from either of two places, and they spell types differently:
#:
#: - a **job signature**, where the annotation is Python source text (``int``,
#:   ``list[str]``) — text rather than a resolved type because the descriptor
#:   may have been rebuilt from the discovery cache, where the type object is
#:   long gone;
#: - a **click command**, where ``ClickCommandNode.params()`` records click's
#:   own ``ParamType.name`` (``integer``, ``boolean``, ``choice``).
#:
#: Keeping one map rather than one per source is the same rule the protocol
#: states for the descriptor itself: there is one description of a command's
#: parameters and every surface reads it. Before this, ``builtin`` flags all
#: degraded to ``string`` — ``--prune`` advertised as text.
#:
#: Anything unrecognized still degrades to ``string``, which stays the honest
#: answer: the CLI would accept the flag as text too.
TYPE_MAP: dict[str, dict[str, Any]] = {
    # Python annotations, from a job signature.
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
    # click ParamType.name, from a builtin or plugin command.
    "text": {"type": "string"},
    "integer": {"type": "integer"},
    "boolean": {"type": "boolean"},
    "uuid": {"type": "string", "format": "uuid"},
    "datetime": {"type": "string", "format": "date-time"},
    "integer range": {"type": "integer"},
    "float range": {"type": "number"},
    # A choice is a string with an ``enum``; ``field_property`` adds the enum
    # from ``choices``, so the base type is all that is needed here.
    "choice": {"type": "string"},
    # Paths and filenames are strings on the wire. Left unannotated with a
    # JSON Schema ``format``: there is no registered format for a filesystem
    # path, and inventing one would mislead a validator.
    "path": {"type": "string"},
    "file": {"type": "string"},
    "directory": {"type": "string"},
    "filename": {"type": "string"},
}


def _is_json_native(value: Any) -> bool:
    """Can this value appear in JSON Schema as written?

    ``None`` is excluded on purpose: it is how both sources spell "no default",
    and publishing ``"default": null`` would claim the field defaults to null.
    """
    if value is None:
        return False
    if isinstance(value, bool | int | float | str):
        return True
    if isinstance(value, list | tuple):
        return all(_is_json_native(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_native(item)
            for key, item in value.items()
        )
    return False


def field_property(field: FieldDescriptor) -> dict[str, Any]:
    """One ``FieldDescriptor`` as a JSON Schema property.

    Shared by a job's own fields and its inherited group options: they are the
    same record type, and a group flag describing itself differently from an
    identical job flag would be a wart a caller has no way to interpret.
    """
    prop: dict[str, Any] = {}

    annotation = getattr(field, "type_annotation", None)
    prop.update(TYPE_MAP.get(annotation or "", {"type": "string"}))

    if field.description:
        prop["description"] = field.description

    # A default is only meaningful on an optional field; on a required one it
    # would advertise a value the caller must still supply.
    #
    # And only when it is representable. Click marks "no default" with its own
    # ``Sentinel.UNSET`` rather than ``None``, which is not None, not JSON, and
    # serialized straight through as the literal string ``"Sentinel.UNSET"`` —
    # a value no caller could ever pass. A default that cannot be represented
    # is better omitted than published wrong.
    if not field.required and _is_json_native(field.default):
        prop["default"] = field.default

    if field.choices:
        prop["enum"] = list(field.choices)

    return prop


def input_schema(fields: Sequence[FieldDescriptor]) -> dict[str, Any]:
    """A JSON Schema ``object`` over ``fields``.

    ``required`` is omitted rather than emitted empty: an empty required list
    is noise, and some consumers treat its presence as meaningful.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []

    for field in fields:
        properties[field.name] = field_property(field)
        if field.required:
            required.append(field.name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def job_input_schema(
    descriptor: Any,
    *,
    group_options_class_names: Iterable[str] = (),
) -> dict[str, Any]:
    """The published input schema for one job descriptor.

    Args:
        descriptor: A ``JobDescriptor``. ``config_fields`` wins over
            ``parameters`` when populated — a job taking a config model
            publishes that model's fields, not the single model parameter.
        group_options_class_names: Class names of known ``GroupOptions``
            declarations. A parameter annotated with one is the *injection
            point* for a group's resolved options, not something a caller
            supplies; the individual flags it stands for are published
            separately, so exposing it too would offer a bare string a caller
            might try to fill in.

    Capabilities are already absent: the descriptor's parameters exclude them
    at extraction (``_primitives/capability_names.py``), which is the single
    place that decision is made.
    """
    known = frozenset(group_options_class_names)

    def is_group_options(field: FieldDescriptor) -> bool:
        if not known:
            return False
        annotation = (getattr(field, "type_annotation", "") or "").strip()
        return bool(annotation) and annotation in known

    fields = [
        f
        for f in (descriptor.config_fields or descriptor.parameters)
        if not is_group_options(f)
    ]
    if not fields:
        return {"type": "object", "properties": {}, "required": []}

    return input_schema(fields)
