"""Theme management for the TUI.

Registers ThemeProviders, loads CSS, manages semantic color variables,
and supports hot-switching themes without restart.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize.plugin.protocols import ThemeProvider

logger = logging.getLogger(__name__)

# Default semantic color variables
_DEFAULT_SEMANTIC_VARS: dict[str, str] = {
    "$bar-ready": "#00ff00",
    "$bar-incomplete": "#808080",
    "$override-indicator": "#ffaa00",
    "$diff-changed": "#ffff00",
    "$diff-new": "#00ff00",
    "$diff-removed": "#ff0000",
    "$highlight": "#0066cc",
    "$panel-border": "#444444",
}


class TransparentTheme:
    """Built-in transparent theme (default fallback)."""

    theme_id = "transparent"
    theme_name = "Transparent"

    def get_css(self) -> str:
        return ""  # No styling — fully transparent


class DarkTheme:
    """Built-in dark theme."""

    theme_id = "dark"
    theme_name = "Dark"

    def get_css(self) -> str:
        return "/* Dark theme CSS */"


class LightTheme:
    """Built-in light theme."""

    theme_id = "light"
    theme_name = "Light"

    def get_css(self) -> str:
        return "/* Light theme CSS */"


class MinimalTheme:
    """Built-in minimal theme."""

    theme_id = "minimal"
    theme_name = "Minimal"

    def get_css(self) -> str:
        return "/* Minimal theme CSS */"


@dataclass
class ThemeManager:
    """Manages theme registration, loading, and hot-switching."""

    _registered_themes: dict[str, ThemeProvider] = field(default_factory=dict)
    _active_theme_id: str = "transparent"
    _active_css: str = ""
    _semantic_variables: dict[str, str] = field(
        default_factory=lambda: dict(_DEFAULT_SEMANTIC_VARS)
    )

    def __post_init__(self) -> None:
        """Register built-in themes."""
        self.register_theme(TransparentTheme())
        self.register_theme(DarkTheme())
        self.register_theme(LightTheme())
        self.register_theme(MinimalTheme())

    def register_theme(self, provider: ThemeProvider) -> None:
        """Register a theme provider. Last registration wins on duplicate IDs."""
        if provider.theme_id in self._registered_themes:
            logger.warning(
                "Theme '%s' already registered, overwriting with new provider",
                provider.theme_id,
            )
        self._registered_themes[provider.theme_id] = provider

    def activate_theme(self, theme_id: str) -> str:
        """Activate a theme by ID. Returns the CSS string.

        Falls back to "transparent" if theme_id not found or CSS is invalid.
        """
        provider = self._registered_themes.get(theme_id)
        if provider is None:
            logger.warning(
                "Theme '%s' not found, falling back to 'transparent'", theme_id
            )
            return self._fallback_to_transparent()

        try:
            css = provider.get_css()
        except Exception:
            logger.error(
                "Theme '%s' get_css() failed, falling back to 'transparent'",
                theme_id,
                exc_info=True,
            )
            return self._fallback_to_transparent()

        self._active_theme_id = theme_id
        self._active_css = css
        return css

    def _fallback_to_transparent(self) -> str:
        """Fall back to transparent theme."""
        self._active_theme_id = "transparent"
        transparent = self._registered_themes.get("transparent")
        self._active_css = transparent.get_css() if transparent else ""
        return self._active_css

    @property
    def active_theme_id(self) -> str:
        return self._active_theme_id

    @property
    def active_css(self) -> str:
        return self._active_css

    @property
    def semantic_variables(self) -> dict[str, str]:
        return dict(self._semantic_variables)

    @property
    def registered_theme_ids(self) -> list[str]:
        return list(self._registered_themes.keys())
