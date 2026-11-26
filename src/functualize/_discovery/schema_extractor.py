"""Schema extraction from Pydantic BaseModel subclasses.

Extracts FieldDescriptor metadata from a Pydantic model using
model_json_schema(), producing serializable field metadata suitable for
cache storage and lazy command wrapper reconstruction.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from functualize._primitives.parameter_contract import build_field_contract
from functualize._types.descriptors import FieldDescriptor
from functualize._types.parameter_contract import Scalar

if TYPE_CHECKING:
    from pydantic import BaseModel

    from functualize._types.parameter_contract import ParameterContract


def extract_field_descriptors(
    config_class: type[BaseModel],
) -> list[FieldDescriptor]:
    """Extract FieldDescriptor list from a Pydantic model using model_json_schema().

    Uses model_json_schema() to extract field definitions and maps them to
    FieldDescriptor instances. Propagates any exceptions from model_json_schema()
    to the caller without catching.

    Args:
        config_class: A Pydantic BaseModel subclass to extract field metadata from.

    Returns:
        A list of FieldDescriptor instances, one per model field.
    """
    schema = config_class.model_json_schema()
    required_fields = set(schema.get("required", []))
    properties = schema.get("properties", {})
    model_fields = getattr(config_class, "model_fields", {})
    fields: list[FieldDescriptor] = []

    for name, prop in properties.items():
        secret = bool(prop.get("secret", False))
        contract = _field_contract(name, model_fields, secret=secret)
        shape = contract.shape if contract is not None else None
        choices = (
            [str(value) for value in shape.enum_values]
            if shape is not None and shape.scalar is Scalar.ENUM
            else None
        )
        default = _extract_default(config_class, name)
        required = name in required_fields
        help_text = prop.get("description", "")

        # Both secret markers land here as one key: `Secret[str]` emits it via
        # `__get_pydantic_json_schema__`, and `json_schema_extra={"secret": True}`
        # is copied through verbatim by Pydantic. Reading the schema rather than
        # the annotation is what keeps the two markers a single mechanism.
        fields.append(
            FieldDescriptor(
                name=name,
                choices=choices,
                default=default,
                required=required,
                description=help_text,
                secret=secret,
                # Every field this function produces comes from a config model
                # by construction — it is the only thing it is ever given. The
                # marker exists because the *consumer* cannot tell: a warm boot
                # sees one `config_fields` list that may hold either kind.
                from_config_model=True,
                # A config field's verdict (spec B-1): `CONFIG_FIELD`, or a
                # refusal for a type no config source can supply (F-29).
                contract=contract,
            )
        )

    return fields


def _field_contract(
    name: str, model_fields: dict[str, Any], *, secret: bool
) -> ParameterContract | None:
    """The field's contract, or None for a property no model field declares."""
    info = model_fields.get(name)
    if info is None:  # an alias-keyed property: no field of that name
        info = next(
            (f for f in model_fields.values() if getattr(f, "alias", None) == name),
            None,
        )
    if info is None:
        return None
    return without_secret_default(build_field_contract(name, info), secret=secret)


def without_secret_default(
    contract: ParameterContract, *, secret: bool
) -> ParameterContract:
    """Drop a secret field's default from its contract, as from its descriptor.

    The cache is a file on disk. ``json_schema_extra={"secret": True}`` marks a
    plain ``str`` field secret, which the classifier cannot see from the type,
    so the default ``_serialize_default`` already drops is dropped here too.
    """
    if not secret or contract.required:
        return contract
    return dataclasses.replace(contract, default_json=None)


def _extract_default(config_class: type[BaseModel], field_name: str) -> Any:
    """Extract the default value for a field.

    Returns None if the field has no default or uses a default_factory.
    For enum defaults, returns the enum instance (downstream serialization
    handles .value conversion).
    """
    from pydantic_core import PydanticUndefined

    field_info = config_class.model_fields.get(field_name)
    if field_info is None:
        return None

    # If the field uses a default_factory, return None
    if field_info.default_factory is not None:
        return None

    # If the field has no default (PydanticUndefined), return None
    if field_info.default is PydanticUndefined:
        return None

    return field_info.default
