"""Tests for FunctualizeApp interactivity.job.submit event handling (Task 3.4)."""

from __future__ import annotations

import textwrap

from functualize._app.state import AppState
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp


def _write_job(tmp_path, source: str) -> str:
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "my_jobs.py").write_text(textwrap.dedent(source))
    return str(jobs_dir)


class TestAppInteractivityJobSubmit:
    """FunctualizeApp routes interactivity.job.submit to engine.execute."""

    def setup_method(self):
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def test_emitting_job_submit_executes_registered_job(self, tmp_path):
        """Emitting interactivity.job.submit triggers the registered job."""
        # Observe execution via a filesystem side effect rather than a
        # shared module-level list: the registered function belongs to the
        # discovery scan's module instance, which is not importable as
        # plain "my_jobs" (registration no longer imports job modules by
        # their plain names).
        marker = tmp_path / "executed.marker"
        source = f"""\
            from pathlib import Path

            def tracked_job():
                Path({str(marker)!r}).write_text("ran")
        """
        jobs_dir = _write_job(tmp_path, source)

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        assert not marker.exists()

        app.event_bus.emit(
            "interactivity.job.submit",
            resource="tracked_job",
            job_name="tracked_job",
            kwargs={},
        )

        assert marker.exists()
        assert marker.read_text() == "ran"

    def test_unknown_job_name_produces_warning_no_crash(self, tmp_path, caplog):
        """Emitting interactivity.job.submit with unknown job logs warning."""
        import logging

        jobs_dir = _write_job(tmp_path, "def noop(): pass\n")
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        with caplog.at_level(logging.WARNING):
            app.event_bus.emit(
                "interactivity.job.submit",
                resource="nonexistent_job",
                job_name="nonexistent_job",
                kwargs={},
            )

        assert "nonexistent_job" in caplog.text
        assert "not registered" in caplog.text
