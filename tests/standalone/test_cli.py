"""Tests for functualize._cli.main module (unified routing).

Tests the refactored CLI entry point that uses:
- resolve_cli_config() for configuration
- FallbackCommand chain for routing
- Normal Typer commands for builtins
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from functualize._cli.main import main
from functualize.app.adapters.cli import _find_similar


class TestFindSimilar:
    """Tests for command suggestion logic."""

    def test_prefix_match(self) -> None:
        result = _find_similar("dep", ["deploy", "test", "build"])
        assert "deploy" in result

    def test_substring_match(self) -> None:
        result = _find_similar("ploy", ["deploy", "test", "build"])
        assert "deploy" in result

    def test_no_match(self) -> None:
        result = _find_similar("xyz", ["deploy", "test", "build"])
        assert result == []

    def test_empty_target(self) -> None:
        result = _find_similar("", ["deploy", "test"])
        assert result == []


class TestMainEntryPoint:
    """Tests for the main() entry point behavior."""

    def test_no_args_bare_invocation(self, tmp_path: Path) -> None:
        """No arguments triggers BARE mode — prints job list or returns."""
        with (
            patch("functualize._cli.config.resolve_cli_config") as mock_config,
            patch("functualize.app.core.FunctualizeApp") as mock_app_cls,
            patch("functualize.app.utils.auto_discover") as mock_discover,
            patch("sys.argv", ["func"]),
        ):
            from functualize._cli.config import CliConfig
            from functualize.app.config import DiscoveryConfig

            mock_config.return_value = CliConfig(
                discovery=DiscoveryConfig(),
                output="rich",
                show_timing=False,
                aliases={},
                dotenv=False,
                dotenv_path=None,
            )
            mock_discover.return_value = MagicMock(
                directories=[],
                functions=None,
                job_providers=None,
                children=None,
                children_glob=None,
                lazy=True,
                anchor=tmp_path,
                merged_config={},
                jobs_directories=[],
                import_libs=[],
            )
            mock_app = MagicMock()
            mock_app.get_jobs.return_value = []
            mock_app_cls.return_value = mock_app

            # main() with no args in non-TTY returns normally (BARE mode)
            main()

    def test_py_file_triggers_early_dispatch(self, tmp_path: Path) -> None:
        """A .py file argument should be handled by early dispatch (no FallbackGroup)."""
        py_file = tmp_path / "job.py"
        py_file.write_text("def run(): pass")

        with (
            patch(
                "functualize._cli.main._handle_single_file",
                return_value=0,
            ) as mock_handler,
            patch("sys.argv", ["func", str(py_file)]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
            # `scope_id`/`prompt_gates` are part of the call as of the
            # workflow-gate flags; asserting the full kwarg set keeps this
            # honest rather than passing on a partial match.
            mock_handler.assert_called_once_with(
                [str(py_file)],
                output_format="auto",
                _app_ref=ANY,
                scope_id=None,
                prompt_gates=False,
            )
