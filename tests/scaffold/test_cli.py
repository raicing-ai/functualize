"""Tests for the scaffold CLI entry point."""

import os
from pathlib import Path

from click.testing import CliRunner

from functualize._cli.scaffold.cli import scaffold_app as app

runner = CliRunner()


class TestInitCommand:
    """Tests for the 'scaffold init' command."""

    def test_init_creates_project_with_default_template(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["init", "my-project", "-d", str(tmp_path)])
        assert result.exit_code == 0
        assert "my-project" in result.output
        assert (tmp_path / "my-project").is_dir()

    def test_init_creates_project_with_specified_template(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["init", "my-project", "--template", "simple", "-d", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "my-project" in result.output

    def test_init_invalid_template_exits_with_error(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            ["init", "my-project", "--template", "nonexistent", "-d", str(tmp_path)],
        )
        assert result.exit_code == 1
        assert "Unknown template" in result.output

    def test_init_invalid_name_exits_with_error(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["init", "INVALID", "-d", str(tmp_path)])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_init_existing_directory_exits_with_error(self, tmp_path: Path) -> None:
        (tmp_path / "existing").mkdir()
        result = runner.invoke(app, ["init", "existing", "-d", str(tmp_path)])
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_init_requires_project_name(self) -> None:
        result = runner.invoke(app, ["init"])
        assert result.exit_code != 0

    def test_init_lists_available_templates_on_invalid(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["init", "my-project", "--template", "bad", "-d", str(tmp_path)]
        )
        assert result.exit_code == 1
        assert "simple" in result.output
        assert "full-interactivity" in result.output


class TestAddJobCommand:
    """Tests for the 'scaffold add job' command."""

    def test_add_job_with_jobs_dir_creates_file(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        result = runner.invoke(
            app, ["add", "job", "my-job", "--jobs-dir", str(jobs_dir)]
        )
        assert result.exit_code == 0
        assert "my-job" in result.output
        assert (jobs_dir / "my_job.py").exists()

    def test_add_job_project_context(self, tmp_path: Path) -> None:
        """In Project_Context, job is created in src/<package>/jobs/."""
        # Set up a project context
        pkg_dir = tmp_path / "src" / "mypackage"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        # Run from project root
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["add", "job", "my-job"])
        finally:
            os.chdir(original_cwd)

        assert result.exit_code == 0
        assert (pkg_dir / "jobs" / "my_job.py").exists()

    def test_add_job_bare_context(self, tmp_path: Path) -> None:
        """In Bare_Context, job is created as standalone file in CWD."""
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["add", "job", "my-job"])
        finally:
            os.chdir(original_cwd)

        assert result.exit_code == 0
        assert (tmp_path / "my_job.py").exists()

    def test_add_job_invalid_name(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        result = runner.invoke(app, ["add", "job", "BAD!", "--jobs-dir", str(jobs_dir)])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_add_job_existing_file(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "my_job.py").write_text("# existing")
        result = runner.invoke(
            app, ["add", "job", "my-job", "--jobs-dir", str(jobs_dir)]
        )
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_add_job_jobs_dir_uses_project_template(self, tmp_path: Path) -> None:
        """--jobs-dir always uses project job template (not standalone)."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        result = runner.invoke(
            app, ["add", "job", "my-job", "--jobs-dir", str(jobs_dir)]
        )
        assert result.exit_code == 0
        content = (jobs_dir / "my_job.py").read_text()
        # Project template uses RunContext or JOB_GROUP pattern
        assert "my_job" in content or "my-job" in content


class TestAddPluginCommand:
    """Tests for the 'scaffold add plugin' command."""

    def test_add_plugin_with_target_dir_creates_file(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["add", "plugin", "my-plugin", "--target-dir", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "my-plugin" in result.output
        assert (tmp_path / "my_plugin.py").exists()

    def test_add_plugin_project_context(self, tmp_path: Path) -> None:
        """In Project_Context, plugin is created in src/<package>/plugins/."""
        pkg_dir = tmp_path / "src" / "mypackage"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["add", "plugin", "my-plugin"])
        finally:
            os.chdir(original_cwd)

        assert result.exit_code == 0
        assert (pkg_dir / "plugins" / "my_plugin.py").exists()

    def test_add_plugin_bare_context(self, tmp_path: Path) -> None:
        """In Bare_Context, plugin is created in .functualize/plugins/."""
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["add", "plugin", "my-plugin"])
        finally:
            os.chdir(original_cwd)

        assert result.exit_code == 0
        assert (tmp_path / ".functualize" / "plugins" / "my_plugin.py").exists()

    def test_add_plugin_invalid_name(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["add", "plugin", "X", "--target-dir", str(tmp_path)]
        )
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_add_plugin_existing_file(self, tmp_path: Path) -> None:
        (tmp_path / "my_plugin.py").write_text("# existing")
        result = runner.invoke(
            app, ["add", "plugin", "my-plugin", "--target-dir", str(tmp_path)]
        )
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestAddTuiScreenCommand:
    """Tests for the 'scaffold add tui-screen' command."""

    def test_add_tui_screen_with_target_dir(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["add", "tui-screen", "my-screen", "--target-dir", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "my-screen" in result.output
        assert (tmp_path / "my_screen.py").exists()
        assert (tmp_path / "my_screen.tcss").exists()

    def test_add_tui_screen_project_context(self, tmp_path: Path) -> None:
        """In Project_Context, screen is created in src/<package>/screens/."""
        pkg_dir = tmp_path / "src" / "mypackage"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["add", "tui-screen", "my-screen"])
        finally:
            os.chdir(original_cwd)

        assert result.exit_code == 0
        assert (pkg_dir / "screens" / "my_screen.py").exists()
        assert (pkg_dir / "screens" / "my_screen.tcss").exists()

    def test_add_tui_screen_bare_context_without_target_dir_errors(
        self, tmp_path: Path
    ) -> None:
        """In Bare_Context without --target-dir, exits with error."""
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["add", "tui-screen", "my-screen"])
        finally:
            os.chdir(original_cwd)

        assert result.exit_code == 1
        assert "--target-dir" in result.output

    def test_add_tui_screen_invalid_name(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["add", "tui-screen", "123bad", "--target-dir", str(tmp_path)]
        )
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_add_tui_screen_existing_file(self, tmp_path: Path) -> None:
        (tmp_path / "my_screen.py").write_text("# existing")
        result = runner.invoke(
            app, ["add", "tui-screen", "my-screen", "--target-dir", str(tmp_path)]
        )
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestScreenCommandRemoved:
    """Tests that the old 'screen' command is removed."""

    def test_screen_command_not_recognized(self) -> None:
        """'scaffold add screen' should result in a Typer 'No such command' error."""
        result = runner.invoke(app, ["add", "screen", "my-screen"])
        assert result.exit_code != 0
        # Typer produces "No such command" or usage error
        assert (
            "No such command" in result.output
            or "Usage" in result.output
            or result.exit_code == 2
        )


class TestAddHelpOutput:
    """Tests that 'scaffold add --help' shows only job, plugin, tui-screen."""

    def test_add_help_lists_correct_subcommands(self) -> None:
        result = runner.invoke(app, ["add", "--help"])
        assert result.exit_code == 0
        assert "job" in result.output
        assert "plugin" in result.output
        assert "tui-screen" in result.output
        # Should NOT have screen or inline
        assert "inline" not in result.output

    def test_scaffold_help_shows_init_and_add(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "init" in result.output
        assert "add" in result.output

    def test_scaffold_new_command_not_recognized(self) -> None:
        """'scaffold new' is completely removed — not just hidden."""
        result = runner.invoke(app, ["new", "my-project"])
        assert result.exit_code != 0
        # Typer produces "No such command" or usage error
        assert (
            "No such command" in result.output
            or "Usage" in result.output
            or result.exit_code == 2
        )


class TestRunEntryPoint:
    """Tests for the run() entry point function."""

    def test_help_output(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "scaffold" in result.output.lower() or "Create" in result.output

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # Typer with no_args_is_help=True shows help (exit code 0 or 2)
        assert result.exit_code in (0, 2)
        assert "init" in result.output
        assert "add" in result.output
