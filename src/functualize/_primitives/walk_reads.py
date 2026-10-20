"""Pure reads of node results recorded in one workflow scope.

The caller supplies only that scope's records.  No project fingerprint or
other walk can be consulted from this module.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

from functualize._primitives.fingerprint import reusable_return_value
from functualize._types.errors import FromStepUnavailableError
from functualize._types.from_job import FromStep


@dataclass(frozen=True)
class Recorded:
    """A node produced a reusable value, including a deliberate ``None``."""

    value: Any


@dataclass(frozen=True)
class NotRecorded:
    """This scope contains no successful record for the named node."""


@dataclass(frozen=True)
class NotCarriable:
    """The node ran, but the stored value cannot be handed to a reader."""


WalkRecords: TypeAlias = (
    Mapping[str, Mapping[str, Any]] | Iterable[tuple[str, Mapping[str, Any]]]
)


# TRANSITIONAL(3.2): Engine injection will call this reader for walk parameters.
def read_node(
    records: WalkRecords, node: str, expected_type: Any = None
) -> Recorded | NotRecorded | NotCarriable:
    """Read the canonical node's completed record from one scope.

    A step key can include an iteration suffix after ``::``.  Its prefix is
    the graph node identity; matching the whole key would lose every ordinary
    step record.  The caller supplies a mapping or its ``items()`` view.
    """
    pairs = records.items() if isinstance(records, Mapping) else records
    for key, record in pairs:
        if key.split("::", 1)[0] != node:
            continue
        if record.get("status") != "success":
            return NotRecorded()
        if record.get("return_value_reusable") is False:
            return NotCarriable()
        value = reusable_return_value(
            record, job_name=node, expected_type=expected_type
        )
        if value is None and record.get("return_value") is not None:
            return NotCarriable()
        return Recorded(value)
    return NotRecorded()


# TRANSITIONAL(5.1): The core gate-tool path will consume this shared resolver.
def resolve_bound_values(
    records: WalkRecords,
    bound: Mapping[str, Any],
    *,
    reader: str = "Tool",
    scope_id: str | None = None,
) -> dict[str, Any]:
    """Replace each bound ``FromStep`` with a value from this scope."""
    resolved: dict[str, Any] = {}
    for parameter, value in bound.items():
        if not isinstance(value, FromStep):
            resolved[parameter] = value
            continue
        result = read_node(records, value.name)
        if isinstance(result, Recorded):
            resolved[parameter] = result.value
            continue
        reason = (
            "node has no record in this walk"
            if isinstance(result, NotRecorded)
            else "recorded value cannot be carried to this reader"
        )
        raise FromStepUnavailableError(
            node=value.name,
            parameter=parameter,
            reader=reader,
            scope_id=scope_id,
            reason=reason,
        )
    return resolved
