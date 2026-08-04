"""Tests for early-dispatch mode detection in _cli/dispatch.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli.dispatch import Mode, detect_mode


class TestDetectMode:
    """Tests for detect_mode() mode classification."""

    def test_bare_invocation_is_cli(self) -> None:
        """No args → CLI mode (will launch TUI or show help)."""
        mode, args = detect_mode(["func"])
        assert mode is Mode.CLI
        assert args == []

    def test_py_file_existing_is_single_file(self, tmp_path: Path) -> None:
        """First positional is an existing .py file → SINGLE_FILE."""
        script = tmp_path / "myjob.py"
        script.write_text("def run(): pass")

        mode, args = detect_mode(["func", str(script)])
        assert mode is Mode.SINGLE_FILE
        assert args == [str(script)]

    def test_py_file_with_function_and_args(self, tmp_path: Path) -> None:
        """File + function + remaining args all passed through."""
        script = tmp_path / "code.py"
        script.write_text("def check(): pass")

        mode, args = detect_mode(["func", str(script), "check", "--config", "x.toml"])
        assert mode is Mode.SINGLE_FILE
        assert args == [str(script), "check", "--config", "x.toml"]

    def test_nonexistent_py_file_is_cli(self) -> None:
        """A .py path that doesn't exist → CLI (Click will error)."""
        mode, args = detect_mode(["func", "/nonexistent/file.py"])
        assert mode is Mode.CLI

    def test_the_builtin_subtree_is_builtin(self) -> None:
        mode, args = detect_mode(["func", "builtin", "cache", "clear"])
        assert mode is Mode.BUILTIN
        assert args == ["builtin", "cache", "clear"]

    def test_bare_builtin_is_builtin(self) -> None:
        mode, args = detect_mode(["func", "builtin"])
        assert mode is Mode.BUILTIN

    @pytest.mark.parametrize(
        "name", ["cache", "version", "scaffold", "show-info", "config", "why"]
    )
    def test_a_former_builtin_name_is_no_longer_reserved(self, name: str) -> None:
        """The point of the subtree: those names belong to jobs again.

        Every one of these used to short-circuit to Mode.BUILTIN, so a project
        with a job called `cache` or `why` could not run it. With `builtin` the
        only reserved segment, they fall through to ordinary job routing.
        """
        mode, _ = detect_mode(["func", name])
        assert mode is not Mode.BUILTIN

    def test_discovered_job_name_is_cli(self) -> None:
        """Unknown names (discovered jobs) → CLI for Click to handle."""
        mode, args = detect_mode(["func", "deploy"])
        assert mode is Mode.CLI
        assert args == ["deploy"]

    def test_global_options_before_file(self, tmp_path: Path) -> None:
        """Global options are skipped to find the positional arg."""
        script = tmp_path / "job.py"
        script.write_text("def run(): pass")

        mode, args = detect_mode(
            ["func", "--log-level", "DEBUG", "--no-dotenv", str(script), "run"]
        )
        assert mode is Mode.SINGLE_FILE
        assert args == [str(script), "run"]

    def test_global_option_with_equals(self, tmp_path: Path) -> None:
        """--option=value style is handled."""
        script = tmp_path / "job.py"
        script.write_text("def run(): pass")

        mode, args = detect_mode(["func", "--log-level=DEBUG", str(script)])
        assert mode is Mode.SINGLE_FILE
        assert args == [str(script)]

    def test_help_flag_is_cli(self) -> None:
        """--help → CLI (Click handles help output)."""
        mode, args = detect_mode(["func", "--help"])
        assert mode is Mode.CLI

    def test_only_global_flags_is_cli(self) -> None:
        """All options, no positional → CLI."""
        mode, args = detect_mode(["func", "--no-dotenv", "--log-level", "INFO"])
        assert mode is Mode.CLI

    def test_relative_py_file(self, tmp_path: Path, monkeypatch) -> None:
        """Relative .py path is resolved against CWD."""
        script = tmp_path / "tasks" / "deploy.py"
        script.parent.mkdir()
        script.write_text("def run(): pass")

        monkeypatch.chdir(tmp_path)
        mode, args = detect_mode(["func", "tasks/deploy.py", "run"])
        assert mode is Mode.SINGLE_FILE
        assert args == ["tasks/deploy.py", "run"]


class TestDetectModeJobBareUnknown:
    """Tests for Mode.JOB, Mode.BARE, Mode.UNKNOWN detection with job_names."""

    def test_job_mode_when_positional_matches_job_name(self) -> None:
        """First positional in job_names → Mode.JOB."""
        mode, args = detect_mode(["func", "deploy"], job_names={"deploy"})
        assert mode is Mode.JOB
        assert args == ["deploy"]

    def test_bare_mode_when_no_positional_and_empty_job_names(self) -> None:
        """No positional args with job_names provided → Mode.BARE."""
        mode, args = detect_mode(["func"], job_names=set())
        assert mode is Mode.BARE
        assert args == []

    def test_unknown_mode_when_positional_not_in_job_names(self) -> None:
        """First positional not in job_names → Mode.UNKNOWN."""
        mode, args = detect_mode(["func", "nonexistent"], job_names={"deploy"})
        assert mode is Mode.UNKNOWN
        assert args == ["nonexistent"]

    def test_job_mode_via_alias(self) -> None:
        """First positional matches an alias → Mode.JOB."""
        mode, args = detect_mode(
            ["func", "d"], aliases={"d": "deploy"}, job_names={"deploy"}
        )
        assert mode is Mode.JOB
        assert args == ["d"]

    def test_plugin_group_token_classifies_unknown_pre_boot(self) -> None:
        """A plugin command group (e.g. `mcp`) is invisible pre-boot → UNKNOWN.

        Plugin commands register at APP_READY, so pre-boot classification never
        sees `mcp` as a group. It must fall through to Mode.UNKNOWN, where
        _handle_job's post-boot fallback resolves it. This documents the
        contract the plugin-dispatch fix relies on.
        """
        mode, args = detect_mode(
            ["func", "mcp", "serve"], job_names={"deploy"}, group_names=set()
        )
        assert mode is Mode.UNKNOWN
        assert args == ["mcp", "serve"]
