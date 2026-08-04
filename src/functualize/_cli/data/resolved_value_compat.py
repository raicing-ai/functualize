"""ResolvedValueCompat — local adapter bridging CLI layer to kernel's ResolvedValue.

The full ResolvedValue lives in _config.chain (kernel layer). The CLI layer
cannot import kernel internals, so this frozen dataclass provides all
attributes that PendingExecution and FieldDetailWidget need:
.value, .source_type, .source_id, .key, and .alternatives.

At runtime boundaries the kernel's ResolvedValue objects are structurally
compatible with this class (duck typing / structural subtyping).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["ResolvedValueCompat"]


@dataclass(frozen=True)
class ResolvedValueCompat:
    """ResolvedValue-compatible object for the CLI layer.

    Mirrors the kernel's ResolvedValue interface so that _cli/ modules
    can type-annotate against this local adapter instead of importing
    from functualize._config.chain.

    Attributes:
        value: The resolved configuration value.
        source_type: Type of source that provided the value
            (e.g., "cli", "env", "file", "remote", "default"). Under the
            SmartBar-as-CLI model, "session" is no
            longer a valid source_type.
        source_id: Identifier of the winning source (e.g., file path,
            "environ", provider name).
        key: The configuration key that was resolved.
        alternatives: Values from lower-priority sources that also
            provide this key. Each entry is (source_type, source_id, value).
    """

    value: Any
    source_type: str  # "default", "file", "env", "cli", "remote"
    source_id: str = ""
    key: str = ""
    alternatives: list[tuple[str, str, Any]] = field(default_factory=list)
