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
