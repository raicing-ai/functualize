"""Plugin config registry for storing resolved plugin config model instances.

Only imports from _types/, _primitives/, _events/, and Python stdlib.
"""

from __future__ import annotations

from typing import Any

__all__ = ["PluginConfigRegistry"]


class PluginConfigRegistry:
    """Stores resolved plugin config model instances keyed by config_section.

    Thread-safe for reads after bootstrap. Mutable only during plugin loading.

    The registry accepts any object as a config value — typically a Pydantic
    BaseModel instance resolved through the application's Resolution Chain.
    """

    def __init__(self) -> None:
        self._configs: dict[str, Any] = {}
        self._section_to_plugin: dict[str, str] = {}  # section -> plugin name

    def register(self, section: str, config: Any, plugin_name: str) -> None:
        """Register a resolved plugin config.

        Args:
            section: The config section namespace (e.g., "plugin.notifications").
            config: The resolved config model instance.
            plugin_name: The name of the plugin registering this config.

        Raises:
            ValueError: If section is already registered by another plugin.
        """
        if section in self._configs:
            existing = self._section_to_plugin[section]
            raise ValueError(
                f"Plugin config section '{section}' is already registered "
                f"by plugin '{existing}'. Conflicting plugin: '{plugin_name}'"
            )
        self._configs[section] = config
        self._section_to_plugin[section] = plugin_name

    def get(self, section: str) -> Any:
        """Retrieve a plugin config by section.

        Args:
            section: The config section namespace to look up.

        Returns:
            The resolved config model instance.

        Raises:
            KeyError: If section is not registered.
        """
        if section not in self._configs:
            available = list(self._configs.keys())
            raise KeyError(
                f"No plugin config registered for section '{section}'. "
                f"Available sections: {available}"
            )
        return self._configs[section]

    def get_all(self) -> dict[str, Any]:
        """Return a copy of all registered configs."""
        return dict(self._configs)

    def has(self, section: str) -> bool:
        """Check if a section is registered."""
        return section in self._configs

    def sections(self) -> list[str]:
        """Return all registered config section names."""
        return list(self._configs.keys())

    def plugin_for_section(self, section: str) -> str | None:
        """Return the plugin name that registered a given section, or None."""
        return self._section_to_plugin.get(section)
