"""The vault source asks for the key only to open a stored entry.

The field report this feature exists for began with a run that needed no
secret at all, and still went to the keyring because boot resolved the key
eagerly. These tests pin the lazy contract with a resolver that **explodes on
any call**: every path that must not need the key is proven not to ask, rather
than merely observed to finish.

Also pinned here: the two consequences the plan's architecture gate found and
the maintainer confirmed — listing never needs the key, so a section holding an
unopenable entry refuses at that entry (R-2); the no-key warning fires once, at
the first declared-remote value that falls through (R-1) — and that a miss is
recorded even with no key (R-3).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

from functualize._config.chain import ResolutionChain
from functualize._config.vault import (
    KEY_BYTES,
    KeyringLockedError,
    SecretsVault,
    VaultEntryUnreadableError,
    VaultOrigin,
)
from functualize._config.vault_key_resolver import (
    KeyAccess,
    KeyLookup,
    VaultKeyResolver,
)
from functualize._config.vault_source import VaultSource

if TYPE_CHECKING:
    from pathlib import Path

_KEY = b"\x22" * KEY_BYTES
_ANNOTATION = "fake-sm://prod/db-password"


class _ExplodingResolver(VaultKeyResolver):
    """A resolver that fails the test the moment anything asks it."""

    def __init__(self) -> None:
        super().__init__("proj", providers=())
        self.calls = 0

    def lookup(self, access: KeyAccess = KeyAccess.BOUNDED) -> KeyLookup:
        self.calls += 1
        msg = "the vault key was resolved on a path that must not need it"
        raise AssertionError(msg)


class _CountingProvider:
    """A provider that answers like a keyring, and counts how often it is asked."""

    def __init__(self, *, key: bytes | None = None, locked: bool = False) -> None:
        self._key = key
        self._locked = locked
        self.calls = 0

    def identifier(self) -> str:
        return "keychain"

    def interactive(self) -> bool:
        return False

    def is_available(self) -> bool:
        return True

    def get_key(self, project_id: str) -> bytes | None:
        self.calls += 1
        if self._locked:
            msg = "locked"
            raise KeyringLockedError(msg)
        return self._key


class _StaticSource:
    """A lower-priority source standing in for env or a config file."""

    source_type = "file"
    source_id = "config.toml"

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def get(self, key: str, section: str | None = None) -> Any | None:
        return self._values.get(f"{section}.{key}" if section else key)

    def has(self, key: str, section: str | None = None) -> bool:
        return self.get(key, section) is not None

    def keys(self, section: str) -> set[str]:
        prefix = f"{section}."
        return {k[len(prefix) :] for k in self._values if k.startswith(prefix)}


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """One provider-written entry and one typed in by hand."""
    path = tmp_path / "vault.db"
    store = SecretsVault(path)
    store.put(
        "database.password",
        "s3cret-provider",
        annotation=_ANNOTATION,
        provider="fake-sm",
        encryption_key=_KEY,
    )
    store.put(
        "api.token",
        "s3cret-direct",
        origin=VaultOrigin.DIRECT,
        encryption_key=_KEY,
    )
    return path


def _locked_resolver(provider: _CountingProvider) -> VaultKeyResolver:
    return VaultKeyResolver("proj", providers=[provider], timeout=5.0)


class TestNothingStoredNeverAsks:
    """B1 / A2 — a run reading no stored entry performs zero key lookups."""

    def test_get_of_an_absent_key_never_asks(self, vault: Path) -> None:
        resolver = _ExplodingResolver()
        source = VaultSource(vault, key=resolver)
        assert source.get("port", "database") is None
        assert resolver.calls == 0

    def test_a_missing_vault_file_never_asks(self, tmp_path: Path) -> None:
        resolver = _ExplodingResolver()
        source = VaultSource(tmp_path / "absent.db", key=resolver)
        assert source.get("password", "database") is None
        assert source.usable is False
        assert not (tmp_path / "absent.db").exists()
        assert resolver.calls == 0

    def test_has_and_keys_never_ask(self, vault: Path) -> None:
        resolver = _ExplodingResolver()
        source = VaultSource(vault, key=resolver)
        assert source.usable is True
        assert source.has("password", "database") is True
        assert source.has("port", "database") is False
        assert source.keys("database") == {"password"}
        assert source.keys("nowhere") == set()
        assert resolver.calls == 0

    def test_a_section_with_no_stored_entries_never_asks(self, vault: Path) -> None:
        resolver = _ExplodingResolver()
        chain = ResolutionChain(
            [VaultSource(vault, key=resolver), _StaticSource({"cache.ttl": "60"})]  # type: ignore[list-item]
        )
        assert chain.resolve_section("cache")["ttl"].value == "60"
        assert resolver.calls == 0

    def test_an_ordinary_fallthrough_never_asks(self, vault: Path) -> None:
        """`note_fallthrough` checks the annotation before the key."""
        resolver = _ExplodingResolver()
        source = VaultSource(vault, key=resolver, providers=("fake-sm",))
        chain = ResolutionChain([source, _StaticSource({"database.port": "5432"})])  # type: ignore[list-item]
        assert chain.resolve("port", "database").value == "5432"
        assert resolver.calls == 0

    def test_constructing_a_source_never_asks(self, vault: Path) -> None:
        resolver = _ExplodingResolver()
        VaultSource(vault, key=resolver, providers=("fake-sm",))
        assert resolver.calls == 0


class TestAStoredEntryResolvesOnce:
    def test_a_stored_entry_is_decrypted_with_the_resolved_key(
        self, vault: Path
    ) -> None:
        provider = _CountingProvider(key=_KEY)
        source = VaultSource(vault, key=_locked_resolver(provider))
        assert source.get("password", "database") == "s3cret-provider"
        assert source.get("token", "api") == "s3cret-direct"
        assert provider.calls == 1

    def test_has_agrees_with_get(self, vault: Path) -> None:
        source = VaultSource(vault, key=VaultKeyResolver.fixed(_KEY, "test"))
        for key in ("password", "absent"):
            assert source.has(key, "database") is (
                source.get(key, "database") is not None
            )

    def test_the_store_is_bound_to_the_provider_that_answered(
        self, vault: Path
    ) -> None:
        """The `SecretsVault` rebuilt after the first FOUND carries the id."""
        source = VaultSource(vault, key=VaultKeyResolver.fixed(_KEY, "keychain"))
        source.get("password", "database")
        assert source._vault._key_provider_id == "keychain"


class TestAStoredEntryThatCannotBeOpenedRefuses:
    """ADR-023 §1 — and, with laziness, listing no longer hides the entry."""

    def test_get_refuses_with_the_locked_message(self, vault: Path) -> None:
        source = VaultSource(
            vault, key=_locked_resolver(_CountingProvider(locked=True))
        )
        with pytest.raises(VaultEntryUnreadableError) as exc:
            source.get("password", "database")
        text = str(exc.value)
        assert "locked or did not answer" in text
        assert "func builtin vault unlock" in text
        assert "FUNCTUALIZE_VAULT_KEY" in text

    @pytest.mark.parametrize(
        ("section", "key"), [("database", "password"), ("api", "token")]
    )
    def test_the_locked_refusal_never_offers_a_destructive_fix(
        self, vault: Path, section: str, key: str
    ) -> None:
        source = VaultSource(
            vault, key=_locked_resolver(_CountingProvider(locked=True))
        )
        with pytest.raises(VaultEntryUnreadableError) as exc:
            source.get(key, section)
        text = str(exc.value)
        assert "vault remove" not in text
        assert "vault clear" not in text
        assert "vault sync" not in text

    def test_a_section_holding_an_unopenable_entry_refuses(self, vault: Path) -> None:
        """R-2 — used to be silently omitted from the section."""
        source = VaultSource(
            vault, key=_locked_resolver(_CountingProvider(locked=True))
        )
        chain = ResolutionChain([source, _StaticSource({})])  # type: ignore[list-item]
        with pytest.raises(VaultEntryUnreadableError):
            chain.resolve_section("database")

    def test_one_wait_for_many_stored_reads(self, vault: Path) -> None:
        provider = _CountingProvider(locked=True)
        source = VaultSource(vault, key=_locked_resolver(provider))
        for _ in range(10):
            with pytest.raises(VaultEntryUnreadableError):
                source.get("password", "database")
        assert provider.calls == 1

    def test_the_wrong_key_keeps_remove_and_clear_last_with_the_warning(
        self, vault: Path
    ) -> None:
        other = b"\x09" * KEY_BYTES
        source = VaultSource(vault, key=VaultKeyResolver.fixed(other, "keychain"))
        with pytest.raises(VaultEntryUnreadableError) as exc:
            source.get("token", "api")
        text = str(exc.value)
        assert "'keychain' provider does not open this vault" in text
        assert text.index("FUNCTUALIZE_VAULT_KEY") < text.index("vault remove")
        assert "only copy" in text
        # A direct entry cannot be refetched, so sync is not offered for it.
        assert "vault sync" not in text

    def test_the_wrong_key_offers_sync_for_a_provider_entry(self, vault: Path) -> None:
        other = b"\x09" * KEY_BYTES
        source = VaultSource(vault, key=VaultKeyResolver.fixed(other, "keychain"))
        with pytest.raises(VaultEntryUnreadableError) as exc:
            source.get("password", "database")
        assert "vault sync" in str(exc.value)


class TestTheNoKeyWarningMoved:
    """R-1 — once, at the first declared-remote value that falls through."""

    def test_an_annotation_with_no_key_warns_exactly_once(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = _CountingProvider(locked=True)
        source = VaultSource(
            tmp_path / "never-synced.db",
            key=_locked_resolver(provider),
            providers=("fake-sm",),
        )
        below = _StaticSource(
            {"database.password": _ANNOTATION, "database.user": "fake-sm://prod/u"}
        )
        chain = ResolutionChain([source, below])  # type: ignore[list-item]
        with caplog.at_level(logging.WARNING):
            chain.resolve("password", "database")
            chain.resolve("password", "database")
            chain.resolve("user", "database")
        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert _ANNOTATION in message
        assert "locked or did not answer" in message
        assert provider.calls == 1

    def test_an_app_whose_values_all_come_from_elsewhere_never_warns(
        self, vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        resolver = _ExplodingResolver()
        source = VaultSource(vault, key=resolver, providers=("fake-sm",))
        chain = ResolutionChain([source, _StaticSource({"app.name": "demo"})])  # type: ignore[list-item]
        with caplog.at_level(logging.WARNING):
            chain.resolve("name", "app")
        assert caplog.records == []
        assert resolver.calls == 0


class TestAMissIsRecordedWithNoKey:
    """R-3 — the stored-names check makes a miss knowable without the key."""

    def test_a_miss_is_recorded_without_resolving(self, vault: Path) -> None:
        resolver = _ExplodingResolver()
        source = VaultSource(vault, key=resolver)
        source.get("port", "database")
        assert source.misses == ["database.port"]
        assert resolver.calls == 0


class TestTheTransitionalSpelling:
    """TRANSITIONAL(4.1): `encryption_key=` survives until every site moves."""

    def test_key_and_encryption_key_are_mutually_exclusive(self, vault: Path) -> None:
        with pytest.raises(TypeError, match="not both"):
            VaultSource(
                vault,
                key=VaultKeyResolver.fixed(_KEY),
                encryption_key=_KEY,
            )

    def test_one_of_them_is_required(self, vault: Path) -> None:
        with pytest.raises(TypeError, match="key="):
            VaultSource(vault)
