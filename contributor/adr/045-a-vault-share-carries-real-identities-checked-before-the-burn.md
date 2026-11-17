# ADR-045: A Vault Share Carries Real Identities, Checked Before the Burn

**Status**: accepted
**Date**: 2026-11-01
**Deciders**: maintainer (decisions O1–O4, B and the share-selection rules, 2026-10-31 and 2026-11-01)
**Builds on**: [ADR-023](023-local-vault-access.md)

## Context

`func builtin vault share` / `redeem` / `show` hand a project's vault entries to
a teammate through a one-time FuncCloud Vault link, without an account. The
wire API v1 and the EnvelopeV1 crypto are frozen and owned by the funccloud
repository; this repository consumes them (`functualize.app.vault_remote`,
vendored, with the vector file pinned in `tests/vault_remote/vectors.json`) and
never redefines them. What a sender puts in an item and a label, and what a
receiver does with a redeemed bundle, are local choices — this record.

Frozen v1 decides one thing for every choice below: **redeeming spends the
link, and items are readable only afterwards.** Meta (`GET`, no burn) returns
labels, counts and timestamps; the ciphertext needs the redemption token that
only `POST …/redeem` issues.

## Decision

1. **An item is a vault entry under its real identity.** The wire `name` is
   `VaultIdentity.encode()` — the same JSON list that is the store key and the
   AES-GCM associated data — with `kind = "secret"`. No second codec and no
   plain items: `--set NAME=VALUE` and `--from-vault` are removed (O1); an
   environment is handed over as vault entries.

2. **The share is scoped to the sender's active environment, and the receiver
   must match it.** `FUNCTUALIZE_ENV` selects it; there is no vault
   environment flag. Every share carries the label `env:<environment>`; a
   caller label starting `env:` is refused (`bad_label`). Redeem refuses a
   share without one (`not_a_vault_share`) and, when it stores into the vault,
   a share whose `env:` label differs from the active environment
   (`environment_mismatch`, naming the `FUNCTUALIZE_ENV=` to use).

3. **Entries are chosen by `--entry` selector, `--all`, or a picker that starts
   empty — nothing else.** No `--group` / `--job` / `--field` on `share`. A
   selector is `key=value` over `group`, `job`, `field`; a field-less `group=G`
   takes its whole subtree (options of `G` and its nested groups, every field
   of every job in them; a job's group is read from its descriptor, never by
   splitting the registered name). Every selector must match at least one
   shareable entry, so a typo never silently shares less. The picker ticks
   nothing, because sharing is the direction in which a secret leaves the
   machine.

4. **Every check that can precede the burn does (O3).** In order: a project
   with jobs to validate against (`no_project`); a way to confirm — a TTY,
   `-y`, `--only` or `--print-only` (`no_tty_confirmation`); the share still
   live, read from meta (`gone` / `not_found` / `expired`); the environment
   label (decision 2); the receiver's vault key, looked up silently and
   locally — no run ever prompts (ADR-023's key lookup, `vault_require_key`).
   Each refusal sends at most the non-burning meta read and leaves the link
   usable. **Not checkable before the burn under v1**, and disclosed rather
   than hidden: whether the link's own key is right (a wrong one spends a
   redemption and fails `open_failed`), and which items the bundle holds
   (`no_match` and `malformed` rows appear only after it). Closing that gap is
   a funccloud wire v2 question, proposed there (Confluence SD/23822368).

5. **Redeem stores real identities after a confirmation.** Each item becomes a
   row validated with `vault put`'s own checks: `storable` (ticked by
   default), `exists` and `synced` (selectable, unticked), `no_match` and
   `malformed` (not selectable; a bad name is a row, never a crash). `-y`
   takes the storable rows; `--only SEL` takes a subset with the share
   selector grammar; `--replace` changes the default for `exists` and
   `synced`. Writes go only into the receiver's active environment. Applying
   a plan to a bundle other than the planned one stores nothing
   (`plan_mismatch`). Selecting nothing stores nothing, and the command says
   the link is already spent.

6. **Redeem may replace a synced entry (O2).** The row is marked `(synced from
   …)` and starts unticked. Applying it rewrites the entry as direct in one
   store transaction (`vault_supersede_synced`: annotation, provider and
   `synced_at` cleared). By ADR-023 §3 the next `vault sync` then reports that
   identity as a direct entry it will not overwrite; the row says so.

7. **No public plaintext read (B).** `functualize.app.vault._read_value` stays
   private, with `app.vault_handoff` its one caller inside the `app/` layer.

8. **Plain-text outputs name what a run resolves.** `--print-only` and
   `--dotenv PATH` store nothing and name each item by its run-time variable:
   `JOB_FIELD` for a job config field, `SCOPE__FIELD` for a group option
   (`env_name_for`, `group_env_name_for`). `--dotenv` is kept for now: an
   explicit opt-in writing a 0600 file, needing no project. A value the dotenv
   reader would substitute (it contains `${`) is refused per entry, the rest
   are written, and the run exits 3 with `dotenv_interpolated`.

9. **No top-level alias (O4).** The verbs live under `func builtin vault` like
   every other vault command; `BUILTIN_NAMES` stays `{builtin}`, so a
   project's own `vault` job or group remains reachable.

10. **`base` is the shared slot at the identity.** `VaultIdentity` folds an
    environment of `base` to no environment, so `FUNCTUALIZE_ENV=base` and a
    `config.base.*` declaration address the same entry instead of a fourth
    environment no other run consults.

## Consequences

### Positive

- One identity spelling from store to wire to store: a shared entry lands in
  the receiver's vault under the identity a run resolves, with no mapping.
- A wrong project, environment, missing key or dead link costs the receiver
  nothing: the link stays redeemable.

### Negative

- A mistyped but well-formed link, an item with no match in the receiver's
  project, and an aborted prompt are each found only after the link is spent;
  the remedy is a fresh share.
- A redeemed synced entry stops syncing until it is removed.
- `--dotenv` writes plaintext to a path the user names, with no guard against
  an un-ignored path in a git working tree; revisit if one is wanted.

### Neutral — deferred

- **Sharing shared entries.** The local seam writes only into the active
  environment, so an entry resolving only through the shared slot is not
  shareable ("sharing shared entries is not supported yet") until import gains
  an explicit-slot write.
- **A `vault.remote_origin` settings key.** Origin is `--origin` >
  `FUNC_VAULT_ORIGIN` > the public FuncCloud vault; the settings key is not
  declared, so it is reported as unknown.
- Account-bound sync, team wrapping and passphrase (`k2.`) links are later
  funccloud chain items.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Plain `NAME=VALUE` items (`--set`, `--from-vault`) | Shares values outside the vault | A second naming scheme beside `VaultIdentity`; not how an environment is handed over | O1 |
| Redeem into a chosen environment or scope (`--into-vault`, `--scope`) | Receiver picks the slot | The seam writes only the active environment; a mismatch would store where no run looks | Environment must match (decision 2) |
| `--group` / `--job` / `--field` flags on `share` | Mirrors `vault put` | Cannot express subtrees or several entries in one share | `--entry` / `--all` only |
| A picker with everything ticked | Fewer keystrokes | Over-shares by default in the direction a secret leaves the machine | Starts empty |
| A public `vault_get` returning plaintext | Simpler caller | A plaintext door any layer could use | B |
| A top-level `func vault` alias | Shorter to type | Shadows a project's own `vault` job or group | O4 |
| Pre-checking the link key against meta | Refuses a wrong link before the burn | Frozen v1 meta carries no key-check value | Funccloud wire v2 proposal |
