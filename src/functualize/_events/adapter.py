"""EventSink adapter — bridges config._emit → EventBus.

Translates config module emit() calls into StructuredEvents routed
through the EventBus. Handles gracefully if config._emit doesn't exist.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._events.bus import EventBus

logger = logging.getLogger(__name__)

_adapter_installed: bool = False


class EventBusAdapter:
    """Adapter implementing the EventSink protocol from config._emit.

    Routes config module emit() calls through the EventBus with
    explicit resource support and fallback heuristic derivation.

    When ``resource`` is provided explicitly in the payload (non-empty),
    it is used directly. Otherwise, the fallback heuristic derives
    resource from payload fields for backward compatibility:

    Fallback resource derivation priority:
        1. ``path`` field (file-related events)
        2. ``provider`` field (remote/provider events)
        3. ``section`` field (section-scoped events)
        4. Empty string (fallback)

    All remaining payload fields are preserved and passed through to the
    EventBus as keyword arguments.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def emit(self, event_name: str, **payload: Any) -> None:
        """Translate config emit call to EventBus emission.

        If ``resource`` is explicitly provided in the payload and non-empty,
        uses it directly. Otherwise falls back to heuristic derivation from
        payload fields for backward compatibility.

        Args:
            event_name: The event name from the config module emit site.
            **payload: Keyword arguments from the config emit call.
        """
        # Pop resource from payload; use it directly if non-empty
        resource = payload.pop("resource", "")

        # Fallback heuristic only when resource is empty (backward compat)
        if not resource:
            if "path" in payload:
                resource = str(payload["path"])
            elif "provider" in payload:
                resource = str(payload["provider"])
            elif "section" in payload:
                resource = str(payload["section"])

        self._event_bus.emit(event_name, resource=resource, **payload)


def install_adapter(event_bus: EventBus) -> None:
    """Install the EventBusAdapter as the config module's event sink.

    Idempotent: calling multiple times has no additional effect.
    After installation, set_event_sink() raises RuntimeError to prevent
    direct calls — callers should use app.event_bus.subscribe() instead.

    Handles gracefully if config._emit module doesn't exist yet
    (from the pluggable-configuration spec that may not be implemented).

    Args:
        event_bus: The EventBus instance to route config events through.
    """
    global _adapter_installed

    if _adapter_installed:
        return

    try:
        from functualize._config._emit import set_event_sink
    except (ImportError, ModuleNotFoundError):
        # config._emit doesn't exist yet — skip installation gracefully
        logger.debug(
            "config._emit not available; EventBusAdapter not installed. "
            "Config events will not route through EventBus."
        )
        _adapter_installed = True
        return

    adapter = EventBusAdapter(event_bus)
    set_event_sink(adapter)

    # Monkey-patch set_event_sink to prevent direct calls after installation
    import functualize._config._emit as emit_module

    def _blocked_set_event_sink(sink: Any) -> None:
        raise RuntimeError(
            "Cannot call set_event_sink() after EventBus adapter is installed. "
            "Use app.event_bus.subscribe() instead."
        )

    emit_module.set_event_sink = _blocked_set_event_sink
    _adapter_installed = True
