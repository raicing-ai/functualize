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
        group_path: The group that declared this field, or ``None`` for the
            job's own. The diff shows group and job entries in one list — a
            change is a change wherever the field was declared — and this is
            what lets a row say which. Defaulted, so an ungrouped project's
            diff is byte-identical.
    """

    field_name: str
    status: str
    current_value: Any
    current_source: str
    previous_value: Any | None
    previous_source: str | None
    group_path: str | None = None


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
    # Group options join the job's own fields in one list. A change is a
    # change wherever the field was declared, and splitting them into two
    # sections would ask the reader to check twice for one question.
    # Keyed by their declaring group so a group's `env` and a job's own `env`
    # stay two rows, not one — the flat values dict cannot tell them apart.
    group_keys = {
        f"{pending.group_option_paths[name]}.{name}"
        if name in pending.group_option_paths
        else name: name
        for name in pending.group_option_values
    }

    current_fields = set(pending.resolved_values.keys()) | set(group_keys)
    previous_fields = set(previous.values.keys()) if previous else set()
    all_fields = current_fields | previous_fields

    if not all_fields:
        return []

    entries: list[ConfigDiffEntry] = []

    def _group_path_of(key: str) -> str | None:
        """The declaring group for a key, or None for a job's own field.

        A **removed** entry is in the previous snapshot and not in the current
        one, so it is absent from ``group_keys`` — yet its stored key is still
        the group-prefixed `deploy.env`. Falling through to ``None`` there
        printed that key raw, one row below a `[deploy] env` that had survived.
        A key the job does not declare and that carries a dot is a group's, and
        is labelled as one.
        """
        if key in group_keys and key not in pending.resolved_values:
            return key.rsplit(".", 1)[0] if "." in key else None
        if key not in pending.resolved_values and "." in key:
            return key.rsplit(".", 1)[0]
        return None

    def _current(key: str) -> tuple[Any, str]:
        """Effective value and source for a key, group or job."""
        if key in group_keys and key not in pending.resolved_values:
            return pending.group_option_values[group_keys[key]], "cli"
        return pending.effective_value(key), pending.effective_source(key)

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
                    group_path=_group_path_of(field),
                )
            )
        elif previous is None or field not in previous_fields:
            # Field exists in current but not previous → new
            new_val, new_src = _current(field)
            entries.append(
                ConfigDiffEntry(
                    field_name=field,
                    status="new",
                    current_value=new_val,
                    current_source=new_src,
                    previous_value=None,
                    previous_source=None,
                    group_path=_group_path_of(field),
                )
            )
        else:
            # Field exists in both — compare values
            current_val, current_src = _current(field)
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
                    group_path=_group_path_of(field),
                )
            )

    return entries
