"""The settings panel's catalog is instance state, not a module global.

Each panel renders the declaration it is handed: the shell passes func's
`surface="tui"` rows, a second app passes its own, and no import-time registry
decides for them.
"""

from __future__ import annotations

import pytest

from functualize._cli.tui.settings_panel import SettingsPanel
from functualize.plugin import FUNCTUALIZE_SETTINGS, Setting


def _catalog() -> tuple[Setting, ...]:
    return (
        Setting(
            "ui.theme",
            "enum",
            "UI theme",
            default="dark",
            choices=("dark", "light"),
        ),
        Setting("verbose", "bool", "Verbose", default="false"),
    )


class TestInstanceScopedCatalog:
    def test_no_catalog_means_no_rows(self) -> None:
        """There is no implicit func catalog to fall back to."""
        assert SettingsPanel()._settings == []

    def test_custom_catalog_replaces_it(self) -> None:
        panel = SettingsPanel(catalog=_catalog())
        assert panel._settings == ["ui.theme", "verbose"]

    def test_two_panels_coexist_with_different_catalogs(self) -> None:
        """The property that a module-global catalog made impossible."""
        func_panel = SettingsPanel(catalog=FUNCTUALIZE_SETTINGS.settings)
        other_panel = SettingsPanel(catalog=_catalog())

        assert other_panel._settings == ["ui.theme", "verbose"]
        assert func_panel._settings == [s.name for s in FUNCTUALIZE_SETTINGS.settings]
        assert set(func_panel._settings) & set(other_panel._settings) == set()

    def test_defaults_come_from_the_catalog(self) -> None:
        panel = SettingsPanel(catalog=_catalog())
        assert panel._values["ui.theme"] == "dark"
        assert panel._values["verbose"] == "false"

    def test_sources_start_at_default(self) -> None:
        panel = SettingsPanel(catalog=_catalog())
        assert set(panel._sources.values()) == {"default"}


class TestCatalogScopedLookups:
    def test_setting_lookup_uses_this_panels_catalog(self) -> None:
        panel = SettingsPanel(catalog=_catalog())
        assert panel._setting("ui.theme") is not None
        # A func setting is not in this panel's catalog.
        assert panel._setting("tui.theme") is None

    def test_validation_uses_this_panels_catalog(self) -> None:
        panel = SettingsPanel(catalog=_catalog())
        assert panel._validate("ui.theme", "dark").valid
        assert not panel._validate("ui.theme", "chartreuse").valid

    @pytest.mark.parametrize("value", ["true", "false"])
    def test_bool_setting_validates(self, value: str) -> None:
        panel = SettingsPanel(catalog=_catalog())
        assert panel._validate("verbose", value).valid
