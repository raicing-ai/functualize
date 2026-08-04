"""Surface-stack routing: who receives events, and who answers prompts.

Two registries make up the routing state:

- ``app._surfaces`` — surfaces *registered* at boot (the TUI panel, flow-viz, a
  log writer). The base of the conceptual stack.
- ``app._surface_stack`` — surfaces *pushed* for the duration of a phase (a
  job-owned ``TextualApp`` during an EXCLUSIVE window). ``TTY.run`` and the
  orchestrator push/pop these, ``finally``-guaranteed.

Events fan out to every surface, **except** while an exclusive (terminal-owning)
window is active: then only the top exclusive surface and headless surfaces
(``needs_terminal`` False — log files, MCP progress, test recorders) receive, so
a job that owns the screen is not fighting the TUI panel or flow-viz for the
cursor. Prompts route to exactly one *active* collector: top-of-stack wins, so
the phase that owns the terminal answers.
"""

from __future__ import annotations

from typing import Any

from functualize._types.interactivity import (
    PromptCollector,
    Surface,
    needs_terminal,
)

__all__ = ["active_collector", "active_live_zone", "iter_fanout_surfaces"]


def _is_live_zone(surface: object) -> bool:
    """A surface that can host live constructs (has ``add`` and ``panel``)."""
    return callable(getattr(surface, "add", None)) and callable(
        getattr(surface, "panel", None)
    )


def active_live_zone(app: Any) -> Any | None:
    """Return the surface that should host ``Live`` constructs, or None.

    Top-of-stack wins (a job-owned app's own live zone during its window), then
    the first registered live-capable surface (the CLI's ``StdoutSurface`` /
    the TUI panel region). None in the kernel — ``Live`` then no-ops.
    """
    for surface in reversed(getattr(app, "_surface_stack", [])):
        if _is_live_zone(surface):
            return surface
    for surface in getattr(app, "_surfaces", []):
        if _is_live_zone(surface):
            return surface
    return None


def iter_fanout_surfaces(app: Any) -> list[Surface]:
    """Return the surfaces that should receive an event, in delivery order.

    Registered surfaces first, then the pushed stack. While an exclusive
    terminal window is active, terminal-drawing surfaces other than the active
    one are skipped (they would corrupt the terminal the exclusive surface
    owns); headless surfaces always receive.
    """
    registered = [s for s in getattr(app, "_surfaces", []) if isinstance(s, Surface)]
    stacked = [s for s in getattr(app, "_surface_stack", []) if isinstance(s, Surface)]

    exclusive = [s for s in stacked if needs_terminal(s)]
    if not exclusive:
        return registered + stacked

    active_terminal = exclusive[-1]
    result: list[Surface] = []
    for surface in registered + stacked:
        if needs_terminal(surface) and surface is not active_terminal:
            continue
        result.append(surface)
    return result


def active_collector(app: Any) -> PromptCollector | None:
    """Return the one collector that should answer a prompt (top-of-stack wins).

    Resolution: the topmost pushed surface that can ``collect``, else the first
    registered collector, else the kernel's TTY-gated stdin fallback (which is
    None off a terminal, preserving default/InputNotAvailable behavior there).
    """
    for surface in reversed(getattr(app, "_surface_stack", [])):
        if isinstance(surface, PromptCollector):
            return surface
    for surface in getattr(app, "_surfaces", []):
        if isinstance(surface, PromptCollector):
            return surface

    from functualize._engine.capabilities.stdin_collector import get_stdin_collector

    return get_stdin_collector()
