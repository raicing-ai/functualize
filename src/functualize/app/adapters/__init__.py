"""Built-in delivery adapters for FunctualizeApp.

This sub-package contains the two built-in adapter implementations that
ship with the core functualize package:

- ``CliAdapter``: Click-based CLI delivery (requires ``[cli]`` extras)
- ``TuiAdapter``: Terminal UI adapter via inline TUI (requires ``[cli]`` extras)
- ``early_setting_flags``: the ``phase="early"`` flags in argv, read before an
  app is constructed (requires ``[cli]`` extras)

It also exposes the ``AdapterPlugin`` protocol that all adapters
(built-in and external) must satisfy.

External adapters (HTTP, Lambda) live in separate plugin packages
under ``plugins/`` in the monorepo.

Note: CliAdapter, TuiAdapter and early_setting_flags are lazily imported to
avoid pulling CLI dependencies (click, rich, textual) into environments that
only use the core library (e.g., Lambda or HTTP deployments).
"""

from __future__ import annotations

from typing import Any

from functualize._types.protocols import AdapterPlugin as AdapterPlugin
from functualize.app.adapters._validation import (
    _ADAPTER_REQUIRED_FIELDS as _ADAPTER_REQUIRED_FIELDS,
)
from functualize.app.adapters._validation import (
    _ADAPTER_REQUIRED_METHODS as _ADAPTER_REQUIRED_METHODS,
)
from functualize.app.adapters._validation import (
    _get_missing_adapter_members as _get_missing_adapter_members,
)
from functualize.app.adapters._validation import (
    validate_adapter as validate_adapter,
)

__all__ = [
    "AdapterPlugin",
    "CliAdapter",
    "TuiAdapter",
    "early_setting_flags",
]


def __getattr__(name: str) -> Any:
    """Lazy import adapters on first access to avoid CLI dependency loading."""
    if name == "CliAdapter":
        from functualize.app.adapters.cli import CliAdapter

        return CliAdapter
    if name == "TuiAdapter":
        from functualize.app.adapters.tui import TuiAdapter

        return TuiAdapter
    if name == "early_setting_flags":
        from functualize.app.adapters.settings_flags import early_setting_flags

        return early_setting_flags
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
