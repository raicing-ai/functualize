"""C2.2 — `SettingsStore` is app-agnostic.

`tests/cli/test_func_settings_store.py` is the oracle for the other half of the
acceptance ("func's own settings resolution is byte-identical") — it is
unchanged and still passes. This file covers the new half: a *second* app gets
its own catalog, env prefix, TOML section prefix and global-config location, and
does not see func's values.

The three things being proved app-agnostic are exactly the three that used to be
literals inside the store: the `FUNCTUALIZE_` env prefix, the
`"tool.functualize" if path.name == "pyproject.toml"` branch, and the global
`config.toml` path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli.config import SettingsFileInfo
from functualize._cli.data.func_settings import (
    FUNC_SCHEMA,
    FUNC_SETTINGS,
    FuncSetting,
    SettingsStore,
)
from functualize._cli.data.settings_schema import SettingSchema
from functualize.plugin import AppSettingsSchema, Setting


def _deploytool_catalog() -> tuple[FuncSetting, ...]:
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
            schema=SettingSchema(
                name="verbose", type="bool", description="Verbose output"
            ),
            default="false",
        ),
    )


def _deploytool_schema() -> AppSettingsSchema:
    return AppSettingsSchema(
        settings=(
            Setting("ui.theme", "enum", "UI theme", default="dark"),
            Setting("verbose", "bool", "Verbose output", default="false"),
        ),
        env_prefix="DEPLOYTOOL",
        file_section_prefixes={"pyproject.toml": "tool.deploytool"},
    )


def _store(tmp_path: Path, values: dict, *, env: dict[str, str]) -> SettingsStore:
    layer = SettingsFileInfo(
        path=tmp_path / "pyproject.toml",
        kind="project",
        section_prefix="tool.deploytool",
        values=values,
    )
    global_layer = SettingsFileInfo(
        path=tmp_path / "global.toml", kind="global", section_prefix="", values={}
    )
    return SettingsStore(
        [layer, global_layer],
        env=env,
        catalog=_deploytool_catalog(),
        schema=_deploytool_schema(),
        app_name="deploytool",
    )


def _effective(store: SettingsStore) -> dict[str, str]:
    return store.effective_values()


class TestSecondAppEnvPrefix:
    def test_reads_its_own_env_prefix(self, tmp_path: Path) -> None:
        store = _store(tmp_path, {}, env={"DEPLOYTOOL_UI_THEME": "light"})
        assert _effective(store)["ui.theme"] == "light"

    def test_top_level_key_uses_bare_prefix(self, tmp_path: Path) -> None:
        store = _store(tmp_path, {}, env={"DEPLOYTOOL_VERBOSE": "true"})
        assert _effective(store)["verbose"] == "true"

    def test_ignores_functualize_env_vars(self, tmp_path: Path) -> None:
        """func's env namespace must not leak into a second app."""
        store = _store(
            tmp_path,
            {},
            env={"FUNCTUALIZE_UI_THEME": "light", "FUNCTUALIZE_VERBOSE": "true"},
        )
        effective = _effective(store)
        assert effective["ui.theme"] == "dark"  # its own default
        assert effective["verbose"] == "false"


class TestSecondAppCatalog:
    def test_does_not_resolve_func_settings(self, tmp_path: Path) -> None:
        """A second app sees only its own catalog — not func's."""
        store = _store(tmp_path, {}, env={})
        keys = set(_effective(store))
        assert keys == {"ui.theme", "verbose"}
        assert not keys & {s.name for s in FUNC_SETTINGS}

    def test_reads_values_from_its_own_toml_section(self, tmp_path: Path) -> None:
        store = _store(tmp_path, {"ui": {"theme": "light"}}, env={})
        assert _effective(store)["ui.theme"] == "light"


class TestSectionPrefixIsDeclaredNotBranched:
    """Replaces `"tool.functualize" if path.name == "pyproject.toml"`."""

    def test_second_app_nests_under_its_own_table(self, tmp_path: Path) -> None:
        store = _store(tmp_path, {}, env={})
        store.ensure_layer(tmp_path / "sub" / "pyproject.toml")
        layer = next(
            info
            for info in store.layers
            if info.path.name == "pyproject.toml" and info.path.parent.name == "sub"
        )
        assert layer.section_prefix == "tool.deploytool"

    def test_dedicated_file_has_no_prefix(self, tmp_path: Path) -> None:
        store = _store(tmp_path, {}, env={})
        store.ensure_layer(tmp_path / "deploytool.toml")
        layer = next(
            info for info in store.layers if info.path.name == "deploytool.toml"
        )
        assert layer.section_prefix == ""

    def test_func_still_nests_under_tool_functualize(self, tmp_path: Path) -> None:
        """The default path is unchanged — func's oracle behavior."""
        store = SettingsStore(
            [
                SettingsFileInfo(
                    path=tmp_path / "global.toml",
                    kind="global",
                    section_prefix="",
                    values={},
                )
            ],
            env={},
        )
        store.ensure_layer(tmp_path / "pyproject.toml")
        layer = next(
            info for info in store.layers if info.path.name == "pyproject.toml"
        )
        assert layer.section_prefix == "tool.functualize"


class TestGlobalPathNamespacing:
    def test_second_app_gets_its_own_global_file(self, tmp_path: Path) -> None:
        """No global layer supplied → the fallback is namespaced by app_name."""
        store = SettingsStore(
            [],
            env={},
            catalog=_deploytool_catalog(),
            schema=_deploytool_schema(),
            app_name="deploytool",
        )
        assert store.global_path.parent.name == "deploytool"

    def test_func_default_is_unchanged(self) -> None:
        store = SettingsStore([], env={})
        assert store.global_path.parent.name == "functualize"
        assert store.global_path.name == "config.toml"


class TestFuncDefaultsUntouched:
    """Every parameter defaults to func, so existing call sites are unaffected."""

    def test_store_constructed_without_new_kwargs_uses_func_catalog(self) -> None:
        store = SettingsStore([], env={})
        assert set(_effective(store)) == {s.name for s in FUNC_SETTINGS}

    def test_func_schema_matches_the_shipped_catalog(self) -> None:
        assert {s.name for s in FUNC_SCHEMA.settings} == {s.name for s in FUNC_SETTINGS}
        assert FUNC_SCHEMA.env_prefix == "FUNCTUALIZE"

    def test_func_settings_store_is_the_same_class(self) -> None:
        from functualize._cli.data.func_settings import FuncSettingsStore

        assert SettingsStore is FuncSettingsStore


@pytest.mark.parametrize(
    ("setting_name", "expected"),
    [("ui.theme", "DEPLOYTOOL_UI_THEME"), ("verbose", "DEPLOYTOOL_VERBOSE")],
)
def test_env_var_naming(setting_name: str, expected: str) -> None:
    schema = _deploytool_schema()
    setting = next(s for s in schema.settings if s.name == setting_name)
    assert schema.env_var_for(setting) == expected
