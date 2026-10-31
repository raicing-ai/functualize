"""Tests for FuncSettingsStore — `func`'s settings over the real config files.

The store owns no precedence of its own: `resolve_settings` decides every
value and its provenance, and the layers it returns are what the store
displays and writes. These tests pin that seam — a snapshot that wins, a
chain that shows it, a prospective layer for a file that does not exist yet,
and a save that hands the layer's text to the writer instead of reading the
file itself.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from functualize._cli.data.func_settings import FuncSettingsStore, setting_schema
from functualize._cli.data.settings_schema import validate_against
from functualize.plugin import FUNCTUALIZE_SETTINGS, resolve_settings


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


def _store(project: Path, **kwargs: object) -> FuncSettingsStore:
    kwargs.setdefault("env", {})
    return FuncSettingsStore(cwd=project, **kwargs)  # type: ignore[arg-type]


def _resolved(store: FuncSettingsStore, name: str):
    return next(k for k in store.resolve() if k.name == name)


def _write_global(project: Path, text: str) -> Path:
    path = _global_file(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class TestLayers:
    def test_global_layer_present_even_when_missing(self, isolated: Path) -> None:
        """The global path is where a "save globally" goes — needed either way."""
        layers = _store(isolated).layers

        assert layers[-1].kind == "global"
        assert layers[-1].path == _global_file(isolated)
        assert layers[-1].exists is False
        assert layers[-1].values == {}
        assert layers[-1].text == ""

    def test_project_layers_nearest_first(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text('[tui]\ntheme = "near"\n')
        sub = isolated / "sub"
        sub.mkdir()
        (sub / ".functualize.toml").write_text('[tui]\ntheme = "nearest"\n')

        project = [layer for layer in _store(sub).layers if layer.kind == "project"]

        assert [p.path.parent.name for p in project] == ["sub", "project"]
        assert project[0].values["tui"]["theme"] == "nearest"

    def test_pyproject_carries_the_tool_prefix(self, isolated: Path) -> None:
        (isolated / "pyproject.toml").write_text(
            '[tool.functualize]\ndotenv = true\n\n[tool.functualize.tui]\ntheme = "x"\n'
        )

        project = [
            layer for layer in _store(isolated).layers if layer.kind == "project"
        ]

        assert project[0].section_prefix == "tool.functualize"
        # Values are already stripped of the prefix.
        assert project[0].values["dotenv"] is True
        assert project[0].values["tui"]["theme"] == "x"

    def test_layer_carries_its_original_text(self, isolated: Path) -> None:
        """A save needs the file as it was read, so the layer keeps it."""
        source = '# keep me\n[tui]\ntheme = "dark"\n'
        (isolated / ".functualize.toml").write_text(source)

        layer = next(
            entry for entry in _store(isolated).layers if entry.kind == "project"
        )

        assert layer.text == source

    def test_root_true_stops_the_walk(self, isolated: Path) -> None:
        """`root = true` in a project file stops the upward search."""
        _write_global(isolated, '[tui]\ntheme = "global"\n')
        (isolated / ".functualize.toml").write_text("[functualize]\nroot = true\n")
        sub = isolated / "sub"
        sub.mkdir()

        project = [layer for layer in _store(sub).layers if layer.kind == "project"]

        assert [layer.path for layer in project] == [isolated / ".functualize.toml"]


class TestSnapshotIsTheAnswer:
    def test_default_when_nothing_sets_it(self, isolated: Path) -> None:
        store = _store(isolated)

        assert store.effective_values()["tui.theme"] == "transparent"
        assert store.source_labels()["tui.theme"] == "default"

    def test_global_beats_default(self, isolated: Path) -> None:
        _write_global(isolated, '[tui]\ntheme = "dark"\n')

        store = _store(isolated)

        assert store.effective_values()["tui.theme"] == "dark"
        assert store.source_labels()["tui.theme"] == "global config"
        assert _resolved(store, "tui.theme").winning.label == "global config"

    def test_project_beats_global(self, isolated: Path) -> None:
        _write_global(isolated, '[tui]\ntheme = "dark"\n')
        (isolated / ".functualize.toml").write_text('[tui]\ntheme = "light"\n')

        store = _store(isolated)

        assert store.effective_values()["tui.theme"] == "light"
        assert store.source_labels()["tui.theme"] == ".functualize.toml"

    def test_env_beats_everything(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text('[tui]\ntheme = "light"\n')

        store = _store(isolated, env={"FUNCTUALIZE_TUI_THEME": "fromenv"})

        assert store.effective_values()["tui.theme"] == "fromenv"
        assert store.source_labels()["tui.theme"] == "FUNCTUALIZE_TUI_THEME"
        assert _resolved(store, "tui.theme").winning.label == "FUNCTUALIZE_TUI_THEME"

    def test_top_level_setting_resolves(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text("dotenv = true\n")

        assert _store(isolated).effective_values()["dotenv"] == "true"

    def test_env_names_come_from_the_declaration(self) -> None:
        def env_for(name: str) -> str:
            setting = next(s for s in FUNCTUALIZE_SETTINGS.settings if s.name == name)
            return FUNCTUALIZE_SETTINGS.env_var_for(setting)

        assert env_for("dotenv") == "FUNCTUALIZE_DOTENV"
        assert env_for("tui.theme") == "FUNCTUALIZE_TUI_THEME"
        assert env_for("cli.output") == "FUNCTUALIZE_CLI_OUTPUT"

    def test_hand_edited_value_is_shown_not_dropped(self, isolated: Path) -> None:
        """One authority: an out-of-choice value is what the app resolves.

        The store used to drop an invalid file value from its chain and fall
        back to the next layer, which made the TUI disagree with the rest of
        the tool about which file won. The snapshot decides now; the panel
        still refuses to *enter* an invalid value.
        """
        _write_global(isolated, '[cli]\noutput = "json"\n')
        (isolated / ".functualize.toml").write_text('[cli]\noutput = "sparkly"\n')

        store = _store(isolated)

        assert store.effective_values()["cli.output"] == "sparkly"
        assert store.source_labels()["cli.output"] == ".functualize.toml"

    def test_settings_without_defaults_resolve_to_unset(self, isolated: Path) -> None:
        key = _resolved(_store(isolated), "discovery.require_file_prefix")

        assert key.winning is None
        assert key.effective_value == ""

    def test_passed_snapshot_is_used_without_reading_again(
        self, isolated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The running app's boot snapshot is the answer; no second resolution."""
        snapshot = resolve_settings(FUNCTUALIZE_SETTINGS, isolated, env={})
        store = FuncSettingsStore(FUNCTUALIZE_SETTINGS, snapshot=snapshot)

        def _boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("a passed snapshot must not be re-resolved")

        monkeypatch.setattr(
            "functualize._config.settings_resolution.resolve_settings", _boom
        )

        assert store.effective_values()["tui.theme"] == "transparent"
        assert store.layers == list(snapshot.layers)


class TestDeclaredSettings:
    def test_surface_filter_matches_the_declaration(self, isolated: Path) -> None:
        store = _store(isolated)

        tui = store.declared_settings(surface="tui")

        assert [s.name for s in tui] == [
            "tui.theme",
            "tui.display_auto_switch",
            "tui.default_surface",
            "tui.show_session_stamp",
            "tui.history_retention",
            "tui.signature_enabled",
            "tui.default_override_target",
        ]
        assert len(store.declared_settings()) == len(FUNCTUALIZE_SETTINGS.settings)

    def test_setting_schema_carries_bounds(self) -> None:
        setting = next(
            s
            for s in FUNCTUALIZE_SETTINGS.settings
            if s.name == "tui.history_retention"
        )

        assert not validate_against(setting_schema(setting), "0").valid
        assert validate_against(setting_schema(setting), "100").valid


class TestProspectiveLayer:
    def test_ensure_layer_adds_without_reading(
        self, isolated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = isolated / "pyproject.toml"
        store = _store(isolated)
        store.effective_values()  # resolve once, so the walk is done
        read: list[Path] = []
        real_read_text = Path.read_text

        def _record(self: Path, *args: object, **kwargs: object) -> str:
            read.append(self)
            return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", _record)

        store.ensure_layer(target)

        assert target not in read

        layer = next(entry for entry in store.layers if entry.path == target)
        assert layer.values == {}
        assert layer.text == ""
        assert layer.section_prefix == "tool.functualize"
        assert store.effective_values()["tui.theme"] == "transparent"

    def test_ensure_layer_is_idempotent(self, isolated: Path) -> None:
        target = isolated / ".functualize.toml"
        store = _store(isolated)

        store.ensure_layer(target)
        store.ensure_layer(target)

        assert [layer.path for layer in store.layers].count(target) == 1

    def test_known_layer_is_not_duplicated(self, isolated: Path) -> None:
        target = isolated / ".functualize.toml"
        target.write_text('[tui]\ntheme = "dark"\n')
        store = _store(isolated)

        store.ensure_layer(target)

        assert [layer.path for layer in store.layers].count(target) == 1
        assert store.effective_values()["tui.theme"] == "dark"


class TestWrite:
    def test_cross_section_edits_group_correctly(self, isolated: Path) -> None:
        """One save can span [tui], [cli], and the top level."""
        target = isolated / ".functualize.toml"
        store = _store(isolated)

        store.write(
            target,
            {"tui.theme": "dark", "cli.output": "json", "dotenv": "true"},
        )

        data = tomllib.loads(target.read_text())
        assert data["tui"]["theme"] == "dark"
        assert data["cli"]["output"] == "json"
        assert data["dotenv"] is True  # typed, not "true"

    def test_save_is_one_atomic_write(
        self, isolated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multiple sections land in a single `os.replace`."""
        import os

        target = isolated / ".functualize.toml"
        store = _store(isolated)
        replaced: list[str] = []
        real_replace = os.replace

        def _counting(src: str, dst: str) -> None:
            replaced.append(dst)
            real_replace(src, dst)

        monkeypatch.setattr(os, "replace", _counting)

        store.write(target, {"tui.theme": "dark", "cli.output": "json"})

        assert replaced == [str(target)]

    def test_typed_literals(self, isolated: Path) -> None:
        target = isolated / ".functualize.toml"
        store = _store(isolated)

        store.write(
            target,
            {"tui.history_retention": "20", "tui.show_session_stamp": "false"},
        )

        data = tomllib.loads(target.read_text())
        assert data["tui"]["history_retention"] == 20
        assert data["tui"]["show_session_stamp"] is False

    def test_pyproject_uses_the_declared_prefix(self, isolated: Path) -> None:
        target = isolated / "pyproject.toml"
        store = _store(isolated)

        store.write(target, {"tui.theme": "dark"})

        data = tomllib.loads(target.read_text())
        assert data["tool"]["functualize"]["tui"]["theme"] == "dark"

    def test_preserves_unrelated_toml_and_comments(self, isolated: Path) -> None:
        target = isolated / "pyproject.toml"
        target.write_text(
            "# project metadata\n"
            "[project]\n"
            'name = "demo"\n'
            "\n"
            "[tool.functualize.tui]\n"
            'theme = "light"  # picked in 2024\n'
        )
        store = _store(isolated)

        store.write(target, {"tui.theme": "dark"})

        text = target.read_text()
        assert "# project metadata" in text
        assert 'name = "demo"' in text
        assert 'theme = "dark"' in text
        data = tomllib.loads(text)
        assert data["project"]["name"] == "demo"
        assert data["tool"]["functualize"]["tui"]["theme"] == "dark"

    def test_creates_missing_file(self, isolated: Path) -> None:
        target = isolated / "sub" / ".functualize.toml"
        store = _store(isolated)

        store.write(target, {"tui.theme": "dark"})

        assert tomllib.loads(target.read_text())["tui"]["theme"] == "dark"

    def test_removal(self, isolated: Path) -> None:
        target = isolated / ".functualize.toml"
        target.write_text('[tui]\ntheme = "dark"\nhistory_retention = 5\n')
        store = _store(isolated)

        store.write(target, {}, {"tui.history_retention"})

        data = tomllib.loads(target.read_text())
        assert data["tui"]["theme"] == "dark"
        assert "history_retention" not in data["tui"]

    def test_unknown_setting_raises(self, isolated: Path) -> None:
        with pytest.raises(ValueError, match="Unknown setting"):
            _store(isolated).write(isolated / ".functualize.toml", {"nope.key": "x"})

    def test_invalid_value_raises(self, isolated: Path) -> None:
        target = isolated / ".functualize.toml"

        with pytest.raises(ValueError, match="Invalid value"):
            _store(isolated).write(target, {"cli.output": "sparkly"})

        assert not target.exists()

    def test_refreshes_the_snapshot_after_saving(self, isolated: Path) -> None:
        target = isolated / ".functualize.toml"
        store = _store(isolated)
        assert store.effective_values()["tui.theme"] == "transparent"

        store.write(target, {"tui.theme": "dark"})

        assert store.effective_values()["tui.theme"] == "dark"
        assert store.source_labels()["tui.theme"] == ".functualize.toml"

    def test_writer_applies_the_text_it_is_given(self, isolated: Path) -> None:
        """The writer must not re-read the file it is rewriting.

        The text on disk deliberately differs from the text handed over: if
        the writer opened the path, the unrelated section would survive. It
        does not, because the save is rendered from the layer's text.
        """
        from functualize._cli.data.toml_writer import SectionEdits, write_toml_sections

        target = isolated / ".functualize.toml"
        target.write_text('[tui]\ntheme = "onDisk"\n\n[extra]\nkeep = true\n')

        write_toml_sections(
            target,
            '[tui]\ntheme = "old"\n',
            {"tui": SectionEdits(edits={"theme": "new"})},
        )

        text = target.read_text()
        assert 'theme = "new"' in text
        assert "[extra]" not in text


class TestCliOverride:
    def test_override_wins_and_labels_the_flag(self, isolated: Path) -> None:
        _write_global(isolated, '[tui]\ntheme = "dark"\n')
        store = _store(isolated)

        store.set_cli_override("tui.theme", "flagtheme", flag="--theme")

        assert store.effective_values()["tui.theme"] == "flagtheme"
        assert store.source_labels()["tui.theme"] == "--theme"
        assert _resolved(store, "tui.theme").winning.precedence == 100

    def test_construction_and_override_read_nothing(
        self, isolated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resolution is lazy: rows and flags alone must not touch a file."""
        read: list[Path] = []
        real_read_text = Path.read_text

        def _record(self: Path, *args: object, **kwargs: object) -> str:
            read.append(self)
            return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", _record)

        store = _store(isolated)
        store.set_cli_override("tui.theme", "x", flag="--theme")

        assert read == []
