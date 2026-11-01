# F6: public group secret read

## Authority and phase

- Workflow: repository-native `/agentic-specify`.
- Shape intent: SD/12779576, version 7 (2026-11-01), **F6 amendment**. Its amendment-specific Authority row says **Approved**. The older “Proposed” heading and approval-gate prose were not updated with that row.
- This document describes behavior for confirmation. Architecture, implementation tasks, and execution follow the repository's later gates.

## Problem

A job can receive its own secret-marked configuration, but it has no public way to read the vault secret of a group or Rise subject selected during the run. A job must be able to resolve that target's local secret and pass the resulting `Secret` as an explicit value to its work without creating a new invocation input or exposing plaintext through a CLI.

## User stories

1. As a job author, I can name a group path or Rise subject address and a field at run time and receive the matching secret as a `Secret` value.
2. As an operator, I can provision a more specific environment entry or a shared ancestor entry and know which one the job will read according to the existing group lookup order.
3. As an operator, I can distinguish an absent entry from an existing entry that cannot be opened, and a failed read cannot silently use a different credential.

## Required behavior

### Group lookup

The public call reads **group scope** for the supplied address and field. The address may be a command group path or a Rise subject address. It checks the exact address, then nearest ancestors, under Functualize's active environment. It then repeats exact address through nearest ancestors in the shared/base slot. The first **existing** entry wins, regardless of whether its origin was a direct write or provider sync. The active-environment ancestor therefore wins over a closer shared entry.

The call uses Functualize's already-selected environment. It does not accept a second vault environment, search a job identity, or search another named environment. It preserves the existing scoped storage identity and group ancestor rules. A job run reads the local vault and does not contact a provider; `vault sync` remains the operation that contacts one.

### Outcome and secrecy

A readable selected entry yields its value wrapped in the public `Secret[str]` type. If no candidate entry exists, the call reports a **missing vault entry** to the caller. It does not read environment variables, config files, defaults, or another source to make up a value. If the first existing candidate cannot be opened, the call fails closed at that candidate. It does not continue to an ancestor, shared entry, job entry, other environment, or lower-priority source. The external result and error distinction is defined in `contracts.md`.

The call, its exceptions, and framework diagnostics never put secret bytes in stdout, stderr, logs, or error text. `Secret` rendering remains masked; a job may deliberately unwrap it only at a trusted use site. `vault inspect` and `vault list` remain metadata-only. No plaintext reveal/export CLI command is added.

## Acceptance criteria

1. A real job imports the public call surface, requests `(cloudflare_dev.d1.main, api_token)`, receives a `Secret[str]` from the closest eligible group entry, and passes it as an explicit value to its work.
2. Exact active-environment entry wins. An active-environment ancestor wins over a shared exact entry. Within each tier, the nearest existing ancestor wins. A shared entry is used only after the active tier has no candidate.
3. A same-named job entry and an entry in another named environment are never candidates. The selected environment is the one already active for the run; the shared/base slot is its existing fallback.
4. With no candidate entry, the caller receives the dedicated missing-entry error. A missing vault file has the same absence outcome. No environment, config, default, or other source is substituted.
5. With a stored active entry and a readable shared entry, failure to open the active entry raises a stored-entry read failure. The shared entry is not returned. The same holds for a stored ancestor ahead of later candidates and for direct and provider origins.
6. A job's call succeeds with network access disabled after local provisioning. Provider contact occurs only through explicit `vault sync`.
7. A known marker value never appears in captured stdout, stderr, logs, exception messages, or diagnostics from successful, missing, and unreadable reads. `inspect` and `list` display metadata only.
8. Existing storage identities, vault entries, and group resolution behavior remain usable without rewrite or migration.

## Out of scope

- Job-scope secret reads, general plaintext reveal/export, and new CLI commands.
- New user-supplied job parameters, invocation inputs, or vault environment selection. The injected `Vault` capability is framework-supplied.
- Provider reads during job execution, cross-environment fallback, or changes to vault storage identity.
- Changes to the ordinary config resolution chain's behavior on a vault miss.

## Evidence and open confirmation

- Live shape read: SD/12779576 v7, F6 amendment, Authority **Approved**.
- Repository prior art: ADR-023 (first present entry is authoritative; ordinary config lookup may fall through on a miss), ADR-016 (local read, explicit sync), ADR-012 (injected capability pattern), and ADR-021 (capability access paths must share a single lookup if both exist).
- Current code: `VaultIdentity.lookup_candidates` defines tier and ancestor order; `VaultSource.get` checks presence before key lookup and distinguishes a miss from an unreadable entry; `Secret` is the public masked value type.
- Confirmation requested: the public job-facing signature and dedicated absence exception in `contracts.md`.
