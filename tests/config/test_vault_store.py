"""The encrypted vault stores values unreadably and metadata readably.

The assertion that matters is byte-level: a round-trip test passes just as
happily against a store that writes plaintext, so it proves nothing about
encryption. These tests read the file off disk.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from functualize._config.vault import (
    KEY_BYTES,
    SecretsVault,
    VaultDecryptionError,
    VaultError,
    vault_path_for_project,
)

# A deliberately distinctive fixture: these tests assert it is absent from
# files, errors, reprs and audit rows, so it must be long enough that an
# accidental match cannot be coincidence. Not a credential.
_SECRET = "correct-horse-battery-staple-9f3a"  # gitleaks:allow
_KEY_A = b"\x01" * KEY_BYTES
_KEY_B = b"\x02" * KEY_BYTES


@pytest.fixture
def vault(tmp_path: Path) -> SecretsVault:
    return SecretsVault(tmp_path / "vault.db", key_provider_id="env")


def _stored(vault: SecretsVault) -> None:
    vault.put(
        "database.password",
        _SECRET,
        annotation="aws-sm://floci/db-password",
        provider="aws-sm",
        encryption_key=_KEY_A,
    )


class TestEncryptionAtRest:
    def test_the_plaintext_is_in_no_file_the_vault_writes(
        self, vault: SecretsVault
    ) -> None:
        """The assertion that actually proves encryption happened.

        Scans **every** file, not just `vault.db`. In WAL mode a fresh write
        lands in the `-wal` sidecar and the main database can still be empty,
        so asserting on `vault.path` alone passes against a store that writes
        plaintext — verified by sabotage, which is how this test got written
        this way.
        """
        _stored(vault)
        written = sorted(p for p in vault.path.parent.iterdir() if p.is_file())
        assert written, "the vault wrote nothing"
        for path in written:
            assert _SECRET.encode() not in path.read_bytes(), path.name

    def test_the_plaintext_is_not_in_the_checkpointed_database(
        self, vault: SecretsVault
    ) -> None:
        """The same check once WAL pages have been folded into the main file."""
        _stored(vault)
        with sqlite3.connect(vault.path) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert _SECRET.encode() not in vault.path.read_bytes()

    def test_a_round_trip_returns_the_value(self, vault: SecretsVault) -> None:
        _stored(vault)
        assert vault.get("database.password", encryption_key=_KEY_A) == _SECRET

    def test_each_write_draws_a_fresh_nonce(self, vault: SecretsVault) -> None:
        """Nonce reuse under one key destroys AES-GCM entirely."""
        nonces = set()
        for i in range(10):
            vault.put(
                f"k{i}",
                _SECRET,
                annotation="aws-sm://x",
                provider="aws-sm",
                encryption_key=_KEY_A,
            )
        with sqlite3.connect(vault.path) as conn:
            for (nonce,) in conn.execute("SELECT nonce FROM secrets"):
                nonces.add(nonce)
        assert len(nonces) == 10

    def test_identical_values_produce_different_ciphertext(
        self, vault: SecretsVault
    ) -> None:
        """A consequence of the fresh nonce, and worth pinning separately."""
        for key in ("a", "b"):
            vault.put(
                key,
                _SECRET,
                annotation="aws-sm://x",
                provider="aws-sm",
                encryption_key=_KEY_A,
            )
        with sqlite3.connect(vault.path) as conn:
            blobs = [r[0] for r in conn.execute("SELECT ciphertext FROM secrets")]
        assert blobs[0] != blobs[1]


class TestTheWrongKey:
    def test_a_wrong_key_raises_rather_than_returning_garbage(
        self, vault: SecretsVault
    ) -> None:
        """AES-GCM is authenticated, so this fails instead of guessing."""
        _stored(vault)
        with pytest.raises(VaultDecryptionError):
            vault.get("database.password", encryption_key=_KEY_B)

    def test_the_error_names_the_key_provider(self, vault: SecretsVault) -> None:
        """'It did not decrypt' without naming the key tried is useless."""
        _stored(vault)
        with pytest.raises(VaultDecryptionError, match="env"):
            vault.get("database.password", encryption_key=_KEY_B)

    def test_the_error_does_not_leak_the_value(self, vault: SecretsVault) -> None:
        _stored(vault)
        with pytest.raises(VaultDecryptionError) as exc:
            vault.get("database.password", encryption_key=_KEY_B)
        assert _SECRET not in str(exc.value)

    @pytest.mark.parametrize("length", [0, 16, 31, 33, 64])
    def test_a_wrong_length_key_is_refused_up_front(
        self, vault: SecretsVault, length: int
    ) -> None:
        with pytest.raises(VaultError, match="32 bytes"):
            vault.put(
                "k",
                _SECRET,
                annotation="aws-sm://x",
                provider="aws-sm",
                encryption_key=b"\x00" * length,
            )


class TestMetadataWithoutTheKey:
    """`vault list` and `vault status` must answer with no key available."""

    def test_listing_needs_no_key(self, vault: SecretsVault) -> None:
        _stored(vault)
        entries = vault.list_entries()
        assert [e.key for e in entries] == ["database.password"]
        assert entries[0].annotation == "aws-sm://floci/db-password"
        assert entries[0].provider == "aws-sm"

    def test_an_entry_carries_no_value_field(self, vault: SecretsVault) -> None:
        """The dataclass cannot leak what it does not hold."""
        _stored(vault)
        entry = vault.list_entries()[0]
        assert not hasattr(entry, "value")
        assert _SECRET not in repr(entry)

    def test_oldest_sync_reports_the_stalest_entry(self, vault: SecretsVault) -> None:
        """A vault is only as fresh as its most-likely-rotated value."""
        _stored(vault)
        oldest = vault.oldest_sync()
        assert oldest is not None
        assert datetime.now(UTC) - oldest < timedelta(seconds=30)

    def test_oldest_sync_is_none_when_empty(self, vault: SecretsVault) -> None:
        assert vault.oldest_sync() is None


class TestMisses:
    def test_a_miss_returns_none_rather_than_raising(self, vault: SecretsVault) -> None:
        """The caller decides; ADR-016 says fall through with a warning."""
        assert vault.get("never.stored", encryption_key=_KEY_A) is None


class TestAudit:
    def test_reads_and_misses_are_recorded(self, vault: SecretsVault) -> None:
        _stored(vault)
        vault.get("database.password", encryption_key=_KEY_A)
        vault.get("absent", encryption_key=_KEY_A)
        actions = [(r[3], r[4]) for r in vault.audit_records()]
        assert ("sync", "ok") in actions
        assert ("read", "ok") in actions
        assert ("read", "miss") in actions

    def test_the_audit_log_never_holds_a_value(self, vault: SecretsVault) -> None:
        _stored(vault)
        vault.get("database.password", encryption_key=_KEY_A)
        for record in vault.audit_records():
            assert _SECRET not in str(record)


class TestProjectScoping:
    def test_two_projects_get_two_files(self, tmp_path: Path) -> None:
        a = vault_path_for_project(tmp_path / "work-api")
        b = vault_path_for_project(tmp_path / "side-thing")
        assert a != b

    def test_one_project_cannot_read_anothers_entry(self, tmp_path: Path) -> None:
        """The isolation ADR-016 chose per-project vaults for."""
        work = SecretsVault(tmp_path / "work" / "vault.db")
        side = SecretsVault(tmp_path / "side" / "vault.db")
        work.put(
            "database.password",
            _SECRET,
            annotation="aws-sm://prod/db",
            provider="aws-sm",
            encryption_key=_KEY_A,
        )
        assert side.get("database.password", encryption_key=_KEY_A) is None

    def test_the_path_honours_xdg_data_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        path = vault_path_for_project(tmp_path / "proj")
        if os.name != "nt":  # Windows uses platform dirs, not XDG
            assert str(tmp_path / "xdg") in str(path)
        assert path.name == "vault.db"
        assert "vaults" in path.parts


class TestClear:
    def test_clear_removes_the_file_and_its_sidecars(self, vault: SecretsVault) -> None:
        _stored(vault)
        assert vault.path.exists()
        vault.clear()
        assert not vault.path.exists()
        leftovers = [p.name for p in vault.path.parent.iterdir()]
        assert leftovers == []

    def test_clear_is_idempotent(self, vault: SecretsVault) -> None:
        vault.clear()
        vault.clear()
