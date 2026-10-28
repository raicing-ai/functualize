"""Unknown settings keys in the structured info report."""

from __future__ import annotations

import json
from pathlib import Path

from functualize._cli.config import resolve_cli_config
from functualize._cli.data.func_settings import FuncSettingsStore
from functualize._cli.tui.settings_panel import SettingsPanel
from functualize.plugin import FUNCTUALIZE_SETTINGS
from tests.conftest import surfaces

pytestmark = surfaces("func")


def _config(cli_run, project: Path, *args: str) -> dict:
    result = cli_run(["builtin", "info", *args, "--json"], cwd=project)
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)["config"]


def test_unknown_keys_are_structured_in_both_info_json_forms(cli_run, project_tree):
    project = project_tree(
        functualize_toml=(
            "root = true\n"
            "roots = true\n"
            "definitely_not_a_setting = 1\n"
            "[cli]\n"
            'outptu = "json"\n'
        )
    )
    path = str(project / ".functualize.toml")
    expected = [
        {"file": path, "key": "roots", "suggestion": "root"},
        {
            "file": path,
            "key": "definitely_not_a_setting",
            "suggestion": None,
        },
        {"file": path, "key": "cli.outptu", "suggestion": "cli.output"},
    ]

    assert _config(cli_run, project)["unknown_keys"] == expected
    assert _config(cli_run, project, "all")["unknown_keys"] == expected


def test_clean_project_and_no_participating_file_have_empty_key(cli_run, project_tree):
    clean = project_tree(functualize_toml='root = true\n[cli]\noutput = "rich"\n')
    assert _config(cli_run, clean)["unknown_keys"] == []

    empty = project_tree()
    assert "unknown_keys" in _config(cli_run, empty)
    assert _config(cli_run, empty)["unknown_keys"] == []


def test_unknown_keys_follow_nearest_layer_then_document_order(
    cli_run, project_tree, xdg_dirs
):
    project = project_tree(functualize_toml='outer_typo = 1\n[cli]\noutput = "rich"\n')
    nested = project / "nested"
    nested.mkdir()
    near = nested / ".functualize.toml"
    near.write_text("first_typo = 1\nsecond_typo = 2\n")
    global_path = xdg_dirs.functualize_config / "config.toml"
    global_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.write_text("global_typo = 3\n")

    findings = _config(cli_run, nested)["unknown_keys"]

    assert [(item["file"], item["key"]) for item in findings] == [
        (str(near), "first_typo"),
        (str(near), "second_typo"),
        (str(project / ".functualize.toml"), "outer_typo"),
        (str(global_path), "global_typo"),
    ]


def test_nonparticipating_files_do_not_add_findings(cli_run, project_tree):
    project = project_tree(pyproject='[project]\nname = "other"\n')
    (project / ".functualize.toml").write_text("")

    assert _config(cli_run, project)["unknown_keys"] == []


def test_root_stop_keeps_parent_output_out_of_every_surface(cli_run, project_tree):
    parent = project_tree(functualize_toml='[cli]\noutput = "json"\n')
    nested = parent / "nested"
    nested.mkdir()
    (nested / ".functualize.toml").write_text("root = true\n")

    config = _config(cli_run, nested)
    store = FuncSettingsStore.discover(nested, env={})
    panel = SettingsPanel(catalog=FUNCTUALIZE_SETTINGS.settings)
    panel.load_from_store(store.effective_values(), store.source_labels())

    assert resolve_cli_config(cwd=nested).output == "rich"
    assert store.effective_values()["cli.output"] == "rich"
    assert panel._values["cli.output"] == "rich"
    assert config["output"] == "rich"
    assert config["unknown_keys"] == []
