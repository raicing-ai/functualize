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

    return complete


def test_group_children_are_scoped_without_group_options(candidates):
    root = candidates("")
    children = candidates("audit ")
    assert any(name.startswith("audit") for name in root)
    assert any(name.startswith("explain") for name in children)
    assert any(name.startswith("notes") for name in children)
    assert not any(name.startswith("builtin") for name in children)
    assert not any("audit.explain" in name for name in children)
