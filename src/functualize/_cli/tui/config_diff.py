"""Config diff computation between current PendingExecution and previous snapshot.

Pure-logic module with no Textual dependency. Computes field-by-field diffs
for display in the DiffViewWidget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._cli.data.config_snapshot_store import ConfigSnapshot
    from functualize._cli.data.pending_execution import PendingExecution


@dataclass(frozen=True)
class ConfigDiffEntry:
    """A single field's diff between current and previous execution.

    Attributes:
        field_name: The configuration field name.
        status: One of "changed", "unchanged", "new", or "removed".
        current_value: The current effective value (None if removed).
        current_source: The current value's source label (empty string if removed).
        previous_value: The previous value (None if new or no previous).
        previous_source: The previous value's source (None if new or no previous).
    """

    field_name: str
    status: str
    current_value: Any
    current_source: str
    previous_value: Any | None
    previous_source: str | None


def compute_config_diff(
    pending: PendingExecution,
    previous: ConfigSnapshot | None,
) -> list[ConfigDiffEntry]:
    """Compute field-by-field diff between current state and previous snapshot.

    Args:
        pending: The current PendingExecution with resolved values and overrides.
        previous: The previous execution's ConfigSnapshot, or None if no prior
            execution exists.

    Returns:
        A sorted list of ConfigDiffEntry objects (alphabetical by field_name),
        one per field in the union of current and previous field sets.
        Returns an empty list if both resolved_values is empty and previous is None.
    """
    current_fields = set(pending.resolved_values.keys())
    previous_fields = set(previous.values.keys()) if previous else set()
    all_fields = current_fields | previous_fields

    if not all_fields:
        return []

    entries: list[ConfigDiffEntry] = []

    for field in sorted(all_fields):
        if field not in current_fields:
            # Field exists in previous but not current → removed
            prev_val = previous.values[field] if previous else None
            entries.append(
                ConfigDiffEntry(
                    field_name=field,
                    status="removed",
                    current_value=None,
                    current_source="",
                    previous_value=prev_val,
                    previous_source=None,
                )
            )
        elif previous is None or field not in previous_fields:
            # Field exists in current but not previous → new
            entries.append(
                ConfigDiffEntry(
                    field_name=field,
                    status="new",
                    current_value=pending.effective_value(field),
                    current_source=pending.effective_source(field),
                    previous_value=None,
                    previous_source=None,
                )
            )
        else:
            # Field exists in both — compare values
            current_val = pending.effective_value(field)
            current_src = pending.effective_source(field)
            prev_val = previous.values[field]

            status = "unchanged" if current_val == prev_val else "changed"

            entries.append(
                ConfigDiffEntry(
                    field_name=field,
                    status=status,
                    current_value=current_val,
                    current_source=current_src,
                    previous_value=prev_val,
                    previous_source=None,
                )
            )

    return entries
