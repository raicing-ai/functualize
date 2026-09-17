"""The plugin-facing host port — what a plugin is allowed to know about the app.

A peer of :class:`~functualize._types.protocols.EngineHost`, which says what the
*engine* needs from outside itself. This module says what a **plugin** needs,
and it is a different, wider list: a plugin registers jobs, reads config, hangs
commands off the CLI, and installs storage, none of which the engine does.

Its own file rather than another class in ``protocols.py`` because the two ports
have different audiences. ``EngineHost`` is read by one implementation inside
this repository; ``PluginHost`` is read by plugin authors outside it, who reach
it through the public ``functualize.plugin`` package. A port with an external
audience is worth a page a reader can open.

Stdlib imports only, like the rest of ``_types``: the whole point of annotating
against a port is that a plugin can name the type without importing the
application.

**Under construction.** ``plugin-host-protocol``/T5 creates this module with the
``on_ready`` handler alias and the placeholder below; T7 fills in the eleven
members and the five view protocols. See ``.spec/features/plugin-host-protocol/``
while that is in flight.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeAlias, runtime_checkable

__all__ = ["OnReadyHandler", "PluginHost"]


@runtime_checkable
class PluginHost(Protocol):
    """What a plugin may ask of the application that loaded it.

    **Empty until T7**, and an empty Protocol is satisfied structurally by
    every object — so an ``app: PluginHost`` annotation written before T7 lands
    constrains the *caller* not at all. It does already constrain the callee:
    mypy rejects any member access on a value of this type, which is why T11's
    annotation sweep waits for T7 rather than running now.

    What it buys in the meantime is the one thing T5 needs: a name with no
    ``Any`` in it, so :data:`OnReadyHandler` can say which parameter type an
    ``APP_READY`` handler takes. ``Callable[[Any], None]`` would not — ``Any``
    is compatible in both directions, so a handler declaring ``app: int`` would
    type-check, which is exactly the class of mistake this feature exists to
    make visible.
    """


OnReadyHandler: TypeAlias = Callable[[PluginHost], None]
"""The shape of an ``APP_READY`` handler: takes the host, returns nothing.

``-> None`` rather than ``-> Any`` because the return value is discarded — the
hook registry calls the handler and drops what comes back — so a handler
annotated as returning something is saying something untrue. All five handlers
that ship return None.
"""
