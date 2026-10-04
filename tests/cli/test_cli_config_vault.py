"""`[vault] keyring_timeout` — a func setting like any other (spec A12a).

The wait on the OS keyring is a per-machine choice, so it rides the func
settings chain (default < global < project, nearest wins < env) and reaches the
app as data in ``ConfigSources`` — the app layer never reads the settings
files itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli.config import resolve_cli_config
from functualize._cli.data.func_settings import env_var_for, func_setting


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp home + cwd so no real config leaks in."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("FUNCTUALIZE_VAULT_KEYRING_TIMEOUT", raising=False)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def _global_file(project: Path) -> Path:
    path = project.parent / "xdg" / "functualize" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class TestTheCatalogEntry:
    def test_it_is_registered_with_its_default(self) -> None:
        setting = func_setting("vault.keyring_timeout")
        assert setting is not None
        assert setting.section == "vault"
        assert setting.default == "30s"

    def test_its_env_spelling(self) -> None:
        setting = func_setting("vault.keyring_timeout")
        assert setting is not None
        assert env_var_for(setting) == "FUNCTUALIZE_VAULT_KEYRING_TIMEOUT"


class TestResolution:
    def test_unset_is_none(self, isolated: Path) -> None:
        assert resolve_cli_config(cwd=isolated).vault_keyring_timeout is None

    def test_a_project_file_sets_it(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text('[vault]\nkeyring_timeout = "5s"\n')
        assert resolve_cli_config(cwd=isolated).vault_keyring_timeout == "5s"

    def test_the_global_file_sets_it(self, isolated: Path) -> None:
        _global_file(isolated).write_text('[vault]\nkeyring_timeout = "2m"\n')
        assert resolve_cli_config(cwd=isolated).vault_keyring_timeout == "2m"

    def test_the_project_outranks_the_global_file(self, isolated: Path) -> None:
        _global_file(isolated).write_text('[vault]\nkeyring_timeout = "2m"\n')
        (isolated / ".functualize.toml").write_text('[vault]\nkeyring_timeout = "5s"\n')
        assert resolve_cli_config(cwd=isolated).vault_keyring_timeout == "5s"

    def test_the_nearest_project_file_wins(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text('[vault]\nkeyring_timeout = "9s"\n')
        sub = isolated / "sub"
        sub.mkdir()
        (sub / ".functualize.toml").write_text('[vault]\nkeyring_timeout = "4s"\n')
        assert resolve_cli_config(cwd=sub).vault_keyring_timeout == "4s"

    def test_the_env_var_outranks_the_files(
        self, isolated: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (isolated / ".functualize.toml").write_text('[vault]\nkeyring_timeout = "5s"\n')
        monkeypatch.setenv("FUNCTUALIZE_VAULT_KEYRING_TIMEOUT", "11s")
        assert resolve_cli_config(cwd=isolated).vault_keyring_timeout == "11s"

    def test_an_unknown_vault_key_is_ignored_with_a_warning(
        self, isolated: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _global_file(isolated).write_text(
            '[vault]\nkeyring_timeout = "3s"\nnot_a_setting = 1\n'
        )
        config = resolve_cli_config(cwd=isolated)
        assert config.vault_keyring_timeout == "3s"
        assert "unrecognized key 'not_a_setting' in [vault]" in capsys.readouterr().err


class TestItReachesConfigSources:
    def test_config_sources_carries_it(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text('[vault]\nkeyring_timeout = "5s"\n')
        sources = resolve_cli_config(cwd=isolated).config_sources()
        assert sources.vault_keyring_timeout == "5s"

    def test_config_sources_keeps_the_dotenv_settings(self, isolated: Path) -> None:
        (isolated / ".functualize.toml").write_text(
            'dotenv = true\ndotenv_path = ".env.local"\n'
        )
        sources = resolve_cli_config(cwd=isolated).config_sources()
        assert sources.dotenv is True
        assert sources.dotenv_path == ".env.local"
