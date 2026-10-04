# Scoped Vault Secrets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address every local vault entry by `(scope, target, field)` and resolve secret-marked group options and job config fields with vault above environment.

**Architecture:** A small, stdlib-only identity codec gives direct writes, sync, reads, and metadata one storage key. The shared resolution chain carries a group/job scope to its sources; its vault and environment sources interpret that scope, while file and default sources keep their existing section lookup. A public app seam validates targets against discovered job and group schemas before the CLI reads a value.

**Tech Stack:** Python, Pydantic, Click, SQLite, AES-GCM, pytest, Ruff, import-linter.

**Spec:** `.spec/features/vault-scoped-secrets/spec.md`; approved [Shape Intent, SD page 12779576, v2](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/12779576).

## Global Constraints

- Vault targets are secret-marked group options or secret-marked job config fields; function parameters remain invocation inputs.
- `put`, `inspect`, and `remove` require `--field` and exactly one of `--group` or `--job`; remove the positional form and its documentation.
- `[[vault_secret]]` declares exactly one scope, `field`, and `source`; inline provider annotations in secret config fields fail with replacement guidance.
- Resolve `runtime override > explicit command-line value > vault > environment > config file > model default` for both scopes.
- An absent entry falls through; a present unreadable entry refuses; a job run never fetches from a remote provider.
- Refuse old-format stores and tell the operator to run `func builtin vault clear`; clear works without a key and performs no migration.
- Keep `_config`, `_engine`, and `_discovery` independent, `_cli` on public APIs, and unused vaults off the heavy import path.
- Keep all outputs and errors free of secret values. Preserve direct/provider origin conflicts and sync's per-entry failure reporting.

## Review Focus

1. A group and job with identical target/field text must remain distinct on disk, including after list/inspect/remove (Tasks 1, 2, 5).
2. A secret inherited from `deploy` by `deploy.web.run` must use the declaring group's identity; a nearer declaration must use its own (Tasks 2, 3).
3. `put --stdin` with an invalid target must fail before reading stdin; `put` with both scope flags must fail as usage (Task 5).
4. A version-1 vault, including one opened without a key, must refuse reads/writes without mutation while `clear` still works (Task 1).
5. Duplicate provider declarations in different files and a legacy inline URI hidden below an environment value must fail without fetching or exposing a value (Task 4).

---

## Alignment

The page's `Authority` field is `Approved` (SD 12779576 v2, read 2026-10-04). Its in-scope words are: “local project-vault entry identity; `func builtin vault put`, `inspect`, `remove`, `list`, `sync`, `status`, `init`, and `clear` where their output or entry handling is affected; group and job config resolution; corresponding documentation.” Its out-of-scope words are: “share/redeem and FuncCloud delivery, general plaintext reveal/export commands, and migration of the old vault format.” The plan does not add a migration or a new reveal surface.

The approved page says the vault targets “secret-marked group options and secret-marked job **config fields**” and that “Ordinary job function parameters remain invocation inputs and are not vault targets.” It retains command-line values, environment variables, config files, and runtime overrides as sources.

## Architecture gate

### BEFORE: flat identity and split group environment path

```text
_discovery/ → _types/descriptors.py (FieldDescriptor.secret, GroupOptionsSpec)
                        ↓ public descriptor
app/vault.py (job-only path split) → _config/vault.py (SQLite key = job.field)
_cli/vault_cmd.py → app/vault.py and app/utils.py (sync scans inline URI)
                                        ↓
_app/boot.py → _config/chain.py → _config/vault_source.py (flat section.field)
                 ↑                    → _config/sources.py (JOB_FIELD env)
_engine/executor.py → injected JobConfigView → _config/job_config.py
                                                └→ direct GROUP__FIELD env read
```

Arrows show call or import direction; the engine receives config behavior through the composition root rather than importing `_config`. `app/vault.py` is the public cross-layer seam and the CLI uses that seam. The separate group environment read in `resolve_job_config` outranks the chain that contains the vault. Flat `section.field` erases whether the section was a group or a job.

**Existing smells:** *Primitive Obsession* in the positional path split and string `section.field` key (`app/vault.py:resolve_canonical_path`, `_config/vault_source.py:_qualified`); *Shotgun Surgery* across `vault_put`, `vault_sync`, `VaultSource`, and CLI reports when key shape changes; *Divergent Change* in `app/utils.py`, whose sync, file flattening, status, and unrelated utilities share a large module; and a duplicated resolution rule in `_config/job_config.py:resolve_job_config` (group environment outside `ResolutionChain`). These names follow the Refactoring.Guru catalogue in the `design-patterns-refactoring` skill.

### AFTER: one identity, one scoped resolution path

```text
_discovery/ → _types/descriptors.py ──────→ app/core.py (group schema query)
                                             ↓ public API
_cli/vault_cmd.py → app/vault.py ────────→ _primitives/vault_identity.py
                    ↑                         ↑             ↑
                    └──────── app/utils.py    │             │
                               (sync) ────────┘             │
                                    ↓                       │
                              _config/vault.py (v2 guard, encoded key)

_app/boot.py → _config/chain.py (scope argument) → _config/vault_source.py
                   ↑                            → _config/sources.py (scope env)
_engine/executor.py → injected JobConfigView → _config/job_config.py
                         (group/job scope; no direct environment read)
```

The identity codec stays in `_primitives` (stdlib-only). The public app seam may consult discovery metadata and `_config` storage without creating a peer-layer import. The chain stays provider-neutral: it passes the scope to every `Source`; each source decides whether scope affects its lookup. The CLI remains a renderer and input collector. `vault_secret` parsing and validation are shared by boot-time missing-entry diagnostics and `vault_sync`; only sync fetches.

**Candidate AFTER check:** Putting identity validation inside `_config` would introduce a forbidden peer import from discovery, so validation stays in `app/vault.py`. A separate group-specific chain would duplicate precedence and invite *Divergent Change*, so one chain carries a scoped request. Moving the entire vault lifecycle into `app/utils.py` would deepen its existing *Divergent Change*; new declaration parsing is a focused module and sync keeps its public function as a thin coordinator. A broad rename of `Source` is unnecessary; append a keyword-only scope with `"job"` default and update concrete implementations and test doubles together.

**Design references consulted:** repository `python-design-patterns` (KISS, single responsibility, composition over inheritance) and workspace `design-patterns-refactoring` (Primitive Obsession, Shotgun Surgery, Divergent Change); `contributor/architecture/codemaps/{overview,modules,dependencies,data-flow,entry-points}.md`; zvec-grep prose index; Serena symbol and reference queries; graphify neighbor queries. The intended shape follows the import-linter dependency rules in `pyproject.toml`.

## Surviving smells

*Divergent Change* remains in `app/utils.py`, because `vault_sync` stays at its established public import location while its declaration parser moves to a focused module. This is accepted for this feature: moving unrelated public utilities would expand the diff without improving scoped identity. It does **not** need maintainer review to execute. No forbidden pattern is accepted in the AFTER design. The group schema query may touch both cached and dynamic registration, but it exposes one answer through the app seam rather than scattering discovery logic into callers.

## Interfaces and file map

| Unit | Responsibility and interface |
| --- | --- |
| `_primitives/vault_identity.py` (new) | `VaultIdentity(scope: Literal["group", "job"], target: str, field: str)`; `encode() -> str`, `decode(key: str) -> VaultIdentity`. JSON array encoding is unambiguous even when target contains dots. |
| `_config/vault.py` | Store v2 identity strings as existing SQLite `key`/AES-GCM AAD; refuse pre-v2 database before schema writes or secret reads. `clear()` bypasses the guard. |
| `app/core.py`, `app/vault.py`, `_discovery/{cached_provider,pipeline}.py`, `_app/impl.py` | `get_group_options_spec(group_path: str) -> GroupOptionsSpec | None`; `resolve_vault_identity(app, *, group: str | None, job: str | None, field: str) -> VaultIdentity`. Reuse `FieldDescriptor.secret` and `from_config_model`; recognize the declaring group. |
| `_types/protocols.py`, `_config/{chain,sources,job_config,vault_source}.py`, `_engine/executor.py`, `_app/boot.py` | Add `scope: Literal["group", "job"] = "job"` to resolution requests and source `get`/`has`/`keys` lookups; group environment spelling handled by `EnvSource`, after vault. Preserve the generic chain and explicit overrides/CLI precedence. |
| `_config/vault_declarations.py` (new), `app/utils.py` | Read `[[vault_secret]]` from `FileSource.per_file_values`, validate and deduplicate identities before fetch; reuse existing provider parser/fallback behavior for `source`. Replace inline annotation scan as sync input; provide declaration map to vault miss diagnostics. |
| `_cli/vault_cmd.py` | Scoped flags and metadata rendering through the public app seam; update list/status/help messages. |
| tests, guides, ADR | Replace old behavior tests, add scope and security acceptance tests, update configuration and group-options guides, amend ADR-016 and ADR-023 with the new contract. |

The public API may use `VaultIdentity` as a return type, but CLI-facing reports expose separate `scope`, `target`, and `field` fields; callers should not parse encoded keys. Keep `vault_remove`'s orphan-recovery behavior: accept a syntactically valid scoped identity even if the declaration has since disappeared, then delete it without a key.

## Execution tasks

### Task 1: Identity codec and legacy store guard

**Files:** Create `src/functualize/_primitives/vault_identity.py`; modify `src/functualize/_config/vault.py`; test `tests/config/test_vault_store.py` and new `tests/config/test_vault_identity.py`.

**Interfaces:** Produce `VaultIdentity`, its `encode`/`decode`, and `VaultFormatError(VaultError)`. `SecretsVault` continues to accept an encoded string key. Existing encryption, origin, metadata, and keyless `clear` signatures stay intact.

- [ ] Write failing tests: group/job same text encode differently; nested `deploy.service` round-trips; malformed key is refused; a v1 database refuses `list_entries`, `get`, `put`, and `delete` without changing bytes; `clear` removes it without a key.
- [ ] Run `uv run pytest tests/config/test_vault_identity.py tests/config/test_vault_store.py -q`; confirm the new tests fail for the expected missing behavior.
- [ ] Add the codec and v2 format guard before `_connect()` creates/updates schema. Create a fresh v2 store normally; give `VaultFormatError` the exact recovery command. Do not migrate or interpret old rows.
- [ ] Run the same tests and `uv run lint-imports`; require pass.
- [ ] Commit with a conventional subject such as `feat(vault): add scoped storage identity`.

### Task 2: Validate group and job targets through the public app seam

**Files:** Modify `src/functualize/app/core.py`, `src/functualize/app/vault.py`, `src/functualize/_discovery/cached_provider.py`, `src/functualize/_discovery/pipeline.py`, `src/functualize/_app/impl.py`; replace `tests/app/test_vault_paths.py`, extend `tests/app/test_vault_seam.py`.

**Interfaces:** Produce `FunctualizeApp.get_group_options_spec(group_path: str) -> GroupOptionsSpec | None` and `resolve_vault_identity(app, *, group: str | None = None, job: str | None = None, field: str) -> VaultIdentity`. `vault_put(app, identity: VaultIdentity, value: str, ...)`, `vault_inspect(app, identity: VaultIdentity, ...)`, and `vault_remove(app, identity: VaultIdentity, ...)` replace positional paths. Re-export `VaultIdentity` from `app.vault` for public callers. Preserve stable error reasons and metadata-only reports.

- [ ] Write failing tests for `group=deploy, field=token`; `job=deploy, field=token`; nested job `deploy.service`; hyphen/underscore normalization; cached and dynamic group declarations; nonsecret and unknown fields; a secret function parameter rejection; orphan removal without a live declaration.
- [ ] Run `uv run pytest tests/app/test_vault_paths.py tests/app/test_vault_seam.py -q`; confirm the new assertions fail as expected.
- [ ] Implement the discovery-backed group spec query and one scope-aware validator; use existing descriptor secret flags. Change public lifecycle functions and reports to carry typed identity while retaining keyless removal and metadata-only inspection.
- [ ] Run the same tests and `uv run lint-imports`; require pass.
- [ ] Commit as `feat(vault): validate scoped secret targets`.

### Task 3: One precedence path for group and job values

**Files:** Modify `src/functualize/_types/protocols.py`, `_config/{chain,sources,job_config,vault_source}.py`, `_engine/executor.py`, `_app/boot.py`, and source test doubles found by the reference scan; test `tests/config/test_resolution_chain.py`, `tests/config/test_vault_miss.py`, `tests/group_options/test_group_options_injection.py`, and `tests/integration/test_local_vault_e2e.py`.

**Interfaces:** `ResolutionChain.resolve(key: str, section: str | None = None, *, scope: Literal["group", "job"] = "job") -> ResolvedValue`; `Source.get/has(key, section=None, *, scope="job")` and `Source.keys(section, *, scope="job")`; `JobConfigView(..., scope="job")`. `VaultSource` encodes the request as `VaultIdentity(scope, section, key)`. `EnvSource` chooses `GROUP__FIELD` for group scope and existing `JOB_FIELD` for job scope. Other sources ignore scope; `resolve_section` and `introspect` forward it.

- [ ] Write failing tests proving group and job CLI > vault > env > file > default; runtime override > CLI where available; inherited group identity; absent entry fallthrough; stored unreadable entry refusal; explicit static and discovered app parity.
- [ ] Run the named test files with `uv run pytest ... -q`; confirm the new tests fail for precedence/identity, not fixture setup.
- [ ] Thread scope from the engine's injected view through the generic chain; remove the direct group `os.environ` branch; keep `resolve_with_source` and `introspect` aligned with execution. Preserve the dormant vault boot path for projects with no vault file.
- [ ] Run the named tests plus `uv run lint-imports`; require pass.
- [ ] Commit as `feat(config): resolve scoped vault values before environment`.

### Task 4: Explicit provider declarations and legacy inline refusal

**Files:** Create `src/functualize/_config/vault_declarations.py`; modify `src/functualize/app/utils.py`, `src/functualize/_config/vault_source.py`, `src/functualize/_app/boot.py`, `src/functualize/_config/sources.py`, `src/functualize/_config/job_config.py`; replace old sync/miss fixtures in `tests/cli/test_vault_commands.py` and `tests/config/test_vault_miss.py`; preserve provider-parser tests in `tests/config/test_annotation_scan.py`; add `tests/config/test_vault_declarations.py`.

**Interfaces:** `parse_vault_declarations(per_file_values) -> list[VaultSecretDeclaration]` with identity, source, and file location; `vault_sync(app, cwd=None) -> VaultSyncReport` retains its public signature. Validate each identity through `resolve_vault_identity` before provider fetch. Keep provider fallback parsing in its existing parser, using each declaration's `source` rather than an ordinary config value.

- [ ] Write failing tests for two valid blocks, both-scope/missing-field/unknown-field blocks, duplicate identity across files, direct/provider conflict, provider partial failure, unsynced declaration warning with winning source, legacy inline URI under an env override, and ordinary nonsecret URL.
- [ ] Run `uv run pytest tests/config/test_vault_declarations.py tests/config/test_vault_miss.py tests/cli/test_vault_commands.py -q`; confirm the new tests fail as expected.
- [ ] Parse from discovered file values without flattening ordinary sections; validate and deduplicate before any fetch or write; sync with encoded identities. Replace annotation-based miss detection with the declaration map and reject legacy inline syntax for secret-marked fields before a value can reach a job.
- [ ] Run the same tests, `tests/config/test_annotation_scan.py`, and `uv run lint-imports`; require pass.
- [ ] Commit as `feat(vault): sync explicit scoped declarations`.

### Task 5: Scoped CLI and safe reports

**Files:** Modify `src/functualize/_cli/vault_cmd.py`, public report types in `src/functualize/app/vault.py` and `src/functualize/app/utils.py`; test `tests/cli/test_vault_commands.py`, `tests/integration/test_local_vault_no_plaintext.py`.

**Interfaces:** `put`, `inspect`, and `remove` accept `--field` and one of `--group`/`--job`. Human and JSON reports expose `scope`, `target`, `field`, origin and freshness/readability where relevant. No output carries decrypted values.

- [ ] Write failing Click tests for required/exclusive flags, positional rejection, validation before `--stdin`/`--file`/prompt, group/job collision in list/inspect/remove, orphan removal, old-store recovery text, and no secret bytes in JSON, human text, or error streams.
- [ ] Run `uv run pytest tests/cli/test_vault_commands.py tests/integration/test_local_vault_no_plaintext.py -q`; confirm the new tests fail for CLI shape or rendering.
- [ ] Replace positional decorators and old help, route validation through the public seam, and render decomposed identity metadata. Keep status/init/clear usable where they do not need a live app or vault key.
- [ ] Run the same tests and `uv run lint-imports`; require pass.
- [ ] Commit as `feat(vault): expose scoped lifecycle commands`.

### Task 6: End-to-end acceptance, documentation, and durable decision

**Files:** Extend `tests/integration/test_local_vault_e2e.py`, `tests/group_options/test_adapter_entry_point_parity.py`; modify `docs/guides/configuration.md`, `docs/guides/group-options.md`, `contributor/adr/016-remote-source-activation.md`, `contributor/adr/023-local-vault-access.md`, and any old-syntax guide/help hit found by `rg`.

**Interfaces:** No new runtime interface. Acceptance fixture contains group `deploy` token, job `deploy.token` token, job `deploy.service` iam_key, inherited/overridden group options, and a function parameter.

- [ ] Write an end-to-end test: direct write one scope, fake-provider sync another, run with provider networking disabled, assert both precedence ladders and scope collisions, inspect/list without plaintext, reject v1 store without deletion, clear keylessly. Run it and confirm the new assertions fail before remaining changes.
- [ ] Replace old positional and inline annotation documentation, add group vault precedence and breaking-change/clear instructions, and amend ADR-016/023 so their durable contract matches the approved shape.
- [ ] Run `uv run pytest tests/config/test_vault_identity.py tests/config/test_vault_declarations.py tests/config/test_resolution_chain.py tests/config/test_vault_miss.py tests/app/test_vault_paths.py tests/app/test_vault_seam.py tests/group_options/test_group_options_injection.py tests/group_options/test_adapter_entry_point_parity.py tests/cli/test_vault_commands.py tests/integration/test_local_vault_e2e.py tests/integration/test_local_vault_no_plaintext.py -q`; require pass. Run `uv run ruff check` on touched Python paths, `uv run lint-imports`, and `git diff --check`. Search docs/help for removed positional examples and inline provider declarations, reviewing any remaining mentions as historical text only.
- [ ] Commit as `docs(vault): document scoped secrets and precedence` after tests and docs agree.

## Risks and release checks

- **Public source protocol:** Passing `scope` to sources can break third-party `Source` implementations. This is a pre-release breaking change; document it in the release note/ADR and test every in-repo source. Avoid an implicit duck-typed fallback that would silently ignore scope.
- **Cached group metadata:** A cache-only lookup can miss dynamic registration; a dynamic-only lookup can break the standalone CLI's warm path. Task 2 tests both and uses one public app query.
- **Legacy database:** `_connect()` currently creates schema before it inspects version. The v2 guard must inspect an existing file without writing to it; `clear` must bypass `_connect()`.
- **Config merge:** `[[vault_secret]]` arrays in separate discovered files must remain separate for duplicate detection, not be lost to a merged last-wins value. Parse `per_file_values` and carry file location into errors.
- **Secret-bearing diagnostics:** Provider exceptions may contain sensitive data; the implementation must keep the existing output redaction tests and never interpolate fetched values into failures.
- **Branch lifecycle:** Keep `.spec/features/vault-scoped-secrets/` on the feature branch for review. Before merge, migrate durable decisions to ADR/docs and clear branch-only spec artifacts in the repository's required final cleanup commit.
