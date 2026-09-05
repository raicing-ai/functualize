"""remote_first() resolves remotely, or refuses. It never quietly becomes classic().

The defect this closes: the preset returned `config_resolution_chain=None` and
no boot path built a remote source, so `None` fell through to the classic
chain builder. Someone selecting it for AWS Secrets Manager got local files and
environment variables, silently, for the whole life of the shipped preset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from functualize._app.boot import build_remote_source, build_resolution_chain
from functualize._config.registry import ProviderRegistry
from functualize._config.vault import KEY_BYTES, SecretsVault
from functualize._config.vault_source import VaultSource
from functualize.app.presets import classic, env_only, remote_first, twelve_factor

_KEY = b"\x07" * KEY_BYTES


class _FakeRemoteProvider:
    def identifier(self) -> str:
        return "fake-sm"

    def is_ready(self) -> bool:
        return True

    def fetch(self, reference: str) -> str:
        return f"fetched:{reference}"


class _FakeApp:
    """The minimum `build_remote_source` reads. Avoids a full boot."""

    def __init__(self, *, remote: bool, providers: bool) -> None:
        self._config_sources = remote_first() if remote else classic()
        self.config_registry = ProviderRegistry()
        if providers:
            self.config_registry.register_remote_provider(_FakeRemoteProvider())


class TestThePresetCarriesItsIntent:
    def test_remote_first_sets_the_marker(self) -> None:
        """A bare None cannot say 'build the remote chain' — hence the flag."""
        assert remote_first().remote is True

    @pytest.mark.parametrize(
        "preset", [classic, twelve_factor, env_only], ids=["classic", "12f", "env"]
    )
    def test_every_other_preset_leaves_it_off(self, preset: Any) -> None:
        assert preset().remote is False

    def test_remote_first_still_leaves_the_chain_for_boot_to_build(self) -> None:
        assert remote_first().config_resolution_chain is None


class TestRefusalWhenNothingCouldResolve:
    def test_it_raises_rather_than_degrading_to_classic(self) -> None:
        """The headline behaviour. Falling back here is the original bug."""
        app = _FakeApp(remote=True, providers=False)
        with pytest.raises(RuntimeError) as exc:
            build_remote_source(app)
        assert "remote_first()" in str(exc.value)

    def test_the_error_names_the_entry_point_group(self) -> None:
        """An operator needs to know what to install, not just that it failed."""
        app = _FakeApp(remote=True, providers=False)
        with pytest.raises(RuntimeError, match="functualize.remote_providers"):
            build_remote_source(app)

    def test_the_error_explains_why_it_refuses(self) -> None:
        app = _FakeApp(remote=True, providers=False)
        with pytest.raises(RuntimeError, match="Refusing"):
            build_remote_source(app)


class TestOtherPresetsAreUntouched:
    def test_a_non_remote_app_builds_no_remote_source(self) -> None:
        assert build_remote_source(_FakeApp(remote=False, providers=False)) is None

    def test_a_non_remote_app_does_not_require_providers(self) -> None:
        """classic() must not start demanding a provider plugin."""
        assert build_remote_source(_FakeApp(remote=False, providers=True)) is None


class TestChainComposition:
    def _chain(self, remote_source: Any, tmp_path: Path) -> list[str]:
        chain = build_resolution_chain(
            str(tmp_path),
            "app",
            ProviderRegistry(),
            remote_source=remote_source,
        )
        return [s.source_type for s in chain.sources]

    def test_classic_composition_is_unchanged(self, tmp_path: Path) -> None:
        """One builder serves both presets; classic() must not have moved."""
        assert self._chain(None, tmp_path) == ["cli", "env", "file", "default"]

    def test_the_vault_slots_between_cli_and_env(self, tmp_path: Path) -> None:
        """A synced secret outranks env and file; an explicit CLI arg wins."""
        source = VaultSource(tmp_path / "v.db", encryption_key=_KEY)
        assert self._chain(source, tmp_path) == [
            "cli",
            "remote",
            "env",
            "file",
            "default",
        ]


class TestTheVaultSource:
    def _vault(self, tmp_path: Path) -> Path:
        path = tmp_path / "vault.db"
        vault = SecretsVault(path)
        vault.put(
            "database.password",
            "s3cret",
            annotation="fake-sm://prod/db",
            provider="fake-sm",
            encryption_key=_KEY,
        )
        return path

    def test_a_synced_value_resolves(self, tmp_path: Path) -> None:
        source = VaultSource(self._vault(tmp_path), encryption_key=_KEY)
        assert source.get("password", "database") == "s3cret"

    def test_a_miss_returns_none_and_is_recorded(self, tmp_path: Path) -> None:
        """Recorded so task 3.2 can warn; returning None defers to the chain."""
        source = VaultSource(self._vault(tmp_path), encryption_key=_KEY)
        assert source.get("absent", "database") is None
        assert "database.absent" in source.misses

    def test_no_key_makes_the_source_inert_rather_than_fatal(
        self, tmp_path: Path
    ) -> None:
        """This path is reachable from `func --help`."""
        source = VaultSource(self._vault(tmp_path), encryption_key=None)
        assert source.usable is False
        assert source.get("password", "database") is None
        assert source.has("password", "database") is False
        assert source.keys("database") == set()

    def test_a_missing_vault_file_is_inert(self, tmp_path: Path) -> None:
        """Nobody has run `vault sync` yet."""
        source = VaultSource(tmp_path / "never-synced.db", encryption_key=_KEY)
        assert source.usable is False
        assert source.get("password", "database") is None

    def test_has_and_get_agree(self, tmp_path: Path) -> None:
        """A source claiming a key it cannot deliver breaks the chain."""
        source = VaultSource(self._vault(tmp_path), encryption_key=_KEY)
        for key in ("password", "absent"):
            assert source.has(key, "database") is (
                source.get(key, "database") is not None
            )

    def test_keys_lists_a_section_without_decrypting(self, tmp_path: Path) -> None:
        source = VaultSource(self._vault(tmp_path), encryption_key=_KEY)
        assert source.keys("database") == {"password"}
        assert source.keys("other") == set()

    def test_a_wrong_key_propagates_rather_than_becoming_a_miss(
        self, tmp_path: Path
    ) -> None:
        """A vault that cannot be READ differs from one that lacks the key.

        Collapsing them would hide a wrong-key configuration behind a silent
        fall-through — the shape of the defect this feature removes.
        """
        from functualize._config.vault import VaultDecryptionError

        source = VaultSource(self._vault(tmp_path), encryption_key=b"\x09" * KEY_BYTES)
        with pytest.raises(VaultDecryptionError):
            source.get("password", "database")

    def test_it_satisfies_the_source_protocol(self, tmp_path: Path) -> None:
        from functualize._types.protocols import Source

        assert isinstance(VaultSource(tmp_path / "v.db", encryption_key=_KEY), Source)
