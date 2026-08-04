"""Unit tests for dotenv wiring in _cli/main.py.

Tests cover:
- _load_dotenv() resolution logic:
  - --no-dotenv suppresses all loading
  - --dotenv-file explicit path (exists → loads, missing → error + exit)
  - config dotenv_path (exists → loads, missing → warning)
  - dotenv_enabled auto-load from CWD (.env exists → loads, missing → None)
  - dotenv_enabled=False → nothing loaded
  - --no-dotenv takes precedence over dotenv_file_flag

Requirements: 19.1–19.7
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from functualize._cli.main import _load_dotenv

# =============================================================================
# _load_dotenv tests
# =============================================================================


class TestLoadDotenv:
    """Tests for _load_dotenv() resolution logic."""

    def test_no_dotenv_flag_suppresses_loading(self):
        """no_dotenv_flag=True → nothing loaded, returns None."""
        result = _load_dotenv(
            dotenv_enabled=True,
            dotenv_path="/some/path/.env",
            dotenv_file_flag="/explicit/.env",
            no_dotenv_flag=True,
        )
        assert result is None

    def test_dotenv_file_flag_loads_existing_file(self, tmp_path: Path):
        """dotenv_file_flag set, file exists → loads from that path, returns path."""
        env_file = tmp_path / ".env"
        env_file.write_text("MY_VAR=value\n")

        with patch("dotenv.load_dotenv") as mock_load:
            result = _load_dotenv(
                dotenv_enabled=False,
                dotenv_path=None,
                dotenv_file_flag=str(env_file),
                no_dotenv_flag=False,
            )

        assert result == str(env_file)
        mock_load.assert_called_once_with(str(env_file), override=False)

    def test_dotenv_file_flag_missing_file_exits(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """dotenv_file_flag set, file doesn't exist → prints error to stderr, sys.exit(1)."""
        missing = str(tmp_path / "nonexistent.env")

        with pytest.raises(SystemExit) as exc_info:
            _load_dotenv(
                dotenv_enabled=False,
                dotenv_path=None,
                dotenv_file_flag=missing,
                no_dotenv_flag=False,
            )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "nonexistent.env" in captured.err
        assert "Error" in captured.err

    def test_config_dotenv_path_loads_existing(self, tmp_path: Path):
        """dotenv_path set in config, file exists → loads from that path, returns path."""
        env_file = tmp_path / "project.env"
        env_file.write_text("DB_URL=postgres://localhost\n")

        with patch("dotenv.load_dotenv") as mock_load:
            result = _load_dotenv(
                dotenv_enabled=False,
                dotenv_path=str(env_file),
                dotenv_file_flag=None,
                no_dotenv_flag=False,
            )

        assert result == str(env_file)
        mock_load.assert_called_once_with(str(env_file), override=False)

    def test_config_dotenv_path_missing_warns_returns_none(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """dotenv_path set in config, file doesn't exist → warning to stderr, returns None."""
        missing = str(tmp_path / "missing.env")

        result = _load_dotenv(
            dotenv_enabled=False,
            dotenv_path=missing,
            dotenv_file_flag=None,
            no_dotenv_flag=False,
        )

        assert result is None
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "missing.env" in captured.err

    def test_dotenv_enabled_loads_cwd_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """dotenv_enabled=True, .env exists in CWD → loads it, returns path."""
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=abc\n")
        monkeypatch.chdir(tmp_path)

        with patch("dotenv.load_dotenv") as mock_load:
            result = _load_dotenv(
                dotenv_enabled=True,
                dotenv_path=None,
                dotenv_file_flag=None,
                no_dotenv_flag=False,
            )

        assert result == str(env_file)
        mock_load.assert_called_once_with(str(env_file), override=False)

    def test_dotenv_enabled_no_env_file_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """dotenv_enabled=True, no .env in CWD → returns None silently."""
        monkeypatch.chdir(tmp_path)

        result = _load_dotenv(
            dotenv_enabled=True,
            dotenv_path=None,
            dotenv_file_flag=None,
            no_dotenv_flag=False,
        )

        assert result is None

    def test_dotenv_disabled_no_flags_returns_none(self):
        """dotenv_enabled=False, no flags → nothing loaded, returns None."""
        result = _load_dotenv(
            dotenv_enabled=False,
            dotenv_path=None,
            dotenv_file_flag=None,
            no_dotenv_flag=False,
        )
        assert result is None

    def test_no_dotenv_takes_precedence_over_dotenv_file_flag(self, tmp_path: Path):
        """--no-dotenv takes precedence over --dotenv-file (no loading at all)."""
        env_file = tmp_path / ".env"
        env_file.write_text("LOADED=yes\n")

        result = _load_dotenv(
            dotenv_enabled=True,
            dotenv_path=str(env_file),
            dotenv_file_flag=str(env_file),
            no_dotenv_flag=True,
        )

        assert result is None
