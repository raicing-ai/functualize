"""Data subpackage — persistence and model classes.

This package consolidates argument history, config snapshots, pending
execution state, invocation presets, shortcut generation, and override
application.
"""

from __future__ import annotations

from functualize._cli.data.argument_history import ArgumentHistory
from functualize._cli.data.config_snapshot_store import (
    ConfigSnapshot,
    ConfigSnapshotStore,
)
from functualize._cli.data.invocation_preset import (
    InvocationPreset,
    get_recent_invocations,
)
from functualize._cli.data.override_applicator import apply_overrides_to_targets
from functualize._cli.data.pending_execution import PendingExecution
from functualize._cli.data.resolved_value_compat import ResolvedValueCompat
from functualize._cli.data.shortcut_generator import (
    ShortcutSpec,
    append_or_write_python_shortcut,
    generate_shortcut_content,
)

__all__: list[str] = [
    "ArgumentHistory",
    "ConfigSnapshot",
    "ConfigSnapshotStore",
    "InvocationPreset",
    "PendingExecution",
    "ResolvedValueCompat",
    "ShortcutSpec",
    "append_or_write_python_shortcut",
    "apply_overrides_to_targets",
    "generate_shortcut_content",
    "get_recent_invocations",
]
