"""Tests for ThemeManager wiring into app lifecycle (task 21.3).

Verifies:
- Built-in themes are registered on construction (Req 16.2)
- activate_theme loads CSS for a valid theme_id (Req 16.5)
- activate_theme falls back to transparent for unknown theme_id (Req 16.6)
- Hot-switch returns new CSS when theme changes (Req 16.4)
"""

from __future__ import annotations

from functualize._cli.tui.theme_manager import ThemeManager


class TestThemeManagerBuiltinRegistration:
    """Req 16.2: 4 built-in themes registered on construction."""

    def test_four_builtin_themes_registered(self) -> None:
        tm = ThemeManager()
        ids = tm.registered_theme_ids
        assert "transparent" in ids
        assert "dark" in ids
        assert "light" in ids
        assert "minimal" in ids
        assert len(ids) == 4

    def test_default_active_theme_is_transparent(self) -> None:
        tm = ThemeManager()
        assert tm.active_theme_id == "transparent"


class TestThemeActivation:
    """Req 16.5: Load matching theme CSS on activation."""

    def test_activate_dark_returns_css(self) -> None:
        tm = ThemeManager()
        css = tm.activate_theme("dark")
        assert css == "/* Dark theme CSS */"
        assert tm.active_theme_id == "dark"

    def test_activate_light_returns_css(self) -> None:
        tm = ThemeManager()
        css = tm.activate_theme("light")
        assert css == "/* Light theme CSS */"
        assert tm.active_theme_id == "light"

    def test_activate_transparent_returns_empty(self) -> None:
        tm = ThemeManager()
        css = tm.activate_theme("transparent")
        assert css == ""
        assert tm.active_theme_id == "transparent"


class TestThemeFallback:
    """Req 16.6: Fall back to transparent if theme_id not found."""

    def test_unknown_theme_falls_back_to_transparent(self) -> None:
        tm = ThemeManager()
        css = tm.activate_theme("nonexistent-theme")
        assert css == ""
        assert tm.active_theme_id == "transparent"


class TestThemeHotSwitch:
    """Req 16.4: Hot-switch theme without restart."""

    def test_switch_from_transparent_to_dark(self) -> None:
        tm = ThemeManager()
        tm.activate_theme("transparent")
        assert tm.active_theme_id == "transparent"

        css = tm.activate_theme("dark")
        assert css == "/* Dark theme CSS */"
        assert tm.active_theme_id == "dark"

    def test_switch_from_dark_to_minimal(self) -> None:
        tm = ThemeManager()
        tm.activate_theme("dark")
        css = tm.activate_theme("minimal")
        assert css == "/* Minimal theme CSS */"
        assert tm.active_theme_id == "minimal"

    def test_switch_to_invalid_reverts_to_transparent(self) -> None:
        tm = ThemeManager()
        tm.activate_theme("dark")
        assert tm.active_theme_id == "dark"

        css = tm.activate_theme("bogus")
        assert css == ""
        assert tm.active_theme_id == "transparent"
