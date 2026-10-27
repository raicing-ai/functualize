"""A second app's settings through the same store.

The store owns no literals about the app it serves: the env prefix, the
`pyproject.toml` table and the global file name come from the
`AppSettingsSchema` handed in, and the values come from `resolve_settings`
over that declaration. These tests are the app-agnostic half;
`tests/cli/test_func_settings_store.py` is func's own.

Nothing here reads a file to answer a question about a *path*: a prospective
layer knows its section prefix because the schema declares it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from functualize._cli.data.func_settings import FuncSettingsStore
from functualize.plugin import AppSettingsSchema, Setting, SettingsSources

DEPLOYTOOL = AppSettingsSchema(
    settings=(
        Setting(
            "ui.theme", "enum", "UI theme", default="dark", choices=("dark", "light")
        ),
        Setting("verbose", "bool", "Verbose output", default="false"),
    ),
    env_prefix="DEPLOYTOOL",
    sources=SettingsSources(
        global_file_name="deploytool.toml",
        project_file_names=("pyproject.toml", ".deploytool.toml"),
    ),
    file_section_prefixes={"pyproject.toml": "tool.deploytool"},
)


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def _store(project: Path, **kwargs: object) -> FuncSettingsStore:
    kwargs.setdefault("env", {})
    return FuncSettingsStore(DEPLOYTOOL, cwd=project, app_name="deploytool", **kwargs)  # type: ignore[arg-type]


class TestSectionPrefixIsDeclaredNotBranched:
    def test_pyproject_nests_under_the_apps_own_table(
        self, isolated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`ensure_layer` answers the prefix with no read at all."""
        target = isolated / "sub" / "pyproject.toml"
        store = _store(isolated)
        store.effective_values()
        read: list[Path] = []
        real_read_text = Path.read_text

        def _record(self: Path, *args: object, **kwargs: object) -> str:
            read.append(self)
            return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", _record)

        store.ensure_layer(target)

        layer = next(entry for entry in store.layers if entry.path == target)
        assert layer.section_prefix == "tool.deploytool"
        assert layer.text == ""
        assert read == []

    def test_dedicated_file_has_no_prefix(self, isolated: Path) -> None:
        target = isolated / ".deploytool.toml"
        store = _store(isolated)

        store.ensure_layer(target)

        assert (
            next(entry for entry in store.layers if entry.path == target).section_prefix
            == ""
        )

    def test_save_lands_under_the_declared_table(self, isolated: Path) -> None:
        target = isolated / "pyproject.toml"
        store = _store(isolated)

        store.write(target, {"ui.theme": "light"})

        assert (
            tomllib.loads(target.read_text())["tool"]["deploytool"]["ui"]["theme"]
            == "light"
        )

    def test_func_still_nests_under_tool_functualize(self, isolated: Path) -> None:
        """The default declaration is unchanged — func's own table name."""
        store = FuncSettingsStore(cwd=isolated, env={})

        store.ensure_layer(isolated / "pyproject.toml")

        layer = next(
            entry for entry in store.layers if entry.path.name == "pyproject.toml"
        )
        assert layer.section_prefix == "tool.functualize"


class TestGlobalPathNamespacing:
    def test_second_app_gets_its_own_global_file(self, isolated: Path) -> None:
        store = _store(isolated)

        assert store.global_path.parent.name == "deploytool"
        assert store.global_path.name == "deploytool.toml"

    def test_func_default_is_unchanged(self, isolated: Path) -> None:
        store = FuncSettingsStore(cwd=isolated, env={})

        assert store.global_path.parent.name == "functualize"
        assert store.global_path.name == "config.toml"

    def test_global_file_is_where_a_global_save_lands(self, isolated: Path) -> None:
        store = _store(isolated)

        store.write(store.global_path, {"ui.theme": "light"})

        assert tomllib.loads(store.global_path.read_text())["ui"]["theme"] == "light"
        assert store.effective_values()["ui.theme"] == "light"
        assert store.source_labels()["ui.theme"] == "global config"


class TestSecondAppValues:
    def test_reads_its_own_files(self, isolated: Path) -> None:
        (isolated / ".deploytool.toml").write_text('[ui]\ntheme = "light"\n')

        assert _store(isolated).effective_values()["ui.theme"] == "light"

    def test_env_uses_the_declared_prefix(self, isolated: Path) -> None:
        store = _store(isolated, env={"DEPLOYTOOL_UI_THEME": "light"})

        assert store.effective_values()["ui.theme"] == "light"
        assert store.source_labels()["ui.theme"] == "DEPLOYTOOL_UI_THEME"

    def test_env_var_naming(self) -> None:
        theme = next(s for s in DEPLOYTOOL.settings if s.name == "ui.theme")

        assert DEPLOYTOOL.env_var_for(theme) == "DEPLOYTOOL_UI_THEME"

    def test_discover_keeps_the_schema(self, isolated: Path) -> None:
        store = FuncSettingsStore.discover(
            isolated, env={}, schema=DEPLOYTOOL, app_name="deploytool"
        )

        assert store.schema is DEPLOYTOOL
        assert store.effective_values()["ui.theme"] == "dark"


class TestFuncDefaultsUntouched:
    def test_func_declaration_is_the_default(self, isolated: Path) -> None:
        from functualize.plugin import FUNCTUALIZE_SETTINGS

        store = FuncSettingsStore(cwd=isolated, env={})

        assert store.schema is FUNCTUALIZE_SETTINGS
        assert "FUNCTUALIZE_TUI_THEME" in {
            store.schema.env_var_for(s) for s in store.schema.settings
        }

    def test_func_does_not_see_a_second_apps_file(self, isolated: Path) -> None:
        (isolated / ".deploytool.toml").write_text('[ui]\ntheme = "light"\n')

        store = FuncSettingsStore(cwd=isolated, env={})

        assert ".deploytool.toml" not in {layer.path.name for layer in store.layers}
        assert store.effective_values()["tui.theme"] == "transparent"

    def test_deploytool_does_not_see_funcs_values(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text('[tui]\ntheme = "dark"\n')

        values = _store(isolated).effective_values()

        assert "tui.theme" not in values
        assert set(values) == {"ui.theme", "verbose"}
