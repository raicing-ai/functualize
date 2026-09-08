"""EventSink adapter — translates sink emit() calls into EventBus events.

`EventBusAdapter` satisfies the sink protocol that `_config/_emit.py` calls,
turning those calls into StructuredEvents on the EventBus. It depends on
`EventBus` alone, so it is legal in `_events`.

Installing it as the config module's sink is deliberately NOT done here:
that touches two peer layers, so it lives in
`functualize._app.event_wiring.install_config_event_sink` — `_app` being the
sole cross-layer wiring point.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._events.bus import EventBus

logger = logging.getLogger(__name__)


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
