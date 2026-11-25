"""Build the JSON Schema for a job's parameters (schema boundary).

The properties are the parameter contracts' own ``json_schema`` (D4: one
shape-to-JSON-Schema function), so the published type of a parameter is the
contract's verdict — never a second mapping from annotation spellings. The
``required`` list is the contracts' requiredness. Together these are what
makes the four renderings one description: the CLI's parameters come from the
same contracts (T2), and both this function and the MCP schema builder read
them (T6 / contracts.md §8).

An ad-hoc contractless field can still publish a string property. Discovered
job and group fields carry contracts, which own their type and verdict.

Enumerations are *not* a vocabulary entry, because they are not part of the
type mapping: an enum contract's ``json_schema`` carries its ``enum`` values
from the shape (``Literal``), and the fallback adds ``enum`` per field from the
field's choices.

Group options are merged inside ``job_input_schema`` (6.1): the job's own
fields win a name clash, a nested group's declaration overrides its parent's,
and the merged options are never ``required`` — "a group option always has a
resolved value (default < file < env)", so demanding one from the caller would
make every call carry it. That is the MCP translator's `_merge_group_options`
fold, moved into core so ``info`` and MCP describe a job identically by
construction; the plugin's copy re-folds identically until 7.1 deletes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from functualize._types.descriptors import FieldDescriptor, JobDescriptor

__all__ = ["field_property", "input_schema", "job_input_schema"]


def _is_json_native(default: Any) -> bool:
    """True when a default belongs in a schema as a literal value.

    This function serves two masters: the schema extractor includes the
    per-field ``default`` when it is JSON-native, and `field_property` gates a
    contract's ``default_json`` the same way. ``None`` is excluded on purpose:
    it is how both sources spell "no default" (the `_REQUIRED_SENTINEL` for a
    contract, `FieldDescriptor.default`'s `None`).
    """
    if isinstance(default, str | int | float | bool):
        return True
    if isinstance(default, list | tuple):
        return all(_is_json_native(item) for item in default)
    if isinstance(default, dict):
        return all(
            isinstance(key, str) and _is_json_native(value)
            for key, value in default.items()
        )
    return False


def field_property(field: FieldDescriptor) -> dict[str, Any]:
    """The JSON Schema property for a field (schema boundary).

    A property is the field's parameter contract's ``json_schema`` (D4),
    enriched with the declaration's description and the contract's JSON
    default. The contract is the cached verdict, so the default survives a
    cold boot even when the live field's own default does not (F-34). A field
    with no contract publishes a string property, preserving the per-field
    ``enum`` and default rules.
    """
    contract = getattr(field, "contract", None)
    if contract is not None:
        if contract.json_schema is None:
            return {}
        prop = dict(contract.json_schema)
    else:
        prop = {"type": "string"}
    if field.description:
        prop["description"] = field.description
    if contract is not None:
        if not contract.required and _is_json_native(contract.default_json):
            prop["default"] = contract.default_json
    elif not field.required and _is_json_native(field.default):
        prop["default"] = field.default
    if contract is None and field.choices:
        prop["enum"] = list(field.choices)
    return prop


def input_schema(fields: Iterable[FieldDescriptor]) -> dict[str, Any]:
    """A JSON Schema object for a field collection.

    `required` is the contracts' requiredness — whether the declaration has a
    default — not the extractor's per-field judgement; a field with no contract
    keeps its own `required` flag. An empty `required` list is omitted: an empty
    required list is noise on a schema every consumer must branch on.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in fields:
        contract = getattr(field, "contract", None)
        if contract is not None and contract.json_schema is None:
            # The contract publishes nothing: an `INJECTED` parameter is filled
            # by the engine (B-22), and a `REJECTED_DISCOVERY` one is refused at
            # discovery, so no caller may supply either.
            continue
        properties[field.name] = field_property(field)
        needed = contract.required if contract is not None else field.required
        if needed:
            required.append(field.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _specs_on_path(group: str | None, group_options: Mapping[str, Any]) -> list[Any]:
    """Every group-options declaration along `group`'s path, outermost first.

    Mirrors `GroupTrie.group_options_on_path` (inheritance by containment) and
    the MCP translator's `_specs_on_path`: a nested group's declaration wins by
    being applied last.
    """
    if not group or not group_options:
        return []
    segments = group.split(".")
    return [
        spec
        for depth in range(1, len(segments) + 1)
        if (spec := group_options.get(".".join(segments[:depth]))) is not None
    ]


def job_input_schema(
    descriptor: JobDescriptor,
    *,
    group_options_class_names: Iterable[str] = (),
    group_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A JSON Schema object for a job (schema boundary).

    A parameter whose contract names a known `GroupOptions` class is the
    *injection point* for a group's resolved options, not something a caller
    supplies. `group_options_class_names` excludes it on both boots.

    `group_options` (the `{dotted path: GroupOptionsSpec}` declarations) folds
    the options the job inherits by its group path into `properties` — inside
    this function, so `info` and MCP are identical by construction. The job's
    own fields win a name clash and the merged options are never `required`
    (see the module docstring).
    """
    known = frozenset(name for name in group_options_class_names if name)

    def is_group_options(field: FieldDescriptor) -> bool:
        contract = getattr(field, "contract", None)
        return contract is not None and contract.display in known

    fields = descriptor.config_fields or descriptor.parameters
    kept = [f for f in fields if not is_group_options(f)]
    schema = input_schema(kept)
    properties: dict[str, Any] = schema["properties"]
    own_fields = set(properties)
    if not properties:
        schema["required"] = []
    for spec in _specs_on_path(getattr(descriptor, "group", None), group_options or {}):
        for field in spec.fields:
            if field.name in own_fields:
                continue
            prop = field_property(field)
            if prop:
                properties[field.name] = prop
    return schema
