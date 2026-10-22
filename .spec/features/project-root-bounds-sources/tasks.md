# Tasks — project root bounds discovered sources (D1a · D2b · D3b/B1)

Execute is **not** authorized until the member answers **D4** (`plan.md` § D4) and reviews this list and `plan.md` § *Surviving smells*.

## Baseline (authoring time, branch `f30285c`, `func` from `uv sync --frozen --all-extras --all-packages`, `HOME`/`XDG_*` isolated)

Tree: `outer/.functualize.toml` (empty unless stated) and `outer/.functualize/jobs/outer_only.py`; `outer/nested/.functualize.toml` = `root = true`; nested job `nested_only`. Run from `outer/nested` unless stated.

| Gate | AC | Baseline | Must be after |
|---|---|---|---|
| G1 job list | AC1 | `['nested-only', 'outer-only']`; `func outer-only` runs | `['nested-only']`; `Unknown command`, exit 1 |
| G2 ancestor `jobs_directories = ["shared"]` | AC2 | `+ shared-job` | absent |
| G3 ancestor `extra_directories = ["extra"]` | AC3 | `+ extra-job` | absent |
| G4 ancestor `.functualize/lib/outerlib.py`, nested job imports it | AC3 | `LIB 1` | `ModuleNotFoundError` |
| G5 nested file emptied | AC4 | both jobs | unchanged |
| G6 no ancestor file; nested `root = true` + `jobs_directories = ["../shared"]` | AC5 | `['nested-only', 'shared-job']` | unchanged |
| G7 warm cache (union), then the set shrinks | AC7 | warm boot correct | G1–G6 identical cold and warm |
| G8 ancestor `[cli] show_timing = true`; `FuncSettingsStore.discover().resolve()` | AC9 | chain lists the ancestor file, value `true` | ancestor absent, default |
| G9 N4: nested `root = true` + `jobs_directories = ["jobs"]`, **no** nested `.functualize/`; ancestor `.functualize/plugins/audit_log.py` (copied from `examples/project/shared_plugins`) | AC3, AC10 | `[audit] nested-only: success`; `builtin data show` → `Mode: project (… outer/.functualize)` from `nested` **and** `nested/sub` | no `[audit]` line; `Mode: standalone`; the same freshness path from `nested` and `nested/sub`, under XDG cache, keyed by `outer/nested` |
| G10 N4 ancestor data intact | AC10 | — | `sha256` of every file under `outer/.functualize/` and `$XDG_DATA_HOME/functualize/vaults/<id(outer)>/` unchanged across the runs |
| G11 standalone control (no root, no `.functualize/`) | H2 | different freshness ids from `dir` and `dir/sub` | unchanged |
| G12 N9: nested `root = true`, ancestor `config.base.toml` `[greeter.greet] greeting="ANCESTOR"` | AC11 | `GREETING = ANCESTOR` | `GREETING = hello-default` |
| G13 N9 + nested `config.base.toml` without the key | AC11 | `ANCESTOR` | `hello-default` |
| G14 N9 + nested base and `config.dev.toml` (`ENVIRONMENT` default `DEV`) | AC11 | overlay wins over base | unchanged order inside the root |
| G15 G12 with nested `root = true` removed | AC11 control | `ANCESTOR` | `ANCESTOR` |
| G16 user-global `$XDG_CONFIG_HOME/<app>/` job value under a root | AC11 | not measured | still applies |
| G17 `--config-directory nested/cfg` (key missing), ancestor has it | D4 | `ANCESTOR` | D4 (a): `hello-default` |
| G18 programmatic `FunctualizeApp(name=…)` inside the root tree, then `app.refresh()` | AC11 | not measured | same as G12 on boot and after refresh |

## Wave 0 — red gates (disjoint new files)

- [ ] **T1a — Source and settings gates** `[F: tests/cli/test_root_boundary_sources.py (new)]`
  - Gates G1–G8 through the public CLI, using the `_run_func` idiom (`uv run --project <repo> func …`, `tests/cli/test_eliminate_fallback_e2e.py:75-86`) with `HOME`/`XDG_*` under `tmp_path`. G8 runs in-process with `monkeypatch.chdir`.
  - Acceptance: on HEAD, G5 and G6 pass; G1–G4, G7 (union case) and G8 fail with the baseline values. Record the counts here. Commit the red tests.
- [ ] **T1b — Identity and state gates** `[F: tests/cli/test_root_boundary_identity.py (new)]` `[real_state_root]`
  - Gates G9–G11. Mark it `real_state_root`: the subject is the state path itself, so the autouse sandbox must not redirect it (marker defined in `pyproject.toml` `[tool.pytest.ini_options].markers`). G10 hashes the ancestor files before and after.
  - Acceptance: on HEAD, G9 fails (the `[audit]` line and the ancestor `Mode`), G10 passes trivially, and G11 passes.
- [ ] **T1c — Job-config gates** `[F: tests/cli/test_root_boundary_job_config.py (new)]`
  - Gates G12–G18, with a `BaseModel` config parameter whose table is `[greeter.greet]`. Print the value **and** the contributing file, using `func builtin info --job greeter.greet` (*JobConfig* table, `Source` column), as the shape's "Required falsifiers" demand.
  - Acceptance: on HEAD, G12, G13 and G17 fail; G14 and G15 pass; G16 and G18 record their HEAD value in this task.

## Wave 1 — the one owner of "where a project stops"

- [ ] **T2 — `_primitives/project_root.py`, and move walk C into it** `[F: src/functualize/_primitives/project_root.py (new), src/functualize/_primitives/locator.py, src/functualize/_primitives/cache_format.py, src/functualize/_primitives/fresh_format.py, src/functualize/_config/vault_paths.py, src/functualize/_config/project_dirs.py, src/functualize/_app/impl.py, src/functualize/_app/__init__.py, tests/primitives/test_project_root.py (new)]`
  - Inputs: `plan.md` § Technical approach 1–2.
  - Create the module: `PROJECT_CONFIG_CANDIDATES` and `_extract_functualize_section` (moved verbatim from `project_dirs.py:106-138`), `is_root_config`, `project_config_at`, `find_project_boundary`, `find_functualize_dir` (moved from `locator.py:484-523`, docstring kept, now bounded), `project_identity_dir`.
  - The 7 importers switch their import line only. `cache_format`/`fresh_format` keep the **unqualified** binding.
  - Gate G-C: `rg -n "find_functualize_dir" src plugins --type py | rg "_primitives.locator import|^\S+locator.py:\d+:def "`. Authoring time: 2 `import … from locator` lines (`_app/__init__.py:57`, `_app/impl.py:32`), plus 4 multi-line imports (`cache_format.py:29`, `fresh_format.py:43`, `vault_paths.py:37`, `project_dirs.py:44`), plus the definition. After: 0. `rg -n "PROJECT_CONFIG_CANDIDATES\s*[:=]" src` → exactly 1 hit, in `project_root.py`.
  - Unit pins: the boundary for every marker form (N7: `pyproject.toml [tool.functualize]`, `.functualize.toml`, `.functualize/.functualize.toml`); a `pyproject.toml` without the table is not a marker; `"true"` (string) does not stop; `.functualize/` *at* the boundary is found; above it, it is not; identity for N4, N6 and standalone.
  - Acceptance: `uv run pytest tests/primitives/test_project_root.py tests/test_resource_locator.py tests/test_state_root_isolation.py tests/config/test_vault_paths.py -q` green; `uv run lint-imports` clean.

## Wave 2 — walk A, identity fallbacks (disjoint files)

- [ ] **T3 — Bounded walk A** `[F: src/functualize/_config/merge.py, src/functualize/_config/project_dirs.py, tests/config/test_merge_config_layers.py, tests/config/test_project_dirs.py]`
  - `merge_config_layers` uses `is_root_config` (default key); `project_config_layers(cwd, *, search_ancestors=True)`; `resolve_project_config` uses it. Gate G-A (`project_dirs.py` part): `rg -n "resolve_all_candidates\(PROJECT_CONFIG_CANDIDATES\)" src/functualize/_config/project_dirs.py` → 1 hit, inside `project_config_layers`.
  - Acceptance: the 14 tests of `test_merge_config_layers.py` pass unmodified; `tests/cli/test_config_upward_walk.py tests/config/test_project_dirs.py` green.
- [ ] **T4 — Standalone identity keyed by the boundary** `[F: src/functualize/_primitives/cache_format.py, src/functualize/_primitives/fresh_format.py, src/functualize/_config/vault_paths.py]`
  - Standalone ids at `cache_format.py:316` and `fresh_format.py:151` become `compute_project_id(str(find_project_boundary(start) or start))`; `vault_paths.project_root_for` returns `project_identity_dir(start)`.
  - Gate G-ID (this task's part): those 2 `compute_project_id(str(start))` hits → 0.
  - Acceptance: T1b G9 (state half), G10 and G11 green; `tests/test_state_root_isolation.py tests/config/test_vault_paths.py tests/cli/test_state_mode_report.py` green.

## Wave 3 — consumers (disjoint files)

- [ ] **T5 — `app/utils.py`** `[F: src/functualize/app/utils.py]`
  - `auto_discover` (both branches) and `list_project_config_files` read `project_config_layers` (D1). Vault-key ids at `:1884` and `:2049` use `project_root_for`.
  - Gate G-A: `rg -n "resolve_all_candidates\(PROJECT_CONFIG_CANDIDATES\)" src plugins` → exactly 1 (authoring: 4; this task removes `utils.py:510`, `:932`, `:988`). Gate G-ID: `rg -n "compute_project_id\(Path\(cwd\)" src/functualize/app/utils.py` → 0 (authoring: 2).
  - Reachability: commit, then revert `auto_discover` to the inline walk and watch G1–G4 go red; restore. Repeat for `list_project_config_files` with G8.
  - Acceptance: T1a all green; `tests/cli/test_auto_discover.py tests/test_auto_discover.py tests/test_auto_discover_bug_condition.py tests/test_auto_discover_preservation.py tests/cli/test_func_settings_store.py tests/cli/test_single_file_cwd_isolation.py` green.
- [ ] **T6 — Walk B, both stages (B1), and the vault key id** `[F: src/functualize/_app/boot.py]`
  - `discover_config_path` stops at `find_project_boundary(cwd)` when that is reached before `~`. `build_resolution_chain`'s `FileSource` locator uses `stop = find_project_boundary(Path(config_path)) or Path.home()` (D4 (a)). `build_vault_source` (`:1319`) uses `project_root_for(Path.cwd())`.
  - Reachability: the production path is `FunctualizeApp` boot → `_app/boot.py:1013` → `discover_config_path`; boot and `refresh()` → `_app/impl.py::_build_resolution_chain` → `build_resolution_chain`. Sabotage each stop separately (commit first): reverting stage 1 turns G12 red; reverting stage 2 turns G13 red.
  - Acceptance: T1c all green, G17 per D4; `tests/config/test_env_overlay_properties.py tests/config/test_legacy_ini_project.py tests/app/test_remote_first.py tests/app/test_vault_seam.py tests/integration/test_local_vault_e2e.py` green.
- [ ] **T7 — `_app/impl.py` identity** `[F: src/functualize/_app/impl.py]`
  - The state locator (`:81-92`) and `build_cached_provider` (`:146-159`) take the standalone id from `project_identity_dir`; `ancestor_search=False` (child projects, ADR-011) unchanged.
  - Gate G-ID: `rg -n "compute_project_id\(str\((cwd|project_root)\)\)" src/functualize/_app/impl.py` → 0 (authoring: 2, `:92` and `:159`).
  - Acceptance: T1b all green (including G9's plugin half, via T2's bounded walk C); `tests/discovery/test_child_project_cache.py tests/discovery/test_cached_provider_wiring.py tests/integration/test_cold_warm_history_parity.py` green.

## Wave 4 — migration proof and the record

- [ ] **T8 — Verified migration procedure and docs** `[F: tests/cli/test_root_boundary_migration.py (new), docs/guides/configuration.md, CHANGELOG.md, contributor/architecture/codemaps/modules.md]`
  - The test replays N4 with real data, first on the pre-fix build (via a git worktree of `f30285c`). Ancestor `runs.json`/`scopes.json` come from running jobs, and a vault entry comes from `func builtin vault put`, with `FUNCTUALIZE_VAULT_KEY` set. Then, on HEAD:
    - (1) nested sees none of it, and the ancestor hashes are unchanged (G10);
    - (2) following `plan.md` § *D2 migration procedure* (`mkdir .functualize`, copy the chosen `runs.json`/`scopes.json`, `func builtin data clear`, `func builtin vault put` again), nested sees the copied runs and its own vault entry, and *not* the ancestor's other vault entries.
  - Docs: a new `docs/guides/configuration.md` section, "Project boundaries and `root = true`", with the shape's declaration table, the four walks, before/after, and the migration steps exactly as the test runs them. `CHANGELOG.md` → `## [Unreleased]` → `### Fixed`: one entry covering sources, settings, job config, and state/vault identity, with both migrations. `modules.md:89`: name `project_root.py` as the owner. No tracker key in any text.
  - Acceptance: `uv run pytest tests/cli/test_root_boundary_migration.py -q` green; `rg -n "root = true" docs/guides/configuration.md` ≥ 1 (authoring: 0).

## Wave 5 — checkpoint

- [ ] **T9 — Full verification** `[F: none — read-only]` `[verify-e2e:cli]`
  - `uv run ruff check src/ tests/ plugins/ examples/`; `uv run ruff format --check …`; `uv run mypy src/`; `uv run lint-imports`; `uv run pytest -x -q --no-header` (log to `/tmp/functualize-pytest.log`); `uv run pytest tests/perf/test_startup_budget.py -q` (R1); `uv run pytest examples/project/shared_plugins/tests -q` (R4, inheritance without a root).
  - AC6: from G1's tree, `func builtin config path` lists no `outer/` file as `✓ used`; `func builtin info` *Config Resolution* names the nested anchor; G9's `Mode:` line says standalone.
  - AC8: T1a–T1c are red on `f30285c` and green on head.
  - `uv run python .github/scripts/dead_code_delta.py origin/master HEAD`: expect no `NEW_DEAD` (`find_project_boundary`, `project_identity_dir`, `project_config_layers`, `is_root_config` each have production callers).
  - Acceptance: every command passes; outputs pasted into the hand-off.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T1a", "T1b", "T1c"] },
    { "id": 1, "tasks": ["T2"] },
    { "id": 2, "tasks": ["T3", "T4"] },
    { "id": 3, "tasks": ["T5", "T6", "T7"] },
    { "id": 4, "tasks": ["T8"] },
    { "id": 5, "tasks": ["T9"] }
  ]
}
```
