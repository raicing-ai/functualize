"""End-to-end test: a custom ConfigSources.file_pattern reaches FileSource.

Regression for the half-wired file_pattern: the regex used to drive only
config-directory anchoring while FileSource globbed the hardcoded
``config.*``, so the documented ``settings.*`` example found nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from functualize.app.config import ConfigSources, JobSources
from functualize.app.core import FunctualizeApp

if TYPE_CHECKING:
    import pytest


class TestFilePatternWiring:
    """ConfigSources.file_pattern drives both anchoring and file matching."""

    def test_custom_pattern_resolves_settings_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "settings.base.ini").write_text("[app]\ntitle = custom\n")
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        app = FunctualizeApp(
            name="pattern-test",
            job_sources=JobSources(directories=[str(jobs_dir)]),
            config_sources=ConfigSources(
                dotenv=False, file_pattern=r"^settings\.(\w+)\.ini$"
            ),
        )

        resolved = app._resolution_chain.resolve("title", section="app")
        assert resolved.value == "custom"
        assert resolved.source_type == "file"

    def test_default_pattern_still_matches_config_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "config.base.ini").write_text("[app]\ntitle = classic\n")
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        app = FunctualizeApp(
            name="pattern-default-test",
            job_sources=JobSources(directories=[str(jobs_dir)]),
            config_sources=ConfigSources(dotenv=False),
        )

        resolved = app._resolution_chain.resolve("title", section="app")
        assert resolved.value == "classic"
        assert resolved.source_type == "file"
