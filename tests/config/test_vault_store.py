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
    VaultOrigin,
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


#: The `secrets` table exactly as it shipped before origin tracking. Written
#: out in full rather than derived, because a migration test whose "old" schema
#: is generated by the new code tests nothing: it would drift silently the
#: moment `_SCHEMA` changes again.
_V0_SCHEMA = """
CREATE TABLE IF NOT EXISTS secrets (
    key         TEXT PRIMARY KEY,
    annotation  TEXT NOT NULL,
    provider    TEXT NOT NULL,
    nonce       BLOB NOT NULL,
    ciphertext  BLOB NOT NULL,
    synced_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    ts        TEXT NOT NULL,
    key       TEXT NOT NULL,
    provider  TEXT,
    action    TEXT NOT NULL,
    outcome   TEXT NOT NULL
);
"""


def _write_v0_store(path: Path, rows: int = 3) -> list[tuple[bytes, bytes]]:
    """Build a pre-upgrade store and return each row's (nonce, ciphertext)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_V0_SCHEMA)
    written: list[tuple[bytes, bytes]] = []
    for i in range(rows):
        nonce = os.urandom(12)
        ciphertext = os.urandom(48)
        conn.execute(
            "INSERT INTO secrets"
            " (key, annotation, provider, nonce, ciphertext, synced_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"section.key{i}",
                f"aws-sm://prod/secret{i}",
                "aws-sm",
                nonce,
                ciphertext,
                datetime.now(UTC).isoformat(),
            ),
        )
        written.append((nonce, ciphertext))
    conn.commit()
    conn.close()
    return written


class TestTheInPlaceUpgrade:
    """A v0 store must survive contact with the new code.

    The values in a vault are recoverable from nowhere else, so "the upgrade
    mostly worked" is not a category that exists here.
    """

    def test_existing_rows_survive_with_ciphertext_untouched(
        self, tmp_path: Path
    ) -> None:
        """The assertion that matters is byte-level.

        `_upgrade` has no key and must never need one — it copies nonce and
        ciphertext rather than re-encrypting. Comparing row counts would pass
        against an upgrade that quietly re-wrote every value.
        """
        path = tmp_path / "vault.db"
        written = _write_v0_store(path, rows=3)

        entries = SecretsVault(path).list_entries()

        assert len(entries) == 3
        with sqlite3.connect(path) as conn:
            stored = conn.execute(
                "SELECT nonce, ciphertext FROM secrets ORDER BY key"
            ).fetchall()
        assert [(bytes(n), bytes(c)) for n, c in stored] == written

    def test_migrated_rows_are_classified_as_provider_written(
        self, tmp_path: Path
    ) -> None:
        """Not a guess: before this version, `sync` was the only writer."""
        path = tmp_path / "vault.db"
        _write_v0_store(path, rows=2)

        entries = SecretsVault(path).list_entries()

        assert {e.origin for e in entries} == {VaultOrigin.PROVIDER}
        assert all(e.provider == "aws-sm" for e in entries)
        assert all(e.synced_at is not None for e in entries)

    def test_it_stamps_the_schema_version(self, tmp_path: Path) -> None:
        path = tmp_path / "vault.db"
        _write_v0_store(path)

        SecretsVault(path).list_entries()

        with sqlite3.connect(path) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1

    def test_running_it_twice_changes_nothing(self, tmp_path: Path) -> None:
        """Idempotence, asserted on the bytes rather than on not raising."""
        path = tmp_path / "vault.db"
        _write_v0_store(path, rows=3)

        def snapshot() -> list[tuple]:
            with sqlite3.connect(path) as conn:
                return conn.execute(
                    "SELECT key, origin, annotation, provider, nonce,"
                    " ciphertext, created_at, updated_at, synced_at"
                    " FROM secrets ORDER BY key"
                ).fetchall()

        SecretsVault(path).list_entries()
        first = snapshot()
        SecretsVault(path).list_entries()
        SecretsVault(path).list_entries()

        assert snapshot() == first

    def test_a_fresh_store_is_created_at_v1(self, tmp_path: Path) -> None:
        """A new store needs no upgrade to be usable.

        Named for what it checks. It was called
        `..._without_a_rebuild`, which it never asserted — a rebuild produces a
        correct shape too, so version and row count are identical either way.
        The rebuild-avoidance claim is carried by
        `test_re_running_the_upgrade_does_not_relabel_a_direct_entry`, which
        can actually fail when the guard is removed.
        """
        vault = SecretsVault(tmp_path / "new.db")
        vault.put(
            "a.b",
            _SECRET,
            annotation="aws-sm://x",
            provider="aws-sm",
            encryption_key=_KEY_A,
        )

        with sqlite3.connect(tmp_path / "new.db") as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0] == 1

    def test_a_direct_row_is_insertable_only_after_the_upgrade(
        self, tmp_path: Path
    ) -> None:
        """What the rebuild is *for*.

        v0 declares annotation, provider and synced_at NOT NULL, so a typed-in
        value — which has none of the three — could not be stored at all. This
        is the constraint SQLite cannot drop with ALTER TABLE.
        """
        path = tmp_path / "vault.db"
        _write_v0_store(path, rows=1)
        SecretsVault(path).list_entries()  # triggers the upgrade

        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO secrets"
                " (key, origin, nonce, ciphertext, created_at, updated_at)"
                " VALUES ('x.y', 'direct', ?, ?, ?, ?)",
                (
                    os.urandom(12),
                    os.urandom(32),
                    "2026-09-17T00:00:00+00:00",
                    "2026-09-17T00:00:00+00:00",
                ),
            )

        direct = [
            e
            for e in SecretsVault(path).list_entries()
            if e.origin is VaultOrigin.DIRECT
        ]
        assert len(direct) == 1
        assert direct[0].annotation is None
        assert direct[0].provider is None
        assert direct[0].synced_at is None

    def test_a_direct_row_cannot_make_the_vault_look_stale(
        self, tmp_path: Path
    ) -> None:
        """`oldest_sync` reads synced_at, which a direct entry does not have.

        SQLite's MIN ignores NULLs, so this holds by construction — asserted
        because it is now load-bearing rather than incidental.
        """
        path = tmp_path / "vault.db"
        _write_v0_store(path, rows=1)
        SecretsVault(path).list_entries()
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO secrets (key, origin, nonce, ciphertext)"
                " VALUES ('x.y', 'direct', ?, ?)",
                (os.urandom(12), os.urandom(32)),
            )

        assert SecretsVault(path).oldest_sync() is not None

    def test_re_running_the_upgrade_does_not_relabel_a_direct_entry(
        self, tmp_path: Path
    ) -> None:
        """The column guard is load-bearing, not an optimization.

        Found by sabotage: removing the `"origin" not in columns` check left
        every test green, because rebuilding an already-v1 table still yields a
        correct *shape*. What it does not yield is correct *data* — the
        rebuild's INSERT...SELECT hardcodes 'provider' as the origin, so a
        direct entry comes back through it relabelled as provider-written.

        That is silent corruption of the field ADR-023 §3 hangs on: a direct
        entry has no upstream copy, so `remove` must warn about it and `sync`
        must refuse to overwrite it. Mislabelled, it would be treated as
        refillable and could be quietly clobbered.

        The stamp is forced back to 0 to reach the rebuild path the way a lost
        or rolled-back user_version would.
        """
        path = tmp_path / "vault.db"
        vault = SecretsVault(path)
        vault.put(
            "a.synced",
            _SECRET,
            annotation="aws-sm://x",
            provider="aws-sm",
            encryption_key=_KEY_A,
        )
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO secrets (key, origin, nonce, ciphertext)"
                " VALUES ('b.typed', 'direct', ?, ?)",
                (os.urandom(12), os.urandom(32)),
            )
            conn.execute("PRAGMA user_version = 0")

        origins = {e.key: e.origin for e in SecretsVault(path).list_entries()}

        assert origins["b.typed"] is VaultOrigin.DIRECT, (
            "a direct entry was relabelled provider-written by the upgrade"
        )
        assert origins["a.synced"] is VaultOrigin.PROVIDER
