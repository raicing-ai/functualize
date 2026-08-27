"""Schema extraction from Pydantic BaseModel subclasses.

Extracts FieldDescriptor metadata from a Pydantic model using
model_json_schema(), producing serializable field metadata suitable for
cache storage and lazy command wrapper reconstruction.
"""

from __future__ import annotations

import enum
import types
from typing import TYPE_CHECKING, Any, get_args, get_origin

from functualize._types.descriptors import FieldDescriptor

if TYPE_CHECKING:
    from pydantic import BaseModel

# JSON schema type → FieldDescriptor type string
_JSON_SCHEMA_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "boolean": "bool",
    "number": "float",
}


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
    fields: list[FieldDescriptor] = []

    for name, prop in properties.items():
        field_type = _map_json_schema_type(prop, config_class, name, schema)
        choices = _extract_choices(config_class, name) if field_type == "enum" else None
        default = _extract_default(config_class, name)
        required = name in required_fields
        help_text = prop.get("description", "")

        # Both secret markers land here as one key: `Secret[str]` emits it via
        # `__get_pydantic_json_schema__`, and `json_schema_extra={"secret": True}`
        # is copied through verbatim by Pydantic. Reading the schema rather than
        # the annotation is what keeps the two markers a single mechanism.
        secret = bool(prop.get("secret", False))

        fields.append(
            FieldDescriptor(
                name=name,
                type_annotation=field_type,
                choices=choices,
                default=default,
                required=required,
                description=help_text,
                secret=secret,
            )
        )

    return fields


def _map_json_schema_type(
    prop: dict[str, Any],
    config_class: type[BaseModel],
    field_name: str,
    root_schema: dict[str, Any],
) -> str:
    """Map a JSON schema property to a FieldDescriptor type string.

    Handles:
    - Direct type mapping (string, integer, boolean, number)
    - Enum detection via $ref to $defs or allOf with $ref
    - Array/list types
    - Optional (anyOf with null) by unwrapping to inner type
    - Fallback to annotation-based detection for complex cases
    """
    # Handle anyOf (Optional/Union types including null)
    if "anyOf" in prop:
        return _map_any_of(prop, config_class, field_name, root_schema)

    # Handle allOf (typically enum references in Pydantic v2)
    if "allOf" in prop:
        return _map_all_of(prop, config_class, field_name, root_schema)

    # Handle $ref (direct enum reference)
    if "$ref" in prop:
        return _map_ref(prop, config_class, field_name, root_schema)

    # Handle array type
    if prop.get("type") == "array":
        return "list[str]"

    # Handle direct type mapping
    json_type = prop.get("type")
    if json_type and json_type in _JSON_SCHEMA_TYPE_MAP:
        return _JSON_SCHEMA_TYPE_MAP[json_type]

    # Fallback: inspect annotation directly
    return _type_from_annotation(config_class, field_name)


def _map_any_of(
    prop: dict[str, Any],
    config_class: type[BaseModel],
    field_name: str,
    root_schema: dict[str, Any],
) -> str:
    """Handle anyOf schemas (Optional[T] / T | None).

    Unwraps to the inner type by filtering out the null variant.
    """
    any_of = prop["anyOf"]
    # Filter out null type entries
    non_null = [item for item in any_of if item.get("type") != "null"]

    if len(non_null) == 1:
        inner = non_null[0]
        # Recurse on the unwrapped inner type
        return _map_json_schema_type(inner, config_class, field_name, root_schema)

    # Multiple non-null types in the union — fall back to annotation
    return _type_from_annotation(config_class, field_name)


def _map_all_of(
    prop: dict[str, Any],
    config_class: type[BaseModel],
    field_name: str,
    root_schema: dict[str, Any],
) -> str:
    """Handle allOf schemas (typically a $ref to an enum in $defs)."""
    all_of = prop["allOf"]
    for item in all_of:
        if "$ref" in item:
            return _map_ref(item, config_class, field_name, root_schema)
    # Fallback
    return _type_from_annotation(config_class, field_name)


def _map_ref(
    prop: dict[str, Any],
    config_class: type[BaseModel],
    field_name: str,
    root_schema: dict[str, Any],
) -> str:
    """Handle $ref schemas — resolve the reference to check if it's an enum."""
    ref_path = prop["$ref"]
    # Pydantic v2 uses #/$defs/EnumName format
    if ref_path.startswith("#/$defs/"):
        def_name = ref_path[len("#/$defs/") :]
        defs = root_schema.get("$defs", {})
        ref_schema = defs.get(def_name, {})

        # Check if it's an enum (has 'enum' key in the definition)
        if "enum" in ref_schema:
            return "enum"

        # Check the type in the referenced definition
        ref_type = ref_schema.get("type")
        if ref_type in _JSON_SCHEMA_TYPE_MAP:
            return _JSON_SCHEMA_TYPE_MAP[ref_type]

    # Fallback: check annotation
    return _type_from_annotation(config_class, field_name)


def _type_from_annotation(config_class: type[BaseModel], field_name: str) -> str:
    """Determine the type string from the model field's Python annotation.

    Used as a fallback when JSON schema type mapping is insufficient.
    """
    field_info = config_class.model_fields.get(field_name)
    if field_info is None:
        return "str"

    annotation = field_info.annotation
    if annotation is None:
        return "str"

    # Unwrap Optional / T | None
    annotation = _unwrap_optional_annotation(annotation)

    # Check enum
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return "enum"

    # Check list
    origin = get_origin(annotation)
    if origin is list:
        return "list[str]"

    # Check base types
    if annotation is str:
        return "str"
    if annotation is int:
        return "int"
    if annotation is bool:
        return "bool"
    if annotation is float:
        return "float"

    # Fallback
    return "str"


def _unwrap_optional_annotation(annotation: Any) -> Any:
    """Unwrap Optional[T] or T | None to the inner type T."""
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is types.UnionType or (
        origin is not None
        and hasattr(origin, "__name__")
        and origin.__name__ == "Union"
    ):
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            return non_none_args[0]

    return annotation


def _extract_choices(config_class: type[BaseModel], field_name: str) -> list[str]:
    """Extract enum choices from a field's annotation.

    Returns the list of str(member.value) for each Enum member.
    """
    field_info = config_class.model_fields.get(field_name)
    if field_info is None:
        return []

    annotation = field_info.annotation
    if annotation is None:
        return []

    # Unwrap Optional
    annotation = _unwrap_optional_annotation(annotation)

    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return [str(member.value) for member in annotation]

    return []


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
