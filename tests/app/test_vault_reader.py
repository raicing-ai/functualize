"""The composition adapter behind ``Vault.read`` (`_app/vault_reader.py`).

Direct tests of the adapter: which source it asks, that it asks that source
for group scope and nothing else, and how the three outcomes leave it. The
candidate order itself belongs to ``VaultIdentity.lookup_candidates``; these
tests pin that the adapter *reaches* that order rather than restating it, by
observing the answers a stored vault gives through it.

The end-to-end job path -- injection, both boot paths, secrecy across every
output -- is `tests/integration/test_group_vault_read.py`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from functualize._app import vault_reader
from functualize._app.vault_reader import LocalVaultReaderFactory
from functualize._config.chain import ResolutionChain
from functualize._config.vault import (
    KEY_BYTES,
    SecretsVault,
    VaultDecryptionError,
    VaultEntryMissingError,
    VaultEntryUnreadableError,
    VaultOrigin,
)
from functualize._config.vault_key_resolver import VaultKeyResolver
from functualize._config.vault_source import VaultSource
from functualize._primitives.vault_identity import VaultIdentity
from functualize._types.protocols import Vault, VaultReaderFactory
from functualize._types.redaction import MASK, Secret

_KEY = b"\x11" * KEY_BYTES
_GROUP = "cloudflare_dev.d1.main"
_FIELD = "api_token"
#: Distinctive, so an absence assertion cannot pass by coincidence.
_MARKER = "F6-ADAPTER-PLAINTEXT-5b0e2c-never-rendered"  # gitleaks:allow


class _NothingStored:
    """A live keyring holding no vault key: a lookup ends NOT_STORED."""

    def identifier(self) -> str:
        return "keychain"

    def interactive(self) -> bool:
        return False

    def is_available(self) -> bool:
        return True

    def get_key(self, project_id: str) -> bytes | None:
        return None


class _LowerSource:
    """Stands in for env/file/defaults: answers *everything* it is asked."""

    source_type = "env"
    source_id = "env"

    def __init__(self) -> None:
        self.asked: list[tuple[str, str | None, str]] = []

    def get(self, key: str, section: str | None = None, *, scope: str = "job") -> Any:
        self.asked.append((key, section, scope))
        return "substituted-from-a-lower-source"

    def has(self, key: str, section: str | None = None, *, scope: str = "job") -> bool:
        return True

    def keys(self, section: str, *, scope: str = "job") -> set[str]:
        return {_FIELD}


def _resolver(key: bytes | None) -> VaultKeyResolver:
    if key is None:
        return VaultKeyResolver("proj", providers=[_NothingStored()], timeout=5.0)
    return VaultKeyResolver.fixed(key, "test")


def _put(
    path: Path,
    target: str,
    value: str,
    *,
    environment: str | None = None,
    scope: str = "group",
    origin: VaultOrigin = VaultOrigin.DIRECT,
) -> None:
    SecretsVault(path).put(
        VaultIdentity(scope, target, _FIELD, environment).encode(),  # type: ignore[arg-type]
        value,
        encryption_key=_KEY,
        origin=origin,
        provider=None if origin is VaultOrigin.DIRECT else "fake-sm",
        annotation=None if origin is VaultOrigin.DIRECT else "fake-sm://x",
    )


def _app(path: Path, *, key: bytes | None = _KEY, environment: str = "prod") -> Any:
    """An app as the adapter sees it: a chain whose vault source sits above a
    lower source that would answer anything."""
    source = VaultSource(path, key=_resolver(key), environment=environment)
    lower = _LowerSource()
    chain = ResolutionChain([source, lower])  # type: ignore[list-item]
    return SimpleNamespace(_resolution_chain=chain, lower=lower)


def _read(app: Any, group: str = _GROUP, field: str = _FIELD) -> Secret:
    return LocalVaultReaderFactory(app).open().read(group, field)


class TestThePorts:
    def test_the_factory_and_its_reader_satisfy_the_typed_ports(
        self, tmp_path: Path
    ) -> None:
        factory = LocalVaultReaderFactory(_app(tmp_path / "vault.db"))

        assert isinstance(factory, VaultReaderFactory)
        assert isinstance(factory.open(), Vault)

    def test_each_open_is_a_fresh_reader(self, tmp_path: Path) -> None:
        """Per invocation: one run's resolved source never leaks into the next."""
        factory = LocalVaultReaderFactory(_app(tmp_path / "vault.db"))

        assert factory.open() is not factory.open()


class TestCandidateOrder:
    """AC-2, through the adapter: the order is the existing group lookup."""

    def test_the_active_exact_entry_wins(self, tmp_path: Path) -> None:
        path = tmp_path / "vault.db"
        _put(path, _GROUP, "active-exact", environment="prod")
        _put(path, "cloudflare_dev", "active-ancestor", environment="prod")
        _put(path, _GROUP, "shared-exact")

        secret = _read(_app(path))

        assert isinstance(secret, Secret)
        assert secret.get_secret_value() == "active-exact"

    def test_an_active_ancestor_beats_a_shared_exact_entry(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "vault.db"
        _put(path, "cloudflare_dev", "active-ancestor", environment="prod")
        _put(path, _GROUP, "shared-exact")

        assert _read(_app(path)).get_secret_value() == "active-ancestor"

    def test_the_nearest_active_ancestor_wins(self, tmp_path: Path) -> None:
        path = tmp_path / "vault.db"
        _put(path, "cloudflare_dev", "far", environment="prod")
        _put(path, "cloudflare_dev.d1", "near", environment="prod")

        assert _read(_app(path)).get_secret_value() == "near"

    def test_the_shared_slot_answers_only_when_the_active_tier_is_empty(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "vault.db"
        _put(path, "cloudflare_dev", "shared-far")
        _put(path, "cloudflare_dev.d1", "shared-near")

        assert _read(_app(path)).get_secret_value() == "shared-near"

    def test_a_provider_origin_entry_is_read_the_same_way(self, tmp_path: Path) -> None:
        path = tmp_path / "vault.db"
        _put(path, _GROUP, "synced", environment="prod", origin=VaultOrigin.PROVIDER)

        assert _read(_app(path)).get_secret_value() == "synced"


class TestAbsence:
    """AC-3 and AC-4: what is not a candidate, and what absence looks like."""

    def test_no_candidate_is_the_missing_error_and_nothing_is_substituted(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "vault.db"
        _put(path, "unrelated", "x")
        app = _app(path)

        with pytest.raises(VaultEntryMissingError) as caught:
            _read(app)

        assert (caught.value.group, caught.value.field) == (_GROUP, _FIELD)
        # The lower source would have answered; it was never asked.
        assert app.lower.asked == []

    def test_a_missing_vault_file_is_the_same_absence(self, tmp_path: Path) -> None:
        path = tmp_path / "never-created.db"

        with pytest.raises(VaultEntryMissingError):
            _read(_app(path))
        assert not path.exists(), "a read must not create the store"

    def test_a_job_scope_entry_is_never_a_candidate(self, tmp_path: Path) -> None:
        path = tmp_path / "vault.db"
        _put(path, _GROUP, "job-entry", environment="prod", scope="job")
        _put(path, _GROUP, "job-entry-shared", scope="job")

        with pytest.raises(VaultEntryMissingError):
            _read(_app(path))

    def test_another_named_environment_is_never_a_candidate(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "vault.db"
        _put(path, _GROUP, "staging-entry", environment="staging")

        with pytest.raises(VaultEntryMissingError):
            _read(_app(path, environment="prod"))

    def test_a_vault_error_is_what_a_caller_catches(self) -> None:
        from functualize._config.vault import VaultError

        assert issubclass(VaultEntryMissingError, VaultError)
        assert not issubclass(VaultEntryMissingError, VaultEntryUnreadableError)


class TestUnreadableStops:
    """AC-5: the first stored candidate is authoritative even when unreadable."""

    @pytest.mark.parametrize("origin", [VaultOrigin.DIRECT, VaultOrigin.PROVIDER])
    def test_no_key_for_the_active_entry_refuses_before_the_shared_one(
        self, tmp_path: Path, origin: VaultOrigin
    ) -> None:
        path = tmp_path / "vault.db"
        _put(path, _GROUP, _MARKER, environment="prod", origin=origin)
        _put(path, _GROUP, "readable-shared")
        app = _app(path, key=None)

        with pytest.raises(VaultEntryUnreadableError) as caught:
            _read(app)

        assert _MARKER not in str(caught.value)
        assert app.lower.asked == []

    def test_a_stored_ancestor_stops_the_walk_before_later_candidates(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "vault.db"
        _put(path, "cloudflare_dev", "stored-ancestor", environment="prod")
        _put(path, _GROUP, "shared-exact")

        with pytest.raises(VaultEntryUnreadableError):
            _read(_app(path, key=None))

    def test_a_wrong_key_refuses(self, tmp_path: Path) -> None:
        path = tmp_path / "vault.db"
        _put(path, _GROUP, _MARKER, environment="prod")
        _put(path, _GROUP, "readable-shared")

        with pytest.raises(VaultEntryUnreadableError) as caught:
            _read(_app(path, key=b"\x09" * KEY_BYTES))
        assert _MARKER not in str(caught.value)

    def test_a_value_that_will_not_authenticate_is_a_decryption_error(
        self, tmp_path: Path
    ) -> None:
        """No check row to say "wrong key", so the decrypt itself refuses."""
        path = tmp_path / "vault.db"
        _put(path, _GROUP, _MARKER, environment="prod")
        _put(path, _GROUP, "readable-shared")
        with sqlite3.connect(path) as conn:
            conn.execute("DELETE FROM vault_meta")

        with pytest.raises(VaultDecryptionError) as caught:
            _read(_app(path, key=b"\x09" * KEY_BYTES))
        assert _MARKER not in str(caught.value)


class TestSourceSelection:
    def test_a_rebuilt_chain_is_the_one_read(self, tmp_path: Path) -> None:
        """`refresh()` replaces the chain; the factory must not hold the old one."""
        first, second = tmp_path / "first.db", tmp_path / "second.db"
        _put(first, _GROUP, "before-refresh", environment="prod")
        _put(second, _GROUP, "after-refresh", environment="prod")
        app = _app(first)
        factory = LocalVaultReaderFactory(app)
        assert factory.open().read(_GROUP, _FIELD).get_secret_value() == (
            "before-refresh"
        )

        app._resolution_chain = _app(second)._resolution_chain

        assert factory.open().read(_GROUP, _FIELD).get_secret_value() == (
            "after-refresh"
        )

    def test_a_chain_without_a_vault_source_gets_the_one_boot_builds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A custom/static chain is asked for nothing; the project vault is."""
        from functualize._app import boot

        path = tmp_path / "vault.db"
        _put(path, _GROUP, "from-project-vault", environment="prod")
        lower = _LowerSource()
        app = SimpleNamespace(_resolution_chain=ResolutionChain([lower]))  # type: ignore[list-item]
        built: list[Any] = []

        def _build(target: Any) -> VaultSource:
            built.append(target)
            return VaultSource(path, key=_resolver(_KEY), environment="prod")

        monkeypatch.setattr(boot, "build_vault_source", _build)

        assert _read(app).get_secret_value() == "from-project-vault"
        assert built == [app]
        assert lower.asked == []

    def test_no_chain_source_and_no_vault_file_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._app import boot

        monkeypatch.setattr(boot, "build_vault_source", lambda app: None)
        app = SimpleNamespace(_resolution_chain=ResolutionChain([]))

        with pytest.raises(VaultEntryMissingError):
            _read(app)

    def test_only_group_scope_is_asked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One `get`, group scope, field then group -- the existing lookup."""
        calls: list[tuple[Any, ...]] = []
        path = tmp_path / "vault.db"
        _put(path, _GROUP, "x", environment="prod")
        app = _app(path)
        source = app._resolution_chain.sources[0]
        original = source.get

        def _spy(key: str, section: str | None = None, *, scope: str = "job") -> Any:
            calls.append((key, section, scope))
            return original(key, section, scope=scope)  # type: ignore[arg-type]

        monkeypatch.setattr(source, "get", _spy)
        _read(app)

        assert calls == [(_FIELD, _GROUP, "group")]


class TestSecrecyAndInput:
    def test_the_value_is_masked_in_every_rendering(self, tmp_path: Path) -> None:
        path = tmp_path / "vault.db"
        _put(path, _GROUP, _MARKER, environment="prod")

        secret = _read(_app(path))

        assert str(secret) == MASK
        assert _MARKER not in repr(secret)
        assert _MARKER not in f"{secret}"
        assert secret.get_secret_value() == _MARKER

    def test_the_missing_error_carries_no_value(self, tmp_path: Path) -> None:
        path = tmp_path / "vault.db"
        _put(path, _GROUP, _MARKER, environment="staging")

        with pytest.raises(VaultEntryMissingError) as caught:
            _read(_app(path))
        assert _MARKER not in str(caught.value)
        assert _MARKER not in repr(caught.value)

    @pytest.mark.parametrize(("group", "field"), [("", _FIELD), (_GROUP, "")])
    def test_an_empty_address_is_an_input_error_not_a_miss(
        self, tmp_path: Path, group: str, field: str
    ) -> None:
        """Even with no vault file, where a miss would otherwise be the answer."""
        with pytest.raises(ValueError, match="nonempty"):
            _read(_app(tmp_path / "absent.db"), group, field)

    def test_a_non_string_address_is_a_type_error(self, tmp_path: Path) -> None:
        reader = LocalVaultReaderFactory(_app(tmp_path / "absent.db")).open()

        with pytest.raises(TypeError, match="str"):
            reader.read(None, _FIELD)  # type: ignore[arg-type]


def test_the_adapter_does_not_walk_candidates_itself() -> None:
    """C3: one lookup policy. The adapter never names the candidate walker."""
    source = Path(vault_reader.__file__).read_text()

    assert "lookup_candidates(" not in source
    assert ".resolve(" not in source
