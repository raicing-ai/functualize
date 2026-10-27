from __future__ import annotations

from pathlib import Path

from functualize._config.settings_layers import settings_layers
from functualize._types.functualize_settings import FUNCTUALIZE_SETTINGS


def test_root_stops_project_walk_and_global_is_last(tmp_path: Path) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "config.toml").write_text('[cli]\noutput = "plain"\n')
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    (parent / ".functualize.toml").write_text('[cli]\noutput = "json"\n')
    (child / "pyproject.toml").write_text("[tool.functualize]\nroot = true\n")

    layers = settings_layers(FUNCTUALIZE_SETTINGS, child, global_dir=global_dir)

    assert tuple(layer.path for layer in layers) == (
        child / "pyproject.toml",
        global_dir / "config.toml",
    )
    assert tuple(layer.kind for layer in layers) == ("project", "global")
    assert layers[0].section_prefix == "tool.functualize"
    assert layers[0].values == {"root": True}
    assert layers[1].values == {"cli": {"output": "plain"}}


def test_one_candidate_per_directory_and_absent_global(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[tool.other]\nvalue = 1\n")
    (project / ".functualize.toml").write_text('[cli]\noutput = "json"\n')
    global_dir = tmp_path / "global"
    layers = settings_layers(FUNCTUALIZE_SETTINGS, project, global_dir=global_dir)
    assert layers[0].path == project / ".functualize.toml"
    assert layers[-1].path == global_dir / "config.toml"
    assert layers[-1].exists is False


def test_layer_carries_the_text_it_parsed(tmp_path: Path) -> None:
    """A save rewrites the file from the layer, so the layer keeps the text."""
    project = tmp_path / "project"
    project.mkdir()
    text = '# comment\n[cli]\noutput = "json"\n'
    (project / ".functualize.toml").write_text(text)

    (layer, *_rest) = settings_layers(
        FUNCTUALIZE_SETTINGS, project, global_dir=tmp_path / "global"
    )

    assert layer.text == text


def test_table_less_file_is_not_a_layer(tmp_path: Path) -> None:
    """`pyproject.toml` without our table contributes nothing — and no text."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "demo"\n')

    layers = settings_layers(FUNCTUALIZE_SETTINGS, project, global_dir=tmp_path / "g")

    assert [layer.path.name for layer in layers] == ["config.toml"]
    assert layers[0].text == ""


def test_read_returns_text_for_an_unwritten_file(tmp_path: Path) -> None:
    """A prospective layer still knows its file name and prefix; text is empty."""
    from functualize._config.settings_layers import SettingsLayer

    target = tmp_path / "sub" / "pyproject.toml"

    layer = SettingsLayer.read(target, "project", "tool.functualize")

    assert layer.path == target
    assert layer.exists is False
    assert layer.text == ""
    assert layer.values == {}
    assert layer.section_prefix == "tool.functualize"


def test_read_matches_the_walk(tmp_path: Path) -> None:
    """Reading one path yields what the walk would have produced for it."""
    project = tmp_path / "project"
    project.mkdir()
    source = '[tool.functualize.cli]\noutput = "json"\n'
    (project / "pyproject.toml").write_text(source)
    from functualize._config.settings_layers import SettingsLayer

    walked = next(
        layer
        for layer in settings_layers(
            FUNCTUALIZE_SETTINGS, project, global_dir=tmp_path / "global"
        )
        if layer.path == project / "pyproject.toml"
    )
    read = SettingsLayer.read(project / "pyproject.toml", "project", "tool.functualize")

    assert read == walked
