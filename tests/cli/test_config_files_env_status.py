"""The Config Files panel must say when a file is being ignored.

The reported problem: "The status is still 'exists' for config.dev.toml and
nothing shows / indicates that it's not used due to no environment file."

The old status was a pure `os.access` stat — it could only report existence
and writability, two things that say nothing about whether the file is
actually contributing. A `config.prod.toml` sitting in the project under
ENVIRONMENT=dev is completely ignored, and read "● exists".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli.tui.panels.config_files import discover_config_files
from functualize._cli.tui.panels.config_table import FieldDef, ParamKind
from functualize.app.core import FunctualizeApp, JobSources

_JOB_MODULE = '''
from pydantic import BaseModel, Field


class ServeConfig(BaseModel):
    """Config for serve."""

    port: int = Field(default=3000, description="Port")


def serve(config: ServeConfig) -> None:
    """Serve."""
'''


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "serve_job.py").write_text(_JOB_MODULE)
    (tmp_path / "config.base.toml").write_text("[serve]\nport = 80\n")
    (tmp_path / "config.dev.toml").write_text("[serve]\nport = 8080\n")
    (tmp_path / "config.prod.toml").write_text("[serve]\nport = 9999\n")
    return tmp_path


def _entries(project: Path, environment: str) -> dict[str, object]:
    import os

    os.environ["ENVIRONMENT"] = environment
    app = FunctualizeApp(
        name="envstatus", job_sources=JobSources(directories=[str(project / "jobs")])
    )
    fields = [
        FieldDef(name="port", value="", source="", param_kind=ParamKind.CONFIG),
    ]
    entries = discover_config_files(
        fields,
        "serve",
        None,
        project,
        kernel_files=app.config_files("serve"),
        config_section="serve",
    )
    return {e.display_name: e for e in entries}


class TestEnvironmentAwareStatus:
    def test_the_active_overlay_is_marked_active(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "dev")
        files = _entries(project, "dev")

        assert files["config.dev.toml"].status == "active"
        assert files["config.base.toml"].status == "active"

    def test_a_file_for_another_environment_is_marked_inactive(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reported bug: prod says 'exists' while being ignored."""
        monkeypatch.setenv("ENVIRONMENT", "dev")
        files = _entries(project, "dev")

        assert files["config.prod.toml"].status == "inactive"

    def test_status_follows_the_environment(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "prod")
        files = _entries(project, "prod")

        assert files["config.prod.toml"].status == "active"
        assert files["config.dev.toml"].status == "inactive"

    def test_the_environment_slot_is_reported(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "dev")
        files = _entries(project, "dev")

        assert files["config.dev.toml"].environment_slot == "dev"
        assert files["config.base.toml"].environment_slot == "base"

    def test_inactive_files_are_still_listed(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Hiding them would answer the user's question by omission."""
        monkeypatch.setenv("ENVIRONMENT", "dev")
        files = _entries(project, "dev")

        assert "config.prod.toml" in files
