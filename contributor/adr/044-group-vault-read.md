# ADR-044: A Job Reads a Group's Secret Through One Injected `Vault` Port

**Status**: accepted
**Date**: 2026-11-11
**Deciders**: maintainer (shape amendment and plan approval)
**Builds on**: [ADR-014](014-capability-registry.md), [ADR-016](016-remote-source-activation.md), [ADR-021](021-capability-duality.md), [ADR-023](023-local-vault-access.md)

## Context

A job could receive its own secret-marked config fields, but it could not read
the vault secret of a group or subject it selected while it ran. The approved
shape for that read fixes its boundaries: one public programmatic call taking a
group address and a field, a `Secret` back, the existing local group lookup
under Functualize's active environment — exact group then nearest ancestors,
then the same order in the shared slot, first existing entry wins — a stored
unreadable entry failing closed, no provider contact during a job, and no
plaintext on any surface.

Three things in the codebase decide how that can be built:

- The lookup already exists. `VaultSource.get(field, group, scope="group")`
  walks `VaultIdentity.lookup_candidates` and treats the first stored candidate
  as authoritative even when it cannot be opened (ADR-023 §1).
- Injection lives in `_engine` (the capability registry, ADR-014), and the vault
  source lives in `_config`. They are peer layers: neither may import the other.
- Ordinary config resolution must keep its existing behaviour on a vault miss:
  continue to env, files and defaults.

## Decision

1. **One public call surface: an injected capability.** `functualize.job.Vault`
   is a `@runtime_checkable Protocol` with `read(group: str, field: str) ->
   Secret[str]`. A job declares `vault: Vault`; there is no `RunContext`
   accessor, free function, invocation input or environment/source argument.
   `rc_accessor=None` on its `CapabilitySpec` records that the injected door is
   the only one, so ADR-021's duality rule has nothing to pair.

2. **A typed port crosses the peer boundary; the composition root composes.**
   `_types/protocols.py` defines `Vault` and `VaultReaderFactory.open() ->
   Vault`. `_app/vault_reader.py` implements the factory over the config layer,
   and `_app/boot.build_engine` — the single engine construction site for both
   boot paths — hands it to `JobExecutionEngine` as a keyword-only constructor
   argument. `_engine/capabilities/vault.py` only calls `open()`. No `_engine`
   → `_config` import exists; `lint-imports` keeps all seven contracts.

3. **No second candidate walker.** The adapter makes exactly one
   `VaultSource.get(field, group, scope="group")` call. It never calls the
   chain's `resolve` (which would substitute lower sources on a miss) and never
   names `lookup_candidates`. The order and the first-present rule therefore
   have one definition, shared with config resolution.

4. **Three outcomes, one new error.** A value is wrapped in `Secret` before it
   is returned. `None` from the source — including no vault file — becomes the
   new `VaultEntryMissingError(VaultError)`, carrying only the group and field.
   `VaultEntryUnreadableError` and `VaultDecryptionError` propagate unchanged and
   stop the read at the first stored candidate. All three are exported from
   `functualize.app.vault`. The missing error is raised **only** by this explicit
   read; ordinary config resolution still falls through on a miss.

5. **The source is the app's current one.** The factory holds the app, not a
   source, and each invocation's reader looks up the vault source in the live
   resolution chain, so a `refresh()` is observed. A chain without one (an
   explicit chain, a static app) gets the source boot would build,
   `build_vault_source(app)`: the dormant local source when the project has a
   vault file, otherwise none — a miss. `_config.vault*` is imported only on the
   read path, keeping `cryptography` off cold boot.

6. **An engine without a factory refuses.** An engine built outside
   `build_engine` answers a `Vault` request with `MissingProviderError` rather
   than an inert reader that would report every entry missing.

## Consequences

- Adding the capability touched the registry, the primitive name set, the
  public `job` exports and the shipped capability table together. That is the
  accepted **Shotgun Surgery** ADR-014 already guards with its import-time name
  agreement; the discovery layer still cannot derive the name set from the
  engine.
- `JobExecutionEngine` and `app/vault.py` gained a field and three re-exports
  respectively, and no vault behaviour. Their existing **Divergent Change** is
  unchanged in kind.
- A job-defined type named `Vault` used as a parameter annotation is now treated
  as the injected capability, because discovery matches capability names as
  strings (ADR-014). Rename the user type.
- A secret read this way is not added to the run's output-redaction set the way
  a resolved secret config field is. `Secret` masks every rendering of the
  wrapper; text a job builds from `get_secret_value()` is the job's
  responsibility, as it already is for config secrets after unwrapping.

## Alternatives rejected

- **Import `_config` from `_engine`** — violates *Peer layers are independent*.
- **A candidate walker in `job/` or `_engine/`** — a second copy of the
  first-present policy, free to drift (Shotgun Surgery), and a contradiction of
  the approved lookup.
- **Vault resolution inside `JobExecutionEngine`** — adds a responsibility to an
  already large class (Divergent Change).
- **`RunContext.vault` as well** — a second door to the same read (Middle Man)
  that ADR-021 would then oblige to share one object; the approved contract has
  one call surface.
