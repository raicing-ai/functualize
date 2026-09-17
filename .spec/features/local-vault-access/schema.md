# Schema: local-vault-access

Internal tables and types. External surfaces are in `contracts.md`.

## 1. `secrets` table

`user_version` 0 (today, implicit) → **1**.

```sql
-- v1. Changes from v0 marked.
CREATE TABLE IF NOT EXISTS secrets (
    key          TEXT PRIMARY KEY,
    origin       TEXT NOT NULL DEFAULT 'provider',  -- NEW: 'direct'|'provider'
    annotation   TEXT,                              -- was NOT NULL
    provider     TEXT,                              -- was NOT NULL
    nonce        BLOB NOT NULL,
    ciphertext   BLOB NOT NULL,
    created_at   TEXT,                              -- NEW
    updated_at   TEXT,                              -- NEW
    synced_at    TEXT,                              -- was NOT NULL
    key_provider TEXT                               -- NEW
);
```

Which columns carry a value, by origin:

| Column | `direct` | `provider` |
|---|---|---|
| `annotation` | `NULL` | the `provider://reference` string |
| `provider` | `NULL` | the provider that answered |
| `created_at` | first `put` | first `sync` |
| `updated_at` | last `put` | last `sync` |
| `synced_at` | `NULL` | last successful sync |
| `key_provider` | whichever supplied the key at write time | same |

`origin` defaults to `'provider'` so the upgrade classifies every pre-existing
row correctly without inspecting it: before this feature, `sync` was the only
writer.

AAD is unchanged — the ciphertext is bound to `key.encode("utf-8")`, so a row
moved to a different key name still fails to authenticate.

## 2. `vault_meta` table — the key check value (D7)

```sql
CREATE TABLE IF NOT EXISTS vault_meta (
    id         INTEGER PRIMARY KEY CHECK (id = 1),   -- exactly one row
    nonce      BLOB NOT NULL,
    ciphertext BLOB NOT NULL,
    created_at TEXT NOT NULL
);
```

Holds a **fixed, non-secret plaintext** encrypted under the vault key, with AAD
`b"functualize-vault-check"`. Written by the first store write (`put` or
`sync`), never by `init` — so `init --key-source env` stays read-only and the
vault file still appears on first write.

`opens_with(key) -> bool` decrypts this row and nothing else. Three callers
already need it, which is why it is one predicate rather than four:

| Caller | Question |
|---|---|
| `VaultSource` (D2) | present-but-unopenable vs. absent — without decrypting a secret |
| `vault sync` | has the key rotated since the store was written? |
| `vault status` / `inspect` | `readable` \| `key_unavailable` \| `wrong_key` |

The plaintext is a constant, so this row leaks nothing an attacker does not
already have: it is a known-plaintext check by construction, which AES-GCM is
designed to withstand. It is *not* a key verifier in the KDF sense and must not
be described as one.

**Absent `vault_meta` is a legal state** — a v0 store upgraded in place has no
check row until its next write. `opens_with` returns `None` (unknown) there, and
every caller treats unknown as "proceed as today", so the upgrade never turns a
working vault into a refusing one.

## 3. Upgrade

```python
def _upgrade(conn: sqlite3.Connection) -> None:
    """Idempotent, additive, stamped. Runs inside the existing connection."""
```

- Reads `PRAGMA user_version`; returns immediately at 1.
- At 0: `ALTER TABLE secrets ADD COLUMN …` per new column (SQLite allows one
  per statement), creates `vault_meta`, sets `user_version = 1`.
- Never rewrites, re-encrypts or reads `ciphertext`.
- Nullability is relaxed by *recreating* the table only if the v0 `NOT NULL`
  constraints block a direct insert; SQLite cannot drop a `NOT NULL` with
  `ALTER`. The table is rebuilt with `CREATE TABLE secrets_v1` → `INSERT …
  SELECT` → `DROP` → `ALTER … RENAME`, inside one transaction, preserving
  `nonce`/`ciphertext` byte-for-byte. **This is the one step that touches
  existing rows and needs its own test** (AC-14).

## 4. Internal types

```python
# _config/vault.py
class VaultOrigin(StrEnum):          # NEW
    DIRECT = "direct"
    PROVIDER = "provider"

@dataclass(frozen=True)
class VaultEntry:                    # CHANGED — fields added, three relaxed
    key: str
    origin: VaultOrigin              # NEW
    annotation: str | None           # was str
    provider: str | None             # was str
    created_at: datetime | None      # NEW
    updated_at: datetime | None      # NEW
    synced_at: datetime | None       # was datetime
    key_provider: str | None         # NEW

class Readability(StrEnum):          # NEW
    READABLE = "readable"
    KEY_UNAVAILABLE = "key_unavailable"
    WRONG_KEY = "wrong_key"
    ABSENT = "absent"
```

`VaultEntry` gains fields rather than being split: every consumer wants the
whole row, and splitting it by origin would push an `isinstance` branch into
`list`, `status` and `inspect` alike — trading **primitive obsession** for
**shotgun surgery**.

## 5. Report types — `app/vault.py`

Frozen dataclasses, no field able to hold plaintext. `contracts.md` §2 fixes
their serialized shapes; these are the Python surfaces behind them.

```python
@dataclass(frozen=True)
class VaultInitReport:
    key_provider: str
    created: bool                # False = validated only, nothing written
    key_scope: Literal["user"]

@dataclass(frozen=True)
class VaultMutationReport:       # put and remove
    path: str
    origin: VaultOrigin | None   # None = nothing was there
    created: bool
    replaced: bool
    removed: bool
    updated_at: datetime | None
    warning: str | None          # set only when a *direct* entry was removed

@dataclass(frozen=True)
class VaultInspectionReport:
    path: str
    eligible: bool
    exists: bool
    origin: VaultOrigin | None
    provider: str | None
    reference: str | None
    created_at: datetime | None
    updated_at: datetime | None
    synced_at: datetime | None
    key_provider: str | None
    readability: Readability
    stale: bool | None
    winning_source: str
```

No report carries `value`, `ciphertext`, `nonce` or `key`. That is enforced by a
test that reflects over the dataclass fields, so a future field cannot
reintroduce one silently (AC-10).

## 6. Canonical path resolution

```python
def resolve_canonical_path(app, path: str) -> ResolvedVaultPath
```

1. Rightmost split: `job_name, _, field = path.rpartition(".")`.
2. `resolve_name(job_name, known)` — the existing single naming policy, so the
   Python spelling of a job finds it. No second resolver.
3. Materialize the descriptor; require it runnable.
4. Find `field` among `descriptor.config_fields`, accepting flag spelling
   (`api-token`) and normalizing to the model field name (`api_token`).
5. Require `from_config_model` **and** `secret`.
6. Return the resolved path; **read no input before this returns.**

The vault key it produces is `f"{job_name}.{field}"` — byte-identical to what
`VaultSource._qualified(key, section)` is asked for at run time, because the
config section prefix is `rc.name`, the job's full dotted canonical name. That
identity is the whole reason a stored value resolves, and it gets its own test
rather than being left as a comment.
