"""Unit tests for help panel grouping in CLI output.

Tests verify that:
- `--help` output shows both "Jobs" and "Functualize Commands" panels
- Panel ordering: "Jobs" before "Functualize Commands" when registered
  in the correct order (discovered jobs first, then builtins)

Requirements: 6.1–6.3
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from click.testing import CliRunner

from functualize._cli.builtins import register_builtin_commands
from functualize.app.adapters.cli import NormalizingGroup

if TYPE_CHECKING:
    import pytest

    from functualize.app.core import FunctualizeApp

runner = CliRunner()


# =============================================================================
# Helper: create a minimal app with discovered jobs
# =============================================================================


def _make_app_with_jobs(tmp_path: Path) -> FunctualizeApp:
    """Create a FunctualizeApp that discovers at least one job from tmp_path."""
    from functualize.app import FunctualizeApp, JobSources

    # Create a minimal job file so the app discovers it
    job_file = tmp_path / "greet.py"
    job_file.write_text('def hello():\n    """Say hello."""\n    print("hello")\n')

    app = FunctualizeApp(
        name="test-panels",
        job_sources=JobSources(directories=[str(tmp_path)]),
    )
    return app


# =============================================================================
# Panel presence tests
# =============================================================================


class TestHelpPanelPresence:
    """Test that --help output contains both panel headings."""

    def test_help_shows_functualize_commands_panel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--help SHALL display the 'Functualize Commands' panel (Req 6.2)."""
        monkeypatch.chdir(tmp_path)

        test_app = NormalizingGroup(name="func", invoke_without_command=True)

        register_builtin_commands(test_app)

        result = runner.invoke(test_app, ["--help"])
        assert result.exit_code == 0
        assert "Functualize Commands" in result.output

    def test_help_shows_discovered_jobs_panel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--help SHALL display the 'Jobs' panel (Req 6.1)."""
        monkeypatch.chdir(tmp_path)

        from functualize.app.adapters.cli import register_discovered_jobs

        test_app = NormalizingGroup(name="func", invoke_without_command=True)

        app = _make_app_with_jobs(tmp_path)
        register_discovered_jobs(test_app, app)

        result = runner.invoke(test_app, ["--help"])
        assert result.exit_code == 0
        assert "Jobs" in result.output

    def test_help_shows_both_panels(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--help SHALL display both 'Jobs' and 'Functualize Commands' panels."""
        monkeypatch.chdir(tmp_path)

        from functualize.app.adapters.cli import register_discovered_jobs

        test_app = NormalizingGroup(name="func", invoke_without_command=True)

        app = _make_app_with_jobs(tmp_path)
        register_discovered_jobs(test_app, app)
        register_builtin_commands(test_app)

        result = runner.invoke(test_app, ["--help"])
        assert result.exit_code == 0
        assert "Jobs" in result.output
        assert "Functualize Commands" in result.output


# =============================================================================
# Panel ordering tests
# =============================================================================


class TestHelpPanelOrdering:
    """Test that 'Jobs' appears before 'Functualize Commands' (Req 6.3).

    Typer renders panels in registration order. When discovered jobs are
    registered before builtins, the 'Jobs' panel appears first.
    """

    def test_discovered_jobs_panel_before_functualize_commands(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """'Jobs' panel SHALL appear before 'Functualize Commands' in --help (Req 6.3)."""
        monkeypatch.chdir(tmp_path)

        from functualize.app.adapters.cli import register_discovered_jobs

        test_app = NormalizingGroup(name="func", invoke_without_command=True)

        # Register discovered jobs BEFORE builtins to achieve correct panel order
        app = _make_app_with_jobs(tmp_path)
        register_discovered_jobs(test_app, app)
        register_builtin_commands(test_app)

        result = runner.invoke(test_app, ["--help"])
        assert result.exit_code == 0

        output = result.output
        discovered_pos = output.index("Jobs")
        functualize_pos = output.index("Functualize Commands")

        assert discovered_pos < functualize_pos, (
            f"'Jobs' (pos {discovered_pos}) should appear before "
            f"'Functualize Commands' (pos {functualize_pos}) in help output"
        )

    def test_panel_order_with_multiple_discovered_jobs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Panel order holds with multiple discovered jobs."""
        monkeypatch.chdir(tmp_path)

        from functualize.app import FunctualizeApp, JobSources
        from functualize.app.adapters.cli import register_discovered_jobs

        # Create multiple job files
        (tmp_path / "deploy.py").write_text(
            'def deploy():\n    """Deploy app."""\n    pass\n'
        )
        (tmp_path / "migrate.py").write_text(
            'def migrate():\n    """Run migrations."""\n    pass\n'
        )

        app = FunctualizeApp(
            name="test-panels-multi",
            job_sources=JobSources(directories=[str(tmp_path)]),
        )

        test_app = NormalizingGroup(name="func", invoke_without_command=True)

        # Register discovered jobs before builtins for correct panel order
        register_discovered_jobs(test_app, app)
        register_builtin_commands(test_app)

        result = runner.invoke(test_app, ["--help"])
        assert result.exit_code == 0

        output = result.output
        discovered_pos = output.index("Jobs")
        functualize_pos = output.index("Functualize Commands")

        assert discovered_pos < functualize_pos
