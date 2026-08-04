"""Tests for FuncSettingsStore — `func`'s settings over the real config files.

Replaces the deleted TuiSettingsStore tests. The old store resolved a
parallel ``functualize.toml`` / ``settings.toml`` pair that nothing else in
`func` read — a user could configure the TUI in a file the rest of the tool
ignored. These tests pin the new contract: the chain runs over the same
files ``resolve_cli_config`` merges (global ``config.toml``, project
``.functualize.toml`` / ``pyproject.toml [tool.functualize]``), plus
``FUNCTUALIZE_*`` env.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from functualize._cli.config import resolve_cli_config_layers
from functualize._cli.data.func_settings import (
    FUNC_SETTINGS,
    FuncSettingsStore,
    env_var_for,
    func_setting,
)


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp home + cwd so no real config leaks in."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def _global_file(project: Path) -> Path:
    return project.parent / "xdg" / "functualize" / "config.toml"


def _resolved(store: FuncSettingsStore, name: str):
    return next(k for k in store.resolve() if k.name == name)


class TestResolveCliConfigLayers:
    def test_global_layer_present_even_when_missing(self, isolated: Path) -> None:
        """The global path is where a "save globally" goes — needed either way."""
        layers = resolve_cli_config_layers(isolated)

        assert layers[-1].kind == "global"
        assert layers[-1].path == _global_file(isolated)
        assert layers[-1].exists is False
        assert layers[-1].values == {}

    def test_project_layers_nearest_first(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text('[tui]\ntheme = "near"\n')
        sub = isolated / "sub"
        sub.mkdir()
        (sub / ".functualize.toml").write_text('[tui]\ntheme = "nearest"\n')

        layers = resolve_cli_config_layers(sub)
        project = [layer for layer in layers if layer.kind == "project"]

        assert [p.path.parent.name for p in project] == ["sub", "project"]
        assert project[0].values["tui"]["theme"] == "nearest"

    def test_pyproject_carries_the_tool_prefix(self, isolated: Path) -> None:
        (isolated / "pyproject.toml").write_text(
            '[tool.functualize]\ndotenv = true\n\n[tool.functualize.tui]\ntheme = "x"\n'
        )

        layers = resolve_cli_config_layers(isolated)
        project = [layer for layer in layers if layer.kind == "project"]

        assert project[0].section_prefix == "tool.functualize"
        # Values are already stripped of the prefix.
        assert project[0].values["dotenv"] is True
        assert project[0].values["tui"]["theme"] == "x"


class TestChainPrecedence:
    def test_default_when_nothing_sets_it(self, isolated: Path) -> None:
        store = FuncSettingsStore.discover(isolated, env={})

        key = _resolved(store, "tui.theme")
        assert key.effective_value == "transparent"
        assert key.winning.label == "default"

    def test_global_beats_default(self, isolated: Path) -> None:
        global_file = _global_file(isolated)
        global_file.parent.mkdir(parents=True)
        global_file.write_text('[tui]\ntheme = "dark"\n')

        store = FuncSettingsStore.discover(isolated, env={})
        key = _resolved(store, "tui.theme")

        assert key.effective_value == "dark"
        assert key.winning.label == "global config"

    def test_project_beats_global(self, isolated: Path) -> None:
        global_file = _global_file(isolated)
        global_file.parent.mkdir(parents=True)
        global_file.write_text('[tui]\ntheme = "dark"\n')
        (isolated / ".functualize.toml").write_text('[tui]\ntheme = "light"\n')

        store = FuncSettingsStore.discover(isolated, env={})

        assert _resolved(store, "tui.theme").effective_value == "light"

    def test_env_beats_everything(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text('[tui]\ntheme = "light"\n')

        store = FuncSettingsStore.discover(
            isolated, env={"FUNCTUALIZE_TUI_THEME": "fromenv"}
        )
        key = _resolved(store, "tui.theme")

        assert key.effective_value == "fromenv"
        assert key.winning.label == "FUNCTUALIZE_TUI_THEME"

    def test_top_level_setting_resolves(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text("dotenv = true\n")

        store = FuncSettingsStore.discover(isolated, env={})

        assert _resolved(store, "dotenv").effective_value == "true"

    def test_top_level_env_var_has_no_section_segment(self, isolated: Path) -> None:
        assert env_var_for(func_setting("dotenv")) == "FUNCTUALIZE_DOTENV"
        assert env_var_for(func_setting("tui.theme")) == "FUNCTUALIZE_TUI_THEME"
        assert env_var_for(func_setting("cli.output")) == "FUNCTUALIZE_CLI_OUTPUT"

    def test_invalid_value_is_dropped_not_fatal(self, isolated: Path) -> None:
        """A hand-edited file with a bad value falls through to the next layer."""
        (isolated / ".functualize.toml").write_text(
            '[cli]\noutput = "sparkly"\n'  # not one of rich/plain/json
        )
        global_file = _global_file(isolated)
        global_file.parent.mkdir(parents=True)
        global_file.write_text('[cli]\noutput = "json"\n')

        store = FuncSettingsStore.discover(isolated, env={})

        assert _resolved(store, "cli.output").effective_value == "json"

    def test_settings_without_defaults_resolve_to_unset(self, isolated: Path) -> None:
        store = FuncSettingsStore.discover(isolated, env={})
        key = _resolved(store, "discovery.require_file_prefix")

        assert key.winning is None
        assert key.effective_value == ""


class TestWrite:
    def test_cross_section_edits_group_correctly(self, isolated: Path) -> None:
        """One save can span [tui], [cli], and the top level."""
        target = isolated / ".functualize.toml"
        store = FuncSettingsStore.discover(isolated, env={})

        store.write(
            target,
            {"tui.theme": "dark", "cli.output": "json", "dotenv": "true"},
        )

        data = tomllib.loads(target.read_text())
        assert data["tui"]["theme"] == "dark"
        assert data["cli"]["output"] == "json"
        assert data["dotenv"] is True  # typed, not "true"

    def test_typed_literals(self, isolated: Path) -> None:
        target = isolated / ".functualize.toml"
        store = FuncSettingsStore.discover(isolated, env={})

        store.write(target, {"tui.history_retention": "250"})

        assert tomllib.loads(target.read_text())["tui"]["history_retention"] == 250

    def test_pyproject_write_nests_under_tool(self, isolated: Path) -> None:
        target = isolated / "pyproject.toml"
        target.write_text('[project]\nname = "demo"\n')
        store = FuncSettingsStore.discover(isolated, env={})

        store.write(target, {"tui.theme": "dark", "dotenv": "true"})

        data = tomllib.loads(target.read_text())
        assert data["tool"]["functualize"]["tui"]["theme"] == "dark"
        assert data["tool"]["functualize"]["dotenv"] is True
        assert data["project"]["name"] == "demo"  # untouched

    def test_write_refreshes_the_store(self, isolated: Path) -> None:
        """A Detail view that re-resolves right after a save must see it."""
        target = isolated / ".functualize.toml"
        target.write_text('[tui]\ntheme = "light"\n')
        store = FuncSettingsStore.discover(isolated, env={})

        store.write(target, {"tui.theme": "dark"})

        assert _resolved(store, "tui.theme").effective_value == "dark"

    def test_invalid_edit_raises(self, isolated: Path) -> None:
        store = FuncSettingsStore.discover(isolated, env={})
        with pytest.raises(ValueError, match="Invalid value"):
            store.write(isolated / ".functualize.toml", {"cli.output": "sparkly"})

    def test_unknown_setting_raises(self, isolated: Path) -> None:
        store = FuncSettingsStore.discover(isolated, env={})
        with pytest.raises(ValueError, match="Unknown setting"):
            store.write(isolated / ".functualize.toml", {"nope.nope": "x"})


class TestDefinedSettings:
    def test_reports_which_settings_a_file_defines(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text(
            'dotenv = true\n\n[tui]\ntheme = "dark"\n\n[cli]\noutput = "plain"\n'
        )

        store = FuncSettingsStore.discover(isolated, env={})
        project = next(info for info in store.layers if info.kind == "project")

        assert set(store.defined_settings(project)) == {
            "dotenv",
            "tui.theme",
            "cli.output",
        }


class TestCatalog:
    def test_catalog_covers_the_recognized_config_surface(self) -> None:
        """Every recognized section key appears in the catalog, and vice versa.

        This is the drift-catcher between `_cli/config.py`'s recognized keys
        and the Settings panel's rows.
        """
        from functualize._cli.config import (
            _RECOGNIZED_KEYS,
            _RECOGNIZED_TOP_LEVEL_KEYS,
        )

        catalog_by_section: dict[str, set[str]] = {}
        for setting in FUNC_SETTINGS:
            catalog_by_section.setdefault(setting.section, set()).add(setting.key)

        for section in ("discovery", "cli", "tui"):
            assert catalog_by_section[section] == set(_RECOGNIZED_KEYS[section]), (
                f"[{section}] drifted between catalog and _RECOGNIZED_KEYS"
            )

        # Top level: jobs_directories and extra_directories are recognized in
        # config parsing but not offered as settings rows (jobs_directories is
        # documented-inert; extra_directories lives under [discovery] here).
        assert catalog_by_section[""] <= set(_RECOGNIZED_TOP_LEVEL_KEYS)


# --- tui.default_surface (supersedes the inert tui.execution_mode) ----------


class TestDefaultSurfaceSetting:
    """The tui.default_surface catalog entry and its env-var mapping."""

    def test_default_surface_in_catalog(self) -> None:
        setting = func_setting("tui.default_surface")
        assert setting is not None
        assert setting.section == "tui"
        assert setting.key == "default_surface"
        assert setting.default == "panel"
        assert setting.schema.choices == ["panel", "stdout"]

    def test_execution_mode_removed(self) -> None:
        # The superseded inert setting is gone from the catalog.
        assert func_setting("tui.execution_mode") is None

    def test_default_surface_env_var(self) -> None:
        setting = func_setting("tui.default_surface")
        assert setting is not None
        assert env_var_for(setting) == "FUNCTUALIZE_TUI_DEFAULT_SURFACE"
