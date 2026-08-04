"""C2.3 — the settings panel's catalog is instance state, not a module global.

Before, the panel read `SETTINGS_ORDER` / `DEFAULT_VALUES` at import time, so
every panel in a process showed func's settings and nothing else. A second app
(C2/C3) needs its own.
"""

from __future__ import annotations

import pytest

from functualize._cli.data.func_settings import FUNC_SETTINGS, FuncSetting
from functualize._cli.data.settings_schema import SettingSchema
from functualize._cli.tui.settings_panel import SettingsPanel


def _catalog() -> tuple[FuncSetting, ...]:
    return (
        FuncSetting(
            name="ui.theme",
            section="ui",
            key="theme",
            schema=SettingSchema(
                name="ui.theme",
                type="enum",
                description="UI theme",
                choices=["dark", "light"],
            ),
            default="dark",
        ),
        FuncSetting(
            name="verbose",
            section="",
            key="verbose",
            schema=SettingSchema(name="verbose", type="bool", description="Verbose"),
            default="false",
        ),
    )


class TestInstanceScopedCatalog:
    def test_default_is_funcs_catalog(self) -> None:
        panel = SettingsPanel()
        assert panel._settings == [s.name for s in FUNC_SETTINGS]

    def test_custom_catalog_replaces_it(self) -> None:
        panel = SettingsPanel(catalog=_catalog())
        assert panel._settings == ["ui.theme", "verbose"]

    def test_two_panels_coexist_with_different_catalogs(self) -> None:
        """The property that a module-global catalog made impossible."""
        func_panel = SettingsPanel()
        other_panel = SettingsPanel(catalog=_catalog())

        assert other_panel._settings == ["ui.theme", "verbose"]
        assert func_panel._settings == [s.name for s in FUNC_SETTINGS]
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
