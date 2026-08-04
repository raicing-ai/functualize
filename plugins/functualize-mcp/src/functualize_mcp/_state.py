"""MCP's slice of the kernel's sanctioned extension-state namespace.

The MCP server is a long-lived consumer that needs state the kernel has no
opinion about: gate checkpoints awaiting external AI input, and input handed
back by ``resume_workflow``. That state used to be monkey-patched onto the
``FunctualizeApp`` instance as private ``_mcp_*`` attributes. It now lives
under ``app.extension_state["mcp"]``, the kernel's documented slot for
exactly this.

Every accessor here tolerates an app without ``extension_state`` (test
doubles, partially-constructed apps) by returning an ephemeral dict rather
than raising — the same forgiving behavior the ``getattr``-guarded
monkey-patching had.
"""

from __future__ import annotations

from typing import Any

__all__ = ["gate_checkpoints", "mcp_state", "pending_gate_input"]

#: Namespace key under ``app.extension_state``.
_NAMESPACE = "mcp"


def mcp_state(app: Any) -> dict[str, Any]:
    """Return MCP's extension-state namespace, creating it if needed."""
    extension_state = getattr(app, "extension_state", None)
    if extension_state is None:
        # An app predating the public API (or a bare test double): hand back a
        # throwaway dict so callers still get dict semantics, not an
        # AttributeError. State simply does not persist for such an app.
        return {}
    namespace = extension_state.setdefault(_NAMESPACE, {})
    return namespace  # type: ignore[no-any-return]


def gate_checkpoints(app: Any) -> dict[str, Any]:
    """Return the gate-checkpoint store (model name -> checkpoint dict)."""
    return mcp_state(app).setdefault("gate_checkpoints", {})  # type: ignore[no-any-return]


def pending_gate_input(app: Any) -> dict[str, Any]:
    """Return the pending-gate-input store (model/step name -> input dict)."""
    return mcp_state(app).setdefault("pending_gate_input", {})  # type: ignore[no-any-return]
