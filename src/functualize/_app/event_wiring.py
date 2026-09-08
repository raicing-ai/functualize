"""Cross-layer event wiring, owned by the composition root.

`_config/_emit.py` exposes no-op emit points that are called on every config
operation. Routing those through the EventBus means replacing its sink with an
`EventBusAdapter` — which touches two peer layers at once (`_config` and
`_events`).

That wiring lives here rather than in `_events` because `_app` is the sole
cross-layer wiring point (`.spec/CONSTITUTION.md`). It used to live in
`_events/adapter.py::install_adapter`, which made `_events` import `_config`
at runtime — a constitution violation that no import-linter contract caught,
because `_events` was not a source module in any contract forbidding a peer.
The "Events depends on foundation only" contract now closes that gap, and this
module is where the coupling was moved to.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._events.bus import EventBus

logger = logging.getLogger(__name__)

_sink_installed: bool = False


def install_config_event_sink(event_bus: EventBus) -> None:
    """Route config resolution events through ``event_bus``.

    Installs an :class:`~functualize._events.adapter.EventBusAdapter` as the
    config module's event sink, then replaces ``set_event_sink`` with a stub
    that raises, so nothing can re-point the sink afterwards.

    Idempotent: calling multiple times has no additional effect, and events are
    never double-routed.

    Tolerates a missing ``functualize._config._emit`` — the pluggable
    configuration spec may not be implemented in a given build. In that case
    the absence is logged at debug level, the install is marked done, and no
    exception escapes.

    Args:
        event_bus: The EventBus instance to route config events through.
    """
    global _sink_installed

    if _sink_installed:
        return

    try:
        from functualize._config._emit import set_event_sink
    except (ImportError, ModuleNotFoundError):
        # config._emit doesn't exist yet — skip installation gracefully
        logger.debug(
            "config._emit not available; EventBusAdapter not installed. "
            "Config events will not route through EventBus."
        )
        _sink_installed = True
        return

    from functualize._events.adapter import EventBusAdapter

    adapter = EventBusAdapter(event_bus)
    set_event_sink(adapter)

    # Block direct calls once the adapter owns the sink. Rebinding the module
    # attribute is why this has to import the module object as well as the
    # function: the raising stub replaces the name that other callers resolve.
    import functualize._config._emit as emit_module

    def _blocked_set_event_sink(sink: Any) -> None:
        raise RuntimeError(
            "Cannot call set_event_sink() after EventBus adapter is installed. "
            "Use app.event_bus.subscribe() instead."
        )

    emit_module.set_event_sink = _blocked_set_event_sink

    _sink_installed = True
