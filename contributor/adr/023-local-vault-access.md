# ADR-023: A Vault Entry That Exists Is the Intended Value

**Status**: accepted
**Date**: 2026-09-17
**Deciders**: maintainer, during the `local-vault-access` Plan phase
**Amends**: [ADR-016](016-remote-source-activation.md) §7

## Context

ADR-016 turned `remote_first()` from a lie into a working preset backed by an
encrypted local vault. It answered the question in front of it: a *provider
cache*, filled by an explicit `vault sync`, read offline by a job run.

`local-vault-access` asks a different question. A developer with one local
secret and no cloud account should be able to `init`, `put`, and run an ordinary
job. That turns the vault from a cache into a general local store, and two of
ADR-016's decisions do not survive the change unaltered.

### What ADR-016 §7 decided, and what it was deciding about

> When a declared annotation has no vault entry, resolution continues to the
> next source — and warns… Hard-failing was considered and rejected: it makes a
> first run after adding an annotation impossible, and it removes the escape
> hatch that lets someone work while a provider is down.

That reasoning is correct and is **not** overturned here. It is about a **miss**
— an annotation declared with nothing stored for it.

The case it did not separate out is an entry that **is** stored but cannot be
opened. Today `VaultSource.usable` is false whenever no key is available, so
*every* lookup falls through — including one whose value is sitting in the
store. The operator then runs on a stale environment variable while believing
they are running on the vault's value. That is the silent substitution ADR-016
exists to prevent, arriving through a door it left open.

### What ADR-016 §5 decided about key scope

Two providers ship. The environment provider is user-scoped and says so: *"The
key is shared across a user's projects here… Isolation comes from the separate
files, not from separate keys."* The keychain provider is project-scoped, with
the opposite rationale: *"a keychain user's blast radius is one project rather
than all of them."*

Having both means **which scope applies depends on whether an environment
variable happens to be exported** — and the non-interactive provider wins. So:

```
projects A and B, each with a per-project keychain key
  export FUNCTUALIZE_VAULT_KEY=…    # for one CI experiment
  cd A && func builtin vault sync   # env wins; A rewritten under the shared key
  cd B && func builtin vault sync   # env wins; B rewritten under the shared key
  unset FUNCTUALIZE_VAULT_KEY
  cd A && func deploy               # the keychain key no longer opens A
```

Nothing records which key wrote a row, so today this is silent. Under the
decision below it becomes a hard failure in both projects at once.

## Decision

### 1. Resolution is decided by presence, not by origin

```
vault holds no entry for this path  ->  fall through to env / file / default
vault HOLDS an entry for this path  ->  that entry is the intended value;
                                        if it cannot be opened, refuse the run
```

A stored entry is what the operator meant to use. Falling past it to a
lower-priority source is the failure, not the safety net.

This applies to provider entries as much as to direct ones, because the rule is
about presence and a stored value is stored whatever wrote it. **ADR-016 §7's
fall-through stands unchanged for a miss**: an absent entry still falls through,
and a declared-but-unsynced annotation still warns per key and continues.

Refusing is tolerable only because recovery is cheap, and all three routes are:

- `vault remove PATH` — any origin, **needs no key** (see 3);
- `vault clear` — needs no key, as today;
- `vault sync` — refreshes provider entries from upstream.

CI is structurally unaffected: a fresh runner has no vault file, so no entries,
so nothing to refuse. The exposed case is a cached `~/.local/share/functualize`
plus a rotated key, and (2) makes `sync` report that on the first run rather
than letting the job fail later.

### 2. The store carries a key check value

One non-secret row holds a fixed known plaintext encrypted under the vault key.
Anything can then ask *"is this the key this store was written with?"* without
decrypting a secret.

It is written on the first store write, never by `init`, so
`init --key-source env` stays genuinely read-only. Absent is a legal state — a
store upgraded in place has none until its next write — and every caller treats
absent as "proceed as today", so the upgrade cannot turn a working vault into a
refusing one.

This is a known-plaintext check by construction, which AES-GCM is designed to
withstand. It is **not** a key verifier in the KDF sense and must not be
described as one.

It exists because one question is asked from four places: the refusal in (1)
needs to name a fix rather than surface a decryption error; `sync` must detect a
rotated key instead of silently writing fresh rows beside unreadable ones;
`status` must be able to report a mismatch, which it cannot today; and `inspect`
must report readability while holding no plaintext.

### 3. `remove` takes any entry and never needs the key

Metadata columns are cleartext by design and a delete decrypts nothing, so the
command that rescues an unopenable store must not itself require the key.

An earlier draft refused to remove a provider entry, to protect provenance. That
refusal fired exactly in the case the command exists for — a locked-out store's
unopenable entry is usually provider-written — and the property it protected is
carried instead by the separate rule that **`sync` must never overwrite a direct
entry**. Removing a provider entry is safe: the value is authoritative upstream
and the next sync refills it. Removing a direct entry warns, because that one
has no upstream copy.

### 4. One key per user; the keychain provider changes to match

Both shipped providers are user-scoped. `project_id` stays in the signature of
`get_key` and `initialize_key`, so a third-party KMS or hosted provider may
still scope per project — **key scope is a provider's choice**, and the seam is
unchanged. What is fixed is that the two *shipped* providers now agree.

Made now because it is free now: nothing in the codebase has ever written a
keychain key (`set_password` appears nowhere), no test asserts per-project
keychain scoping, and `KEYCHAIN_SERVICE` is not a public export. Once `init`
ships and begins writing keys, the same change becomes a migration.

### 5. `VaultKeyInitializer` is a separate optional protocol

Key creation is a capability a provider opts into by having the method. Widening
`VaultKeyProvider` would retroactively invalidate every structural
implementation that satisfies it today.

### 6. `init` is a preflight, never a gate

The store is created lazily by the first write, so
`export FUNCTUALIZE_VAULT_KEY=… && func builtin vault sync` continues to work on
a machine where `init` has never run. `init` must never become a prerequisite
for `put` or `sync`.

`keygen` and `init` are not two stages of one sequence: `keygen` prints a key and
stores nothing, for an operator who will place it themselves; `init` persists a
key into a provider and never shows it.

## Consequences

### Positive

- The substitution ADR-016 set out to prevent is closed on the path it left
  open. A stored secret is either used or the run stops.
- A rotated key is reported by `sync` instead of producing rows that can never
  be read again.
- Key scope is one rule instead of two that disagree, so it no longer depends on
  whether an environment variable is exported.
- `inspect` and `status` can report key state truthfully while holding no
  plaintext at any point.

### Negative

- **Losing the one user key now strands every project's vault, not one.** This
  is a real property given up, recorded rather than elided. It was never a
  *system* property — only one provider's, while the primary non-interactive
  route had no such isolation — and an inconsistent guarantee is worth less than
  none.
- An abandoned vault from a past `remote_first()` experiment will start refusing
  runs once the dormant source sees it. Recovery is `vault remove` or
  `vault clear`, both keyless, and the refusal names them.
- `docs/guides/configuration.md` promised the opposite of (1) — *"With no key at
  all the vault does not open. There is no plaintext fallback: resolution falls
  through to the next source"* — and is corrected as part of this change.

### Neutral

- `list --json` gains nullable `provider` / `annotation` / `synced_at`, because a
  direct entry has none of the three. No field is removed or renamed.
- The store gains columns and a one-time in-place upgrade. Additive; existing
  ciphertext is preserved byte-for-byte.

## Alternatives rejected

**Refuse only for direct entries, keep fall-through for provider entries.**
Simpler to justify against ADR-016, and it was the first recommendation put to
the maintainer. Rejected because it makes two kinds of entry behave differently
for a reason the user cannot see, when the honest rule is about presence: a
stored value is the intended value whatever wrote it.

**Keep falling through, and warn louder.** This is what the code does today, and
the warning is already loud. The operator still runs on the wrong value; a
louder message does not change which secret the job received.

**A second table for direct entries**, leaving `secrets` untouched. Avoids the
migration, but every read then consults two tables and merges them, and "which
one wins" becomes a new rule maintained in `VaultSource`, `list`, `status`,
`sync` and `inspect` — shotgun surgery traded for a migration, with the
no-clobber invariant becoming cross-table rather than a column check.
