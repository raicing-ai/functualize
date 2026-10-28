"""Tests for the config-path command after shared settings resolution.

Unknown keys are diagnosed by ``config path`` without affecting resolution.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click
from click.testing import CliRunner, Result

from functualize._cli.builtins._config import register_config

if TYPE_CHECKING:
    import pytest

# =============================================================================
# config path tolerates keys it does not recognize
# =============================================================================


def _config_path() -> Result:
    group = click.Group(name="func")
    register_config(group)
    return CliRunner().invoke(group, ["config", "path"])


class TestConfigPathAfterUnknownKeys:
    """Unknown keys are the config path's business, not resolve-time noise."""

    def _write_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
    ) -> Path:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        path = tmp_path / "xdg" / "functualize" / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return path

    def test_a_bogus_key_in_a_recognized_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        global_path = self._write_global(
            tmp_path,
            monkeypatch,
            '[discovery]\nrequire_file_import = "functualize"\nbogus_key = "x"\n',
        )
        result = _config_path()
        assert result.exit_code == 0
        assert f"✓ used    {global_path}" in result.output
        assert "unrecognized key" not in result.output
        assert "Warning:" not in result.output

    def test_an_invalid_cli_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        global_path = self._write_global(
            tmp_path,
            monkeypatch,
            '[cli]\noutput = "json"\nshow_timing = true\ninvalid_key = "bad"\n',
        )
        result = _config_path()
        assert result.exit_code == 0
        assert f"✓ used    {global_path}" in result.output
        assert "unrecognized key" not in result.output
        assert "Warning:" not in result.output

    def test_an_unknown_discovery_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        global_path = self._write_global(
            tmp_path,
            monkeypatch,
            '[discovery]\nrequire_file_prefix = "job_"\nunknown = "ignored"\n',
        )
        result = _config_path()
        assert result.exit_code == 0
        assert f"✓ used    {global_path}" in result.output
        assert "unrecognized key" not in result.output
        assert "Warning:" not in result.output
