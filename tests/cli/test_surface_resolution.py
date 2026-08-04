"""Surface-resolution ladder (orchestrator) + Live-zone binding."""

from __future__ import annotations

from types import SimpleNamespace

from functualize._cli.orchestrator import RenderSurface, resolve_surface
from functualize._engine.surface_routing import active_live_zone

# --- resolution ladder ------------------------------------------------------


def test_requires_tty_forces_exclusive_over_everything() -> None:
    assert (
        resolve_surface(requires_tty=True, hint="panel", setting="stdout")
        is RenderSurface.EXCLUSIVE
    )


def test_hint_beats_setting_and_default() -> None:
    assert (
        resolve_surface(
            requires_tty=False,
            hint="stdout",
            setting="panel",
            framework_default=RenderSurface.PANEL,
        )
        is RenderSurface.STDOUT
    )


def test_setting_used_when_no_hint() -> None:
    assert (
        resolve_surface(requires_tty=False, hint=None, setting="stdout")
        is RenderSurface.STDOUT
    )


def test_framework_default_when_nothing_specified() -> None:
    assert (
        resolve_surface(requires_tty=False, framework_default=RenderSurface.STDOUT)
        is RenderSurface.STDOUT
    )
    assert resolve_surface(requires_tty=False) is RenderSurface.PANEL


def test_unknown_preference_strings_ignored() -> None:
    assert (
        resolve_surface(requires_tty=False, hint="bogus", setting="panel")
        is RenderSurface.PANEL
    )


# --- Live-zone binding ------------------------------------------------------


class _Zone:
    def add(self, c: object) -> None: ...
    def panel(self, c: object) -> None: ...


class _NotAZone:
    def handle_event(self, e: object) -> None: ...


def test_active_live_zone_finds_registered_zone() -> None:
    zone = _Zone()
    app = SimpleNamespace(_surfaces=[_NotAZone(), zone], _surface_stack=[])
    assert active_live_zone(app) is zone


def test_active_live_zone_prefers_top_of_stack() -> None:
    registered = _Zone()
    stacked = _Zone()
    app = SimpleNamespace(_surfaces=[registered], _surface_stack=[stacked])
    assert active_live_zone(app) is stacked


def test_active_live_zone_none_when_no_zone() -> None:
    app = SimpleNamespace(_surfaces=[_NotAZone()], _surface_stack=[])
    assert active_live_zone(app) is None
