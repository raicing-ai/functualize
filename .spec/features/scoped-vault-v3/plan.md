# Scoped vault v3 — implementation plan

## Authority and phase

- Workflow: repository native (`AGENTS.md`, `.claude/rules/spec-workflow.md`, `.spec/CONSTITUTION.md`). Phase: Plan. Execute is gated on review of `tasks.md` and the surviving smells below.
- Shape: SD/12779576 page version 5, read live 2026-10-16, `Authority: Approved`. The maintainer confirmed `spec.md` and `contracts.md` on the issue at 11:59 UTC. The page's Status and Last reviewed prose have not caught up with its Authority field.
- Current branch starts from `c03dfb7`; `origin/master` has advanced. Refresh the branch against current master before the first Execute wave, preserving the confirmed spec and checking the vault file diff.
- The class-discovery prerequisite is still blocked. Its interface says the subject-operation integration (R7.4) belongs to whichever prerequisite lands second. This plan makes the vault side address-capable and records an explicit joint verification checkpoint; it does not invent a subject operation job before class discovery exists.

## Architecture evidence and decisions

The Plan architecture pass used zvec-grep for the reasons recorded in ADR-016 and ADR-023, Serena symbol overviews and reference queries for the live API surface, Graphify neighbors for dependency direction, and `rg` for exact callers and file hit sets. Graphify's committed graph predates `VaultIdentity`, so its line references are corroborated against source. The five `contributor/architecture/codemaps/` maps establish the layer directions below. Design guidance consulted: repository `python-design-patterns` and `design-patterns-refactoring` (Refactoring.Guru smell catalogue).

ADR-016 keeps provider calls in explicit `vault sync`; ADR-023 makes a present but unreadable entry terminal and preserves a missing entry's fallthrough. Neither decision changes. `roles.parse_slot` already parses config file environment slots; `FileSource.per_file_values` exposes the active file set. The plan reuses both. `ConfigurationFacade.active_environment()` and `environment_source()` expose the boot-selected environment; `_config` receives it as an input rather than reading process globals. The public vault API remains the route used by `_cli`.

### BEFORE — current call and import directions

```text
PUBLIC app/vault.py (validation and single-entry operations)
  -> INTERNAL _primitives/vault_identity.py (three-part key)
  -> INTERNAL _config/vault.py (encrypted SQLite store)
PUBLIC app/utils.py::vault_sync
  -> INTERNAL _config/vault_declarations.py (exclusive group/job, all parsed files)
  -> INTERNAL _config/vault.py
INTERNAL _app/boot.py (composition root, selected environment)
  -> INTERNAL _config/sources.py::FileSource (active config files)
  -> INTERNAL _config/vault_source.py (exact key lookup, no environment)
       -> INTERNAL _primitives/vault_identity.py
       -> INTERNAL _config/vault.py
INTERNAL _cli/vault_cmd.py (delivery) -> PUBLIC app/vault.py and app/utils.py
```

The `_config` and `_app` import edges comply with the dependency rules; `_cli` crosses only the public API boundary. The existing **Primitive Obsession** is the three string parts interpreted separately in display, sync, and lookup. The `vault_sync` function in `app/utils.py` is a **Long Method** (its function body spans lines 1948–2110 in the inspected branch). A new independent environment resolver in every caller would add **Shotgun Surgery** and risk different answers for writes and reads.

### AFTER — proposed call and import directions

```text
PUBLIC app/vault.py (composed target validation; direct operations and inspection)
  -> INTERNAL _primitives/vault_identity.py (typed scope/target/field/environment;
                                            v2 shared encoding; ordered candidates)
  -> INTERNAL _config/vault.py (unchanged ciphertext/storage mechanism)
PUBLIC app/utils.py::vault_sync
  -> INTERNAL _config/vault_declarations.py (composed target; roles.parse_slot)
  -> INTERNAL _primitives/vault_identity.py -> INTERNAL _config/vault.py
INTERNAL _app/boot.py (one environment selection; injects name and source)
  -> INTERNAL _config/sources.py::FileSource (base + active overlay only)
  -> INTERNAL _config/vault_source.py (ordered candidates; terminal unreadable hit)
       -> INTERNAL _primitives/vault_identity.py -> INTERNAL _config/vault.py
INTERNAL _cli/vault_cmd.py (flags and metadata only)
  -> PUBLIC app/vault.py and app/utils.py
```

The boundary crossing is explicit: `_app` passes the selected environment into the peer `_config` layer; public `app/` may use internal services; `_cli` only calls public `app/`. No peer layer imports another peer. `VaultIdentity` owns encoded identity and candidate order, so lookup and inspect cannot silently disagree about precedence. The candidate AFTER was checked for new smells: putting environment detection in `_config` would create a forbidden peer/boot dependency; putting ancestor logic independently into `VaultSource` and `vault_inspect` would create Shotgun Surgery. Both are excluded. The settled design does not add a new port, singleton, or store.

## Technical approach and file hit sets

1. Extend `_primitives/vault_identity.py` with an optional normalized environment. Keep the exact v2 three-string JSON and associated data for shared entries; use a four-string JSON for qualified entries. Provide ordered group and exact-job candidate identities from this value object. Cover malformed keys and case folding in `tests/config/test_vault_identity.py`.
2. Make `_config/vault_declarations.py` accept group alone, group plus leaf job, or ungrouped leaf job. Use `_config/roles.py::parse_slot` to assign the declaration's environment, and deduplicate by full identity. The active config file set is already selected by `FileSource`; do not contact an inert overlay. Cover this in `tests/config/test_vault_declarations.py`.
3. Inject the active environment from `_app/boot.py` into `_config/vault_source.py`. Resolve candidates in environment-first, nearest-ancestor-first order; refuse on a present unreadable candidate. Keep misses and declaration warnings scoped to the actual candidate set. Extend `tests/config/test_vault_source_lazy.py` and `tests/config/test_vault_miss.py`.
4. In `app/vault.py`, resolve composed group/job input against the job registry while preserving the registered full name as storage target. Reject dotted `--job` early, allow a subject-address group when its secret-marked field is discoverable, and retain keyless orphan removal. Give `put`, `remove`, and `inspect` the app-selected environment; inspection reports the winning exact identity. Extend `tests/app/test_vault_paths.py` and `tests/app/test_vault_seam.py`.
5. Make `app/utils.py::vault_sync` validate declarations using the composed target and full identity, then fetch only active declarations. Use the existing provider scan and origin-conflict behavior. Extend `tests/config/test_vault_declarations.py` and `tests/app/test_remote_first.py`.
6. Update `_cli/vault_cmd.py` for composed flags, environment/source notices, and redacted human/JSON metadata. Round-trip the public API through `tests/cli/test_vault_commands.py`; test the nested-job path through the actual `func` entry point and the app entry point, including cold and warm cache where applicable.
7. Update `docs/guides/configuration.md`, the existing Unreleased vault changelog entry, and ADR-016/ADR-023's obsolete scoped-identity prose. Use the existing spelling in the approved contract; no compatibility alias for the unreleased dotted `--job` form.
8. Verify the joint subject operation path when class discovery exists. If this branch lands first, hand R7.4 to the class-discovery implementation as the interface requires, with the exact vault API and a release-level verification case. Do not mark an unavailable operation job as tested. The core vault path must nevertheless accept a subject address and resolve its ancestors independently of Rise.

## Verification and risks

- Each wave uses its named domain tests, then the repository's `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, and pytest gates. The production call path for each new seam is recorded before its task is checked. Commit first, sabotage that path, observe a targeted test fail, restore, then record the proof.
- Exercise v2 ciphertext without rewriting it; exercise wrong-key and corrupt-ciphertext stops at a nearer candidate; compare `prod`, `staging`, and shared identities; verify sync never calls an inert overlay provider; assert secret bytes are absent from list, inspect, and errors.
- The highest integration risk is a different candidate order in inspection and run resolution. Both must use the value object's order. The next risk is a direct write that silently lands in default `dev`; CLI and public reports must carry the selected/defaulted source.
- `app/vault.py` and `app/utils.py` are broad public modules. Keep changes at the existing seams, avoid changing `SecretsVault` encryption, and run public API plus CLI tests. No new dependency or import-linter contract is planned.

## Surviving smells

- **Long Method** — `app/utils.py::vault_sync`. Its existing provider, key, and partial-failure control flow remains in one function. The environment and target change should be a short validation/filter step using shared helpers; extracting the whole sync workflow would expand this feature into a behavior-preserving refactor. Accepted for this wave; no maintainer review requested beyond the task-list review.
- No new Primitive Obsession or Shotgun Surgery is accepted: the identity value object and one candidate-order implementation hold those rules. No forbidden pattern from `.spec/CONSTITUTION.md` is proposed.
