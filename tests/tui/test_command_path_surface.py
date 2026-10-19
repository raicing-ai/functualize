"""SmartBar navigation is available without group option declarations."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from functualize._cli.completions.provenance import CompletionProvenanceClassifier
    from functualize._cli.tui.smart_bar_autocomplete import SmartBarAutoComplete
    from functualize.app.config import JobSources
    from functualize.app.core import FunctualizeApp

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (tmp_path / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\n', encoding="utf-8"
    )
    (jobs / "audit.py").write_text(
        'JOB_GROUP = "audit"\n\n'
        "def explain() -> None:\n    pass\n\n"
        "def notes() -> None:\n    pass\n"
    )
    app = FunctualizeApp(name="audit", job_sources=JobSources(directories=[str(jobs)]))
    app.get_jobs()
    autocomplete = SmartBarAutoComplete(app, CompletionProvenanceClassifier(app))

    def complete(line: str) -> list[str]:
        items = autocomplete._command_mode_candidates(line, len(line))
        return [
            str(item.get("main", ""))
            if isinstance(item, dict)
            else str(getattr(item, "main", item))
            for item in items
        ]

    complete.items = lambda line: autocomplete._command_mode_candidates(line, len(line))
    complete.root = tmp_path
    complete.app = app
    return complete


def test_group_children_are_scoped_without_group_options(candidates):
    root = candidates("")
    children = candidates("audit ")
    assert any(name.startswith("audit") for name in root)
    assert any(name.startswith("explain") for name in children)
    assert any(name.startswith("notes") for name in children)
    assert not any(name.startswith("builtin") for name in children)
    assert not any("audit.explain" in name for name in children)


def test_no_option_path_has_provenance_and_runs(candidates, cli_run):
    from functualize._cli.tui.cli_arg_parser import (
        build_group_option_trie,
        resolve_tui_command,
    )

    items = candidates.items("audit ")
    labels = [str(item.main) for item in items]
    assert any(label.startswith("explain") for label in labels)
    assert any(label.startswith("notes") for label in labels)
    assert all("(local)" in label for label in labels)
    chosen = next(label.split()[0] for label in labels if label.startswith("explain"))
    trie = build_group_option_trie(candidates.app)
    resolution = resolve_tui_command(trie, ["audit", chosen])
    assert resolution.job_name == "audit.explain"
    invoked = cli_run(["audit", chosen], cwd=candidates.root)
    assert invoked.exit_code == 0, invoked.stderr


def test_dotted_traversal_is_not_a_tui_path(candidates):
    from functualize._cli.tui.cli_arg_parser import (
        build_group_option_trie,
        resolve_tui_command,
    )

    trie = build_group_option_trie(candidates.app)
    resolution = resolve_tui_command(trie, ["audit.explain"])
    assert resolution.job_name is None
    assert resolution.dotted_token == "audit.explain"


def test_literal_dot_leaf_remains_a_tui_path():
    from functualize._cli.tui.cli_arg_parser import resolve_tui_command
    from functualize.app.utils import build_group_trie

    trie = build_group_trie([("ci", "ci.tools.lint", "job")], builtin=False)
    resolution = resolve_tui_command(trie, ["ci", "tools.lint"])
    assert resolution.job_name == "ci.tools.lint"
    assert resolution.dotted_token is None
