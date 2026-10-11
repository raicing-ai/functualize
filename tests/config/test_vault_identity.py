"""Scoped identities and the refusal of the pre-scope vault format."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from functualize._config.vault import SecretsVault, VaultError
from functualize._primitives.vault_identity import VaultIdentity

#: The wrong key a refusal is probed with — 32 valid bytes that open nothing.
_WRONG_KEY = b"\x01" * 32


def test_group_and_job_with_same_target_and_field_have_distinct_keys() -> None:
    group = VaultIdentity("group", "deploy", "token")
    job = VaultIdentity("job", "deploy", "token")

    assert group.encode() == '["group","deploy","token"]'
    assert job.encode() == '["job","deploy","token"]'
    assert group.encode() != job.encode()


def test_dots_belong_to_the_target_and_round_trip() -> None:
    original = VaultIdentity("job", "deploy.service", "iam_key")

    assert VaultIdentity.decode(original.encode()) == original


@pytest.mark.parametrize(
    "key",
    [
        "deploy.token",
        '["other","deploy","token"]',
        '["group","","token"]',
        '["group","deploy",""]',
        '["group","deploy","token","extra"]',
    ],
)
def test_malformed_or_legacy_keys_are_not_guessed_into_a_scope(key: str) -> None:
    with pytest.raises(ValueError):
        VaultIdentity.decode(key)


def _v1_store(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE secrets (
                key TEXT PRIMARY KEY, origin TEXT NOT NULL, annotation TEXT,
                provider TEXT, nonce BLOB NOT NULL, ciphertext BLOB NOT NULL,
                created_at TEXT, updated_at TEXT, synced_at TEXT,
                key_provider TEXT
            );
            CREATE TABLE vault_meta (
                id INTEGER PRIMARY KEY, nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE audit_log (
                ts TEXT NOT NULL, key TEXT NOT NULL, provider TEXT,
                action TEXT NOT NULL, outcome TEXT NOT NULL
            );
            PRAGMA user_version = 1;
            """
        )


@pytest.mark.parametrize("operation", ["list", "get", "put", "delete"])
def test_v1_store_refuses_without_changing_bytes(
    tmp_path: Path, operation: str
) -> None:
    path = tmp_path / "vault.db"
    _v1_store(path)
    before = path.read_bytes()
    vault = SecretsVault(path)
    key = '["job","deploy","token"]'

    with pytest.raises(VaultError, match="func builtin vault clear"):
        if operation == "list":
            vault.list_entries()
        elif operation == "get":
            vault.get(key, encryption_key=_WRONG_KEY)
        elif operation == "put":
            vault.put(key, "example", encryption_key=_WRONG_KEY)
        else:
            vault.delete(key)

    assert path.read_bytes() == before
    vault.clear()
    assert not path.exists()
