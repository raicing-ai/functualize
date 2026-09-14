# Research: vault-sync-providers

## Research question

How should remote providers populate the local encrypted vault without making
normal job execution network-dependent or forcing provider setup for local-only
users?

## Starting point

This branch starts at `origin/master` `aed582e`. Current provider behavior is
built around:

- the `functualize.remote_providers` entry-point group;
- `RemoteProvider` in the internal config protocol module;
- `remote_first()` boot admission;
- `vault sync` as the network-touching operation;
- a local encrypted SQLite vault used during later runs.

The previous vault-access branch also explored direct local writes, audit records,
retention, and provider-free boot. Those concerns must be separated here.

## Findings

1. Sync is correctly isolated from ordinary job execution. Preserve that
   invariant: a job run must never fetch a remote provider implicitly.
2. Provider identity and source provenance are valuable metadata, but references
   and key names may themselves be sensitive. “Not plaintext” does not mean
   “non-sensitive”.
3. A sync operation needs clear per-key outcomes: stored, skipped, missing,
   unauthorized, unavailable, invalid reference, and decryption/storage error.
4. Partial success is useful for interactive work, but CI needs a reliable
   non-zero exit and machine-readable output.
5. Provider installation and provider authentication are different failures and
   should not collapse into a generic “provider missing” message.
6. Provider contracts should be settled by `feat/plugin-host-protocol` before
   broad provider/plugin edits begin.
7. Remote sync should populate an explicit local profile or environment bundle
   eventually, rather than assuming one flat global vault is the only model.

## UX scenarios to specify

- first sync with one provider missing;
- first sync with a provider installed but credentials unavailable;
- one provider returning five values with two failures;
- rotation followed by sync;
- stale local values when the remote system is offline;
- dry-run/preview that does not overwrite the local vault;
- CI sync with JSON output and no interactive prompts;
- audit/provenance inspection without exposing values.

## Open decisions

- Keep `remote_first()` strict, or add a separate local-vault preset and make
  remote sync opt-in.
- Whether sync overwrites automatically, requires a diff/confirmation, or
  supports `--force`.
- Whether remote references are retained in metadata after local set/replace.
- Retention and redaction policy for provider names, references, and audit rows.
- Whether provider failures are retryable and whether retries belong in the
  provider or the sync coordinator.
- Whether a future bundle/profile is the unit of sync rather than an individual
  key.

## Recommendation

Build this only after the provider contract and local-vault UX are settled.
Keep the sync coordinator provider-neutral, preserve offline execution, expose
structured results, and make overwrite/provenance behavior explicit. Do not
introduce cloud-specific behavior into the core vault store.

