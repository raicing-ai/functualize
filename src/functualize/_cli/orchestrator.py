"""Terminal orchestrator — resolve where a job renders.

The rendering surface (who owns the terminal while a job runs, and who draws on
it) is resolved by a precedence ladder, then clamped by the capability floor.
This module owns the pure decision; wiring the PANEL/STDOUT/EXCLUSIVE handoff
into the inline-TUI loop builds on top of it.

``_cli`` layer — public API / stdlib only.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["RenderSurface", "explicit_surface", "resolve_surface"]


class RenderSurface(Enum):
    """Where a job renders.

    - ``PANEL``: the func TUI owns the terminal; the job runs on a worker
      thread and events go to the TUI's output panel.
    - ``STDOUT``: the func Rich runtime owns the terminal (host exited); events
      go to scrollback + a live zone (``StdoutSurface``).
    - ``EXCLUSIVE``: the job owns the terminal and draws directly via ``TTY``.
    """

    PANEL = "panel"
    STDOUT = "stdout"
    EXCLUSIVE = "exclusive"


def resolve_surface(
    *,
    requires_tty: bool,
    hint: str | None = None,
    setting: str | None = None,
    framework_default: RenderSurface = RenderSurface.PANEL,
) -> RenderSurface:
    """Resolve the rendering surface by the precedence ladder (top wins).

    1. **HARD requirement** — a ``tty: TTY`` parameter (``requires_tty``) forces
       EXCLUSIVE. A violated requirement is an error, so it cannot be overridden
       by a preference below.
    2. **Job HINT** — a metadata preference (``"panel"`` / ``"stdout"``);
       ignorable without breakage.
    3. **TUI SETTING** — ``tui.default_surface`` (``"panel"`` / ``"stdout"``).
    4. **FRAMEWORK DEFAULT** — PANEL inside the TUI, STDOUT for direct
       ``func <job>`` (the caller passes the right default).

    The **capability floor** (EXCLUSIVE needs a real terminal; MCP/CI/piped
    cannot grant it) is enforced by the caller, which refuses when it cannot
    honour the resolved surface — see ``TerminalUnavailable``.
    """
    if requires_tty:
        return RenderSurface.EXCLUSIVE
    return _parse(hint) or _parse(setting) or framework_default


def explicit_surface(
    hint: str | None, setting: str | None = None
) -> RenderSurface | None:
    """The ladder's *preference* rungs only: job hint, then setting.

    Returns None when neither states a preference — unlike
    :func:`resolve_surface` there is no framework default, so callers can
    distinguish "explicitly asked for STDOUT" from "defaulted to STDOUT".
    Direct runs use this to decide whether to register a ``StdoutSurface``
    without changing the output of every plain ``func <job>``.
    """
    return _parse(hint) or _parse(setting)


def _parse(value: str | None) -> RenderSurface | None:
    """Parse a preference string into a non-exclusive surface, or None."""
    if value == "panel":
        return RenderSurface.PANEL
    if value == "stdout":
        return RenderSurface.STDOUT
    return None
