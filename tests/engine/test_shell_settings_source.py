"""Shell setting source and vault-path regression tests."""

from __future__ import annotations

from pathlib import Path

from functualize._app import boot
from functualize._app.boot import _resolve_plugins_strict
from functualize._config.chain import ResolutionChain
from functualize._config.vault import KEY_BYTES, SecretsVault, VaultOrigin
from functualize._config.vault_key_resolver import VaultKeyResolver
from functualize._config.vault_paths import vault_path_for_project
from functualize._config.vault_source import VaultSource
from functualize._engine.executor import JobExecutionEngine
from functualize._primitives.vault_identity import VaultIdentity
from functualize._types.redaction import MASK, Secret
from functualize.app import ConfigSources, FunctualizeApp, JobSources, PluginSources


def test_current_sudo_password_path_reads_vault_and_wraps_secret(
    tmp_path: Path,
) -> None:
    """Pin the current chain -> VaultSource -> Secret route before rewiring."""
    path = tmp_path / "vault.db"
    key = b"\x19" * KEY_BYTES
    SecretsVault(path).put(
        VaultIdentity("job", "shell", "sudo_password").encode(),
        "stored-password",
        origin=VaultOrigin.DIRECT,
        encryption_key=key,
    )
    source = VaultSource(path, key=VaultKeyResolver.fixed(key))
    chain = ResolutionChain([source])

    class Host:
        def resolution_chain(self) -> ResolutionChain:
            return chain

    engine = object.__new__(JobExecutionEngine)
    engine._host = Host()
    password = engine._resolve_sudo_password()

    assert chain.resolve("sudo_password", "shell").source_id == "vault"
    assert isinstance(password, Secret)
    assert password.get_secret_value() == "stored-password"
    assert str(password) == MASK


def _standard_app() -> FunctualizeApp:
    return FunctualizeApp(
        "example",
        job_sources=JobSources(functions=[]),
        config_sources=ConfigSources(),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
    )


def test_booted_engine_reads_shell_program_from_app_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".functualize.toml").write_text(
        '[shell]\nprogram = "/bin/from-settings"\n'
    )

    app = _standard_app()

    assert app.settings.get("shell.program") == "/bin/from-settings"
    assert app._execution_engine._resolve_shell_program() == "/bin/from-settings"


def test_plugin_strict_reads_declared_app_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FUNCTUALIZE_PLUGINS_STRICT", "true")
    monkeypatch.setenv("PLUGINS_STRICT", "false")

    app = _standard_app()

    assert app.settings.get("plugins.strict") is True
    assert _resolve_plugins_strict(app) is True


def test_booted_engine_reads_stored_sudo_password_lazily(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".functualize").mkdir()
    key = b"\x27" * KEY_BYTES
    path = vault_path_for_project()
    path.parent.mkdir(parents=True, exist_ok=True)
    SecretsVault(path).put(
        VaultIdentity("job", "shell", "sudo_password").encode(),
        "stored-password",
        origin=VaultOrigin.DIRECT,
        encryption_key=key,
    )
    source: VaultSource | None = None

    def fixed_source(app, vault_path, *, max_age=None):
        nonlocal source
        source = VaultSource(vault_path, key=VaultKeyResolver.fixed(key))
        return source

    monkeypatch.setattr(boot, "_lazy_vault_source", fixed_source)
    app = _standard_app()
    assert source is not None
    assert source._lookup_result is None

    password = app._execution_engine._resolve_sudo_password()

    assert isinstance(password, Secret)
    assert password.get_secret_value() == "stored-password"
    assert str(password) == MASK
    assert source._lookup_result is not None
