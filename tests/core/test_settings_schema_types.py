"""C2.1 — public `Setting` / `AppSettingsSchema` / `SettingsSources`.

The store refactor is C2.2; what is pinned here is that the new declaration is a
**faithful reconciliation** of the shipped `FuncSetting`, not a redesign that
quietly drops information.

The load-bearing test is `TestRoundTripAgainstShippedCatalog`: every one of
today's `FUNC_SETTINGS` entries must land in the same TOML location and resolve
from the same environment variable under the new types. If that holds, C2.2 can
swap the store's internals without moving a single user's config value.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli.config import SettingsFileInfo
from functualize._cli.data.func_settings import (
    FUNC_SETTINGS,
    env_var_for,
    section_for_file,
)
from functualize.plugin import AppSettingsSchema, Setting, SettingsSources


def _as_setting(func_setting: object) -> Setting:
    """Project a shipped `FuncSetting` onto the new `Setting`.

    This is the mapping C2.2 will apply for real; doing it here proves the new
    shape can carry everything the old one did.
    """
    schema = func_setting.schema  # type: ignore[attr-defined]
    return Setting(
        name=func_setting.name,  # type: ignore[attr-defined]
        type=schema.type,
        description=schema.description,
        default=func_setting.default,  # type: ignore[attr-defined]
        choices=tuple(schema.choices) if schema.choices else None,
        min_value=schema.min_value,
        max_value=schema.max_value,
        max_items=schema.max_items,
    )


@pytest.fixture
def shipped_schema() -> AppSettingsSchema:
    return AppSettingsSchema(settings=tuple(_as_setting(s) for s in FUNC_SETTINGS))


class TestDerivedSectionAndKey:
    """`section`/`key` survive the reshape — as derived properties."""

    @pytest.mark.parametrize("func_setting", FUNC_SETTINGS, ids=lambda s: s.name)
    def test_section_and_key_match_shipped(self, func_setting: object) -> None:
        setting = _as_setting(func_setting)
        assert setting.section == func_setting.section  # type: ignore[attr-defined]
        assert setting.key == func_setting.key  # type: ignore[attr-defined]

    def test_top_level_key_has_empty_section(self) -> None:
        assert Setting("dotenv", "bool", "x").section == ""
        assert Setting("dotenv", "bool", "x").key == "dotenv"

    def test_dotted_name_splits_on_the_last_dot(self) -> None:
        setting = Setting("tui.theme", "enum", "x")
        assert (setting.section, setting.key) == ("tui", "theme")

    def test_name_and_section_cannot_disagree(self) -> None:
        """Derivation is the point: section/key are not settable fields.

        The shipped `FuncSetting` stores name, section and key independently, so
        they can drift. Here they cannot: only `name` is a field.
        """
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(Setting)}
        assert "name" in field_names
        assert "section" not in field_names
        assert "key" not in field_names
        with pytest.raises(TypeError):
            Setting("tui.theme", "enum", "x", section="other")  # type: ignore[call-arg]


class TestRoundTripAgainstShippedCatalog:
    """Every shipped setting keeps its env var and its TOML location."""

    @pytest.mark.parametrize("func_setting", FUNC_SETTINGS, ids=lambda s: s.name)
    def test_env_var_identical(
        self, func_setting: object, shipped_schema: AppSettingsSchema
    ) -> None:
        setting = _as_setting(func_setting)
        assert shipped_schema.env_var_for(setting) == env_var_for(func_setting)  # type: ignore[arg-type]

    @pytest.mark.parametrize("file_name", ["pyproject.toml", ".functualize.toml"])
    @pytest.mark.parametrize("func_setting", FUNC_SETTINGS, ids=lambda s: s.name)
    def test_toml_section_identical(
        self,
        func_setting: object,
        file_name: str,
        shipped_schema: AppSettingsSchema,
    ) -> None:
        info = SettingsFileInfo(
            path=Path("/tmp") / file_name,
            kind="project",
            section_prefix="tool.functualize" if file_name == "pyproject.toml" else "",
            values={},
        )
        assert shipped_schema.section_in_file(
            _as_setting(func_setting), file_name
        ) == section_for_file(func_setting, info)  # type: ignore[arg-type]

    def test_catalog_is_fully_covered(self, shipped_schema: AppSettingsSchema) -> None:
        """Guard: the projection must not silently drop entries."""
        assert len(shipped_schema.settings) == len(FUNC_SETTINGS)
        assert {s.name for s in shipped_schema.settings} == {
            s.name for s in FUNC_SETTINGS
        }


class TestParameterization:
    """The three things that were hardcoded are now declared."""

    def test_env_prefix_is_parameterized(self) -> None:
        other = AppSettingsSchema(settings=(), env_prefix="DEPLOYTOOL")
        assert other.env_var_for(Setting("tui.theme", "enum", "x")) == (
            "DEPLOYTOOL_TUI_THEME"
        )
        assert other.env_var_for(Setting("dotenv", "bool", "x")) == "DEPLOYTOOL_DOTENV"

    def test_file_section_prefix_is_data_not_a_filename_branch(self) -> None:
        """Replaces `"tool.functualize" if path.name == "pyproject.toml"`."""
        other = AppSettingsSchema(
            settings=(),
            file_section_prefixes={"pyproject.toml": "tool.deploytool"},
        )
        setting = Setting("ui.theme", "enum", "x")
        assert other.section_in_file(setting, "pyproject.toml") == (
            "tool.deploytool.ui"
        )
        # A dedicated file has no prefix, so the bare section stands.
        assert other.section_in_file(setting, "deploytool.toml") == "ui"

    def test_func_defaults_reproduce_todays_behavior(self) -> None:
        schema = AppSettingsSchema(settings=())
        assert schema.env_prefix == "FUNCTUALIZE"
        assert schema.section_prefix_for("pyproject.toml") == "tool.functualize"
        assert schema.section_prefix_for(".functualize.toml") == ""

    def test_sources_declare_the_upward_walk(self) -> None:
        sources = SettingsSources()
        assert sources.global_file_name == "config.toml"
        assert "pyproject.toml" in sources.project_file_names
        assert sources.env is True


class TestFutureFields:
    """`cli_flag` / `phase` exist but nothing consumes them yet (C3.1 / C3.2)."""

    def test_default_to_none(self) -> None:
        setting = Setting("tui.theme", "enum", "x")
        assert setting.cli_flag is None
        assert setting.phase is None

    def test_can_be_declared(self) -> None:
        setting = Setting(
            "log_level", "str", "Logging level", cli_flag="--log-level", phase="early"
        )
        assert setting.cli_flag == "--log-level"
        assert setting.phase == "early"

    def test_no_shipped_setting_declares_them_yet(self) -> None:
        """Guard so C3 starts from a known-empty baseline."""
        projected = [_as_setting(s) for s in FUNC_SETTINGS]
        assert all(s.cli_flag is None and s.phase is None for s in projected)


class TestPublicHome:
    def test_importable_from_functualize_plugin(self) -> None:
        import functualize.plugin as plugin

        for name in ("Setting", "AppSettingsSchema", "SettingsSources"):
            assert name in plugin.__all__

    def test_types_layer_stays_import_free(self) -> None:
        import inspect

        import functualize._types.settings as mod

        source = inspect.getsource(mod)
        for forbidden in (
            "from functualize._app",
            "from functualize._cli",
            "from functualize._engine",
            "from functualize._discovery",
        ):
            assert forbidden not in source
