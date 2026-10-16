# Scoped vault v3 — execution tasks

The current phase is Plan. These tasks are unchecked until the maintainer reviews the list and the surviving smell in `plan.md`. Execute uses only its fixed context anchor. In each task, name the production path, commit before sabotage, demonstrate a targeted regression test fails when the path is broken, restore, then check the task and record the wave in `.spec/STATE.md`. A later-wave gate does not make an earlier unchecked task complete.

## Wave 0 — refresh and identity

- [x] **T0.1 — Refresh the branch against current master.** Files: the confirmed `.spec/features/scoped-vault-v3/spec.md` and `contracts.md` plus any paths Git reports as conflicts. Preserve their approved behavior; do not import unrelated implementation into this feature. Acceptance: the branch contains current `origin/master`, its diff still describes the confirmed contract, and `git diff --check` passes.
- [x] **T0.2 — Encode the full identity and lookup candidates.** Files: `src/functualize/_primitives/vault_identity.py`, `tests/config/test_vault_identity.py`. Acceptance: shared keys retain byte-for-byte v2 encoding; environment keys are distinct and case-folded; group candidates are active environment then shared, nearest address first within each; job candidates are exact; malformed keys refuse. Production path: booted `VaultSource.get` and public vault operations consume this type. This is a foundation task; it remains transitional until those consumers are wired in later waves.

## Wave 1 — declaration and run resolution

- [x] **T1.1 — Parse composed declarations and file slots.** Files: `src/functualize/_config/vault_declarations.py`, `tests/config/test_vault_declarations.py`. Acceptance: group, group+leaf-job, and ungrouped leaf-job blocks map to distinct identities; dotted job values refuse with composed guidance; base/unslotted and named overlays have distinct environment identities; duplicate detection uses all four parts. Production path: `vault_sync` and `VaultSource._declared_identities` call the parser.
- [x] **T1.2 — Wire active environment and ordered vault reads.** Files: `src/functualize/_app/boot.py`, `src/functualize/_config/vault_source.py`, `tests/config/test_vault_source_lazy.py`, `tests/config/test_vault_miss.py`. Acceptance: boot injects the selected environment; a group read walks active ancestors before shared ancestors; a job read stays exact; a present unreadable candidate stops; a missing entry falls through without touching a key provider. Production path: boot → ResolutionChain → VaultSource.get → SecretsVault.get. The `VaultSource` constructor may keep a test-only default, but production must pass the app environment explicitly.

## Wave 2 — public mutation and sync

- [x] **T2.1 — Validate composed targets and inspect the winner.** Files: `src/functualize/app/vault.py`, `tests/app/test_vault_paths.py`, `tests/app/test_vault_seam.py`. Acceptance: `--group G --job J` resolves exactly `G.J`; dotted job and misplaced leaf refuse before input; direct mutation uses the active environment; remove acts on its exact key; inspect reports the candidate used without decrypting a secret; v2 shared entries remain inspectable. Production path: public vault API → validation → SecretsVault and the same candidate order used by the run source.
- [x] **T2.2 — Sync only selected declarations.** Files: `src/functualize/app/utils.py`, `tests/app/test_remote_first.py`. Acceptance: a prod sync validates and fetches base+prod declarations and never contacts a staging-only provider; canonical duplicate/origin conflict checks run before fetch; provider failure reports contain no secret bytes. Production path: public `vault_sync` → active FileSource values → parser → provider → SecretsVault.

## Wave 3 — delivery and documentation

- [ ] **T3.1 — Expose composed flags and redacted environment metadata.** Files: `src/functualize/_cli/vault_cmd.py`, `tests/cli/test_vault_commands.py`. Acceptance: put/inspect/remove accept the three approved target forms; output spells grouped jobs with both flags and names selected/defaulted environment; list and inspect identify exact stored/resolved identities; errors and JSON contain no secret bytes. Production path: `func builtin vault` → public `app.vault` / `app.utils`. Cover both `func` and an app where the command is exposed.
- [ ] **T3.2 — Update durable and user documentation.** Files: `docs/guides/configuration.md`, `CHANGELOG.md`, `contributor/adr/016-remote-source-activation.md`, `contributor/adr/023-local-vault-access.md`. Acceptance: examples use composed grouped-job flags, explain `base` and active environment, ancestor order and exact removal, preserve offline runs, and remove the unreleased old dotted-job instruction. No plaintext appears in examples.

## Wave 4 — integration and handoff

- [ ] **T4.1 — Prove the end-to-end contract and hand off the joint gate.** Files: `tests/integration/test_local_vault_no_plaintext.py`, `tests/group_options/test_adapter_entry_point_parity.py`, `examples/standalone/secrets_lab/tests/test_vault_lifecycle.py` as indicated by the new tests' real call paths. Acceptance: a nested job reads the grouped-job entry on both entry surfaces; group/job identities stay distinct; v2 ciphertext decrypts; wrong-key fallback stops; provider access happens only during sync; metadata stays redacted. If class discovery has landed, add the canonical subject operation test here; if it has not, record R7.4 as the second prerequisite's release gate, with the exact API it must call. Run repository lint, type, import, and bounded test gates, then record dead-code delta over the dispatch base and delivered head. This is a checkpoint task, not a permission to declare untested subject integration complete.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["T0.1"]},
    {"id": 1, "tasks": ["T0.2"]},
    {"id": 2, "tasks": ["T1.1"]},
    {"id": 3, "tasks": ["T1.2"]},
    {"id": 4, "tasks": ["T2.1"]},
    {"id": 5, "tasks": ["T2.2"]},
    {"id": 6, "tasks": ["T3.1"]},
    {"id": 7, "tasks": ["T3.2"]},
    {"id": 8, "tasks": ["T4.1"]}
  ]
}
```
