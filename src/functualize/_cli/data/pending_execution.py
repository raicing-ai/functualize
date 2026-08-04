"""PendingExecution state model for config views.

Pure-logic module with no Textual dependency. Accumulates config overrides
until execution commit. All config views share this as the single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._cli.data.resolved_value_compat import ResolvedValueCompat


@dataclass
class PendingExecution:
    """Accumulates config overrides until execution commit.

    All config views (pre-flight, config table, field detail, diff)
    read from and write to this single object.

    Under the SmartBar-as-CLI model an override is a
    plain CLI value written directly into ``overrides`` — there is no per-field
    persistence target and no ``set_override`` helper.

    Attributes:
        job_name: The job this pending execution is for.
        resolved_values: Mapping of field names to their ResolvedValue from
            the ResolutionChain.
        overrides: User-applied override values, keyed by field name.
    """

    job_name: str
    resolved_values: dict[str, ResolvedValueCompat]
    overrides: dict[str, Any] = field(default_factory=dict)

    def effective_value(self, field_name: str) -> Any:
        """Return override value if set, otherwise the resolved chain value.

        Args:
            field_name: The configuration field to look up.

        Returns:
            The effective value for the field.

        Raises:
            KeyError: If field_name is not in resolved_values.
        """
        if field_name not in self.resolved_values:
            msg = f"Unknown field: {field_name!r}"
            raise KeyError(msg)
        if field_name in self.overrides:
            return self.overrides[field_name]
        return self.resolved_values[field_name].value

    def effective_source(self, field_name: str) -> str:
        """Return 'cli' if field is overridden, else the resolved source_type.

        Every entry in ``overrides`` is bar-synced and therefore
        CLI-equivalent under the SmartBar-as-CLI model, so an
        overridden field reports ``"cli"`` rather than the former ``"override"``
        sentinel.

        Args:
            field_name: The configuration field to look up.

        Returns:
            The source label for the field's effective value.

        Raises:
            KeyError: If field_name is not in resolved_values.
        """
        if field_name not in self.resolved_values:
            msg = f"Unknown field: {field_name!r}"
            raise KeyError(msg)
        if field_name in self.overrides:
            return "cli"
        return self.resolved_values[field_name].source_type

    def clear_override(self, field_name: str) -> None:
        """Remove override for a field, restoring chain-resolved value.

        No-op if the field has no override.

        Args:
            field_name: The field to clear the override for.
        """
        self.overrides.pop(field_name, None)

    def has_override(self, field_name: str) -> bool:
        """Check if a field has an active override.

        Args:
            field_name: The field to check.

        Returns:
            True if the field has an override set.
        """
        return field_name in self.overrides

    def override_count(self) -> int:
        """Return the number of active overrides.

        Returns:
            The count of overridden fields.
        """
        return len(self.overrides)

    def all_effective(self) -> dict[str, tuple[Any, str]]:
        """Return all fields with their effective values and source labels.

        Returns:
            A dict mapping each field name to a (value, source_label) tuple.
            Source label is "cli" if the field has an override, otherwise
            the resolved_values entry's source_type.
        """
        result: dict[str, tuple[Any, str]] = {}
        for field_name in self.resolved_values:
            result[field_name] = (
                self.effective_value(field_name),
                self.effective_source(field_name),
            )
        return result
