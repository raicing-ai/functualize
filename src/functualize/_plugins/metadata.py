"""What makes an object a plugin, and whether it is telling the truth.

The `PluginMetadata` contract — `name`, `version`, `description` as strings,
and callable — plus the PEP 440 check on `version` and the adapter-claim
warning. Extracted from `loader.py` by `declared-plugin-directories`/T4 so that
`file_source.py` can validate a file plugin without importing the loader that
imports it.

`loader.py` re-exports these names, so
`from functualize._plugins.loader import _validate_metadata` keeps working —
three test files and about thirty references depend on that spelling, and
moving code is not a reason to churn them.

Only imports from `_types/` and Python stdlib.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from functualize._types.protocols import AdapterPlugin

logger = logging.getLogger(__name__)

__all__ = ["_validate_metadata", "_validate_pep440"]


# PEP 440 version pattern
_PEP440_PATTERN = re.compile(
    r"^([1-9][0-9]*!)?"  # epoch
    r"(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*"  # release
    r"((a|b|rc)(0|[1-9][0-9]*))?"  # pre-release
    r"(\.post(0|[1-9][0-9]*))?"  # post-release
    r"(\.dev(0|[1-9][0-9]*))?$"  # dev release
)


def _validate_pep440(version: str) -> bool:
    """Check if a version string conforms to PEP 440."""
    return _PEP440_PATTERN.match(version) is not None


def _validate_metadata(plugin: Any, entry_point_name: str) -> list[str]:
    """Validate plugin metadata attributes.

    Returns a list of validation error messages. Empty list means valid.
    """
    errors: list[str] = []

    # Check name attribute
    if not hasattr(plugin, "name"):
        errors.append("missing 'name' attribute")
    else:
        name = plugin.name
        if not isinstance(name, str):
            errors.append(f"'name' must be a string, got {type(name).__name__}")
        elif len(name) > 64:
            errors.append(f"'name' exceeds 64 characters (got {len(name)})")

    # Check version attribute
    if not hasattr(plugin, "version"):
        errors.append("missing 'version' attribute")
    else:
        version = plugin.version
        if not isinstance(version, str):
            errors.append(f"'version' must be a string, got {type(version).__name__}")
        elif not _validate_pep440(version):
            errors.append(f"'version' does not conform to PEP 440: {version!r}")

    # Check description attribute
    if not hasattr(plugin, "description"):
        errors.append("missing 'description' attribute")
    else:
        description = plugin.description
        if not isinstance(description, str):
            errors.append(
                f"'description' must be a string, got {type(description).__name__}"
            )
        elif len(description) > 256:
            errors.append(
                f"'description' exceeds 256 characters (got {len(description)})"
            )

    _warn_if_the_adapter_claim_is_false(plugin, entry_point_name)

    return errors


def _warn_if_the_adapter_claim_is_false(plugin: Any, entry_point_name: str) -> None:
    """A plugin that says it is an adapter should be one.

    `plugin-taxonomy`/T9. `functualize-mcp` declared ``adapter_type = "mcp"``,
    said *"Implements the AdapterPlugin protocol"* in its docstring, and had
    **neither `run` nor `shutdown`** — two of the protocol's three methods —
    while its two siblings had both. Nothing noticed, for a plain reason:
    `functualize.app.adapters.validate_adapter` exists to catch exactly this and
    had **no production caller**, only a re-export and five test files.

    Checked here because this is the one function every load path goes through
    — entry points, explicit plugins and file-based plugins all reach it — and
    because `_plugins` may import `_types.protocols` directly. It cannot call
    `validate_adapter`: that lives in the public `app/` package, and the layer
    contract forbids an internal layer from importing public. The protocol
    itself is the shared thing, which is the right shared thing.

    **A warning, not a rejection.** Refusing the plugin would have removed
    `functualize-mcp` from every installation that had it, over a claim that
    changes nothing at runtime — `adapter_type` is declarative and nothing
    dispatches on it. The cost of the defect is a reader believing a docstring,
    so the fix is to say so where somebody will see it.
    """
    if not hasattr(plugin, "adapter_type"):
        return
    if isinstance(plugin, AdapterPlugin):
        return
    missing = [
        member
        for member in ("__call__", "run", "shutdown")
        if not callable(getattr(plugin, member, None))
    ]
    logger.warning(
        "Plugin %r declares adapter_type=%r but does not satisfy AdapterPlugin: "
        "missing %s. It will still load — adapter_type is declarative — but the "
        "claim is false and anything written against the protocol will fail.",
        entry_point_name,
        getattr(plugin, "adapter_type", None),
        ", ".join(missing) or "nothing callable",
    )
