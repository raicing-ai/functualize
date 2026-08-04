"""Type hint formatter for FieldDescriptor display.

Maps FieldDescriptor type_annotation strings to concise display forms
and formats constraint ranges using bracket notation.
"""

from __future__ import annotations

# Type annotation → display type mapping
_TYPE_MAP: dict[str, str] = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "Path": "Path",
    "FilePath": "Path",
    "DirectoryPath": "Dir",
    "pathlib.Path": "Path",
}

_DISPLAY_WIDTH = 12


def format_type_hint(
    type_annotation: str,
    *,
    ge: float | int | None = None,
    le: float | int | None = None,
    gt: float | int | None = None,
    lt: float | int | None = None,
    choices: list[str] | None = None,
) -> str:
    """Format a FieldDescriptor type_annotation for display.

    Args:
        type_annotation: The raw type annotation string (e.g., "int", "str", "list[str]")
        ge: Greater-than-or-equal constraint (inclusive lower bound)
        le: Less-than-or-equal constraint (inclusive upper bound)
        gt: Greater-than constraint (exclusive lower bound)
        lt: Less-than constraint (exclusive upper bound)
        choices: If present, type displays as "enum"

    Returns:
        A fixed-width (12 char) right-padded string. E.g., "int [1..100]"
    """
    # Determine base type
    if choices:
        base_type = "enum"
    elif type_annotation.startswith("list["):
        # Keep as-is: list[str], list[int], etc.
        base_type = type_annotation
    elif type_annotation in _TYPE_MAP:
        base_type = _TYPE_MAP[type_annotation]
    else:
        base_type = type_annotation

    # Format constraint range if any numeric bounds exist
    constraint = _format_constraint(ge=ge, le=le, gt=gt, lt=lt)
    result = f"{base_type}{constraint}" if constraint else base_type

    # Right-pad to fixed width
    return result.ljust(_DISPLAY_WIDTH)


def _format_constraint(
    *,
    ge: float | int | None = None,
    le: float | int | None = None,
    gt: float | int | None = None,
    lt: float | int | None = None,
) -> str:
    """Format constraint as bracket notation.

    - [N..M] for inclusive bounds (ge/le)
    - (N..M) for exclusive bounds (gt/lt)
    - Mixed: [N..M) or (N..M] for one inclusive and one exclusive
    - Empty string if no constraints
    """
    # Determine lower bound
    lower_val: float | int | None = None
    lower_bracket = ""
    if ge is not None:
        lower_val = ge
        lower_bracket = "["
    elif gt is not None:
        lower_val = gt
        lower_bracket = "("

    # Determine upper bound
    upper_val: float | int | None = None
    upper_bracket = ""
    if le is not None:
        upper_val = le
        upper_bracket = "]"
    elif lt is not None:
        upper_val = lt
        upper_bracket = ")"

    if lower_val is None and upper_val is None:
        return ""

    lower_str = _format_number(lower_val) if lower_val is not None else ""
    upper_str = _format_number(upper_val) if upper_val is not None else ""

    # Handle one-sided constraints
    if lower_val is not None and upper_val is None:
        return f"{lower_bracket}{lower_str}..)"
    if lower_val is None and upper_val is not None:
        return f"(..{upper_str}{upper_bracket}"

    return f"{lower_bracket}{lower_str}..{upper_str}{upper_bracket}"


def _format_number(value: float | int) -> str:
    """Format a number for display (integers without decimal)."""
    if isinstance(value, int) or (isinstance(value, float) and value == int(value)):
        return str(int(value))
    return str(value)
