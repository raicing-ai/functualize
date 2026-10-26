# Tasks — project root bounds discovered sources (D1a · D2b · D3b/B1)

**Tasks approved by the member 2026-10-26** ("D4 a, smells 2 need to be fixed in this scope, tasks approved"). D4 = (a). Smell 2 was added as T5b–T5d and widens T2 and T5, within the approved shape. **T5d alone waits on D5**; every other task may execute.

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
| G19 `func builtin config path` from `outer/nested/sub` (nested `root = true` in `.functualize/.functualize.toml`) | AC12 / D5 | lists `sub/pyproject.toml` ✗ and `sub/.functualize.toml` ✗ only | D5 (a): lists `nested/.functualize/.functualize.toml` ✓ and nothing under `outer/` |

## Wave 0 — red gates (disjoint new files)

- [x] **T1a — Source and settings gates** `[F: tests/cli/test_root_boundary_sources.py (new)]`
  - Gates G1–G8 through the public CLI, using the `_run_func` idiom (`uv run --project <repo> func …`, `tests/cli/test_eliminate_fallback_e2e.py:75-86`) with `HOME`/`XDG_*` under `tmp_path`. G8 runs in-process with `monkeypatch.chdir`.
  - Acceptance: on HEAD, G5 and G6 pass; G1–G4, G7 (union case) and G8 fail with the baseline values. Record the counts here. Commit the red tests.
  - Observed (2026-10-26, `f30285c` and its merge with `master` `11ed0e8`, identical): `uv run pytest tests/cli/test_root_boundary_sources.py` → **7 failed, 2 passed**. Red: G1, G2 (`+ shared-job`), G3 (`+ extra-job`), G4 (`LIB 1`), G7 ×2 (cold/warm union; warm union after the root appears), G8 (ancestor file in the chain, value `true`). Green: G5, G6.
- [x] **T1b — Identity and state gates** `[F: tests/cli/test_root_boundary_identity.py (new)]` `[real_state_root]`
  - Gates G9–G11. Mark it `real_state_root`: the subject is the state path itself, so the autouse sandbox must not redirect it (marker defined in `pyproject.toml` `[tool.pytest.ini_options].markers`). G10 hashes the ancestor files before and after.
  - Acceptance: on HEAD, G9 fails (the `[audit]` line and the ancestor `Mode`), G10 passes trivially, and G11 passes.
  - Observed (2026-10-26, `f30285c` and the `master` merge, identical): `uv run pytest tests/cli/test_root_boundary_identity.py` → **3 failed, 1 passed**. Red: G9 ×2 (`[audit] nested-only: success`; `Mode: project (… outer/.functualize)`). Green: G11. **Deviation from the authored prediction:** G10 is *red* on HEAD, not trivially green — the test hashes across the nested job run as well as the two reads, and on HEAD that run writes `cache.json`, `runs.json` and a plugin `.pyc` into `outer/.functualize/`. It is the D2 leak itself, so the stronger gate was kept; the Factory Designer may amend the row.
- [x] **T1c — Job-config gates** `[F: tests/cli/test_root_boundary_job_config.py (new)]`
  - Gates G12–G18, with a `BaseModel` config parameter whose table is `[greeter.greet]`. Print the value **and** the contributing file, using `func builtin info --job greeter.greet` (*JobConfig* table, `Source` column), as the shape's "Required falsifiers" demand.
  - Acceptance: on HEAD, G12, G13 and G17 fail; G14 and G15 pass; G16 and G18 record their HEAD value in this task.
  - Observed (2026-10-26, `f30285c` and the `master` merge, identical): `uv run pytest tests/cli/test_root_boundary_job_config.py` → **4 failed, 4 passed**. Red: G12, G13, G17 (`ANCESTOR`), G18 with a root. Green: G14 (`NESTED-DEV` over `NESTED-BASE`), G15 (`ANCESTOR`), G16, G18 without a root. HEAD values: **G16** = `USER-GLOBAL`, from `$XDG_DATA_HOME/functualize/config.base.toml` — the user-global job-config source is `search_platform_user`, i.e. the XDG *data* directory, not `$XDG_CONFIG_HOME/<app>/` as the row says, so the gate uses the real location; **G18** = `ANCESTOR` on boot and `ANCESTOR` after `refresh()` under a root (and without one).

## Wave 1 — the one owner of "where a project stops"

- [x] **T2 — `_primitives/project_root.py`, and move walk C into it** `[F: src/functualize/_types/settings.py, src/functualize/_primitives/project_root.py (new), src/functualize/_primitives/locator.py, src/functualize/_primitives/cache_format.py, src/functualize/_primitives/fresh_format.py, src/functualize/_config/vault_paths.py, src/functualize/_config/project_dirs.py, src/functualize/_app/impl.py, src/functualize/_app/__init__.py, tests/primitives/test_project_root.py (new)]`
  - Inputs: `plan.md` § Technical approach 1–2.
  - Smell 2: in `_types/settings.py`, name the two literals as module constants (`PROJECT_FILE_NAMES`, `PROJECT_FILE_SECTION_PREFIXES`) and point the `SettingsSources` / `AppSettingsSchema` defaults at them. The public API is unchanged.
  - Create the module: `PROJECT_CONFIG_CANDIDATES` **derived** from those constants (a name with a section prefix becomes `(name, extractor for that table)`), replacing `_extract_functualize_section` from `project_dirs.py:106-138`; `project_config_file_table(path) -> (values, prefix)`; `is_root_config`, `project_config_at`, `find_project_boundary`, `find_functualize_dir` (moved from `locator.py:484-523`, docstring kept, now bounded), `project_identity_dir`.
  - The 7 importers switch their import line only. `cache_format`/`fresh_format` keep the **unqualified** binding.
  - Gate G-C: `rg -n "find_functualize_dir" src plugins --type py | rg "_primitives.locator import|^\S+locator.py:\d+:def "`. Authoring time: 2 `import … from locator` lines (`_app/__init__.py:57`, `_app/impl.py:32`), plus 4 multi-line imports (`cache_format.py:29`, `fresh_format.py:43`, `vault_paths.py:37`, `project_dirs.py:44`), plus the definition. After: 0. `rg -n "PROJECT_CONFIG_CANDIDATES\s*[:=]" src` → exactly 1 hit, in `project_root.py`.
  - Unit pin (smell 2): the derived `PROJECT_CONFIG_CANDIDATES` resolves exactly as today's literal list on a fixture with all three files, and with a `pyproject.toml` lacking the table.
  - Unit pins: the boundary for every marker form (N7: `pyproject.toml [tool.functualize]`, `.functualize.toml`, `.functualize/.functualize.toml`); a `pyproject.toml` without the table is not a marker; `"true"` (string) does not stop; `.functualize/` *at* the boundary is found; above it, it is not; identity for N4, N6 and standalone.
  - Acceptance: `uv run pytest tests/primitives/test_project_root.py tests/test_resource_locator.py tests/test_state_root_isolation.py tests/config/test_vault_paths.py -q` green; `uv run lint-imports` clean.
  - Done 2026-10-26. G-C after: **0** (also 0 across multi-line `locator` imports, `rg -U`); `PROJECT_CONFIG_CANDIDATES\s*[:=]` → **1**, `project_root.py:95`. Acceptance (plus `tests/test_locator_candidates.py`): **77 passed**; `lint-imports` 7 kept, 0 broken; `mypy src/` clean. `ROOT_KEY` is exported beside the listed names.
  - Reachability: `func <job>` → `boot_standard` step 3.5 → `_config/project_dirs.py::resolve_project_directories` → `find_functualize_dir` (convention plugins); `func builtin data show` → `fresh_format.resolve_fresh_location` → `find_functualize_dir` (mode). Sabotage (committed first): `if False and _declares_root(current)` in `find_functualize_dir` → T1b `test_g9_ancestor_convention_plugin_does_not_run` **red**; restored with `git checkout --`. With T2 alone, T1b is 3 passed / 1 failed (G9 identity waits on T4/T7).

## Wave 2 — walk A, identity fallbacks (disjoint files)

- [x] **T3 — Bounded walk A** `[F: src/functualize/_config/merge.py, src/functualize/_config/project_dirs.py, tests/config/test_merge_config_layers.py, tests/config/test_project_dirs.py]`
  - `merge_config_layers` uses `is_root_config` (default key); `project_config_layers(cwd, *, search_ancestors=True)`; `resolve_project_config` uses it. Gate G-A (`project_dirs.py` part): `rg -n "resolve_all_candidates\(PROJECT_CONFIG_CANDIDATES\)" src/functualize/_config/project_dirs.py` → 1 hit, inside `project_config_layers`.
  - Acceptance: the 14 tests of `test_merge_config_layers.py` pass unmodified; `tests/cli/test_config_upward_walk.py tests/config/test_project_dirs.py` green.
  - Done 2026-10-26. G-A (`project_dirs.py` part): **1** hit, `project_dirs.py:176`, inside `project_config_layers`. Acceptance: **42 passed** (the 14 merge tests unmodified; 4 new `project_config_layers` pins in `test_project_dirs.py`).
  - Reachability: `func <job>` → `boot_standard` step 3.5 → `resolve_project_directories` → `resolve_project_config` → `project_config_layers` / `merge_config_layers`. Sabotage (committed first): both stops `if False and …` → **5 failed** (`test_root_true_stops_processing`, `test_first_layer_is_root`, `test_custom_root_key`, `test_the_layers_end_at_the_root`, and the boot-path `test_root_true_stops_the_inheritance`); restored. The remaining walk-A consumers (`auto_discover`, `list_project_config_files`) are wired in T5.
- [x] **T4 — Standalone identity keyed by the boundary** `[F: src/functualize/_primitives/cache_format.py, src/functualize/_primitives/fresh_format.py, src/functualize/_config/vault_paths.py]`
  - Standalone ids at `cache_format.py:316` and `fresh_format.py:151` become `compute_project_id(str(find_project_boundary(start) or start))`; `vault_paths.project_root_for` returns `project_identity_dir(start)`.
  - Gate G-ID (this task's part): those 2 `compute_project_id(str(start))` hits → 0.
  - Acceptance: T1b G9 (state half), G10 and G11 green; `tests/test_state_root_isolation.py tests/config/test_vault_paths.py tests/cli/test_state_mode_report.py` green.
  - Done 2026-10-26. G-ID (T4 part): `rg -c "compute_project_id\(str\(start\)\)"` over the two formats → **0** (authoring 2). Acceptance: **22 passed** (T1b 4/4 with T2+T4, plus the three listed files).
  - Reachability: `func builtin data show` → `fresh_format.resolve_fresh_location` (standalone id); `func` CLI fast path → `cache_format.resolve_cache_path`; vault boot → `_build_dormant_vault_source` → `vault_path_for_project` → `project_root_for`. Sabotage (committed first): standalone ids back to `start` and `project_root_for` back to `start` → **3 failed** (T1b `test_g9_root_and_subfolder_share_one_standalone_identity`, and two `test_vault_paths.py` identity tests); restored. Disclosed gap: the *root-without-folder* branch of `project_root_for` has no end-to-end observer until T8 puts a vault entry from the nested root.

## Wave 3 — consumers (disjoint files)

- [x] **T5 — `app/utils.py`** `[F: src/functualize/app/utils.py]`
  - `auto_discover` (both branches) and `list_project_config_files` read `project_config_layers` (D1). Vault-key ids at `:1884` and `:2049` use `project_root_for`. Re-export `project_config_file_table` publicly (consumed by T5b).
  - Gate G-A: `rg -n "resolve_all_candidates\(PROJECT_CONFIG_CANDIDATES\)" src plugins` → exactly 1 (authoring: 4; this task removes `utils.py:510`, `:932`, `:988`). Gate G-ID: `rg -n "compute_project_id\(Path\(cwd\)" src/functualize/app/utils.py` → 0 (authoring: 2).
  - Reachability: commit, then revert `auto_discover` to the inline walk and watch G1–G4 go red; restore. Repeat for `list_project_config_files` with G8.
  - Acceptance: T1a all green; `tests/cli/test_auto_discover.py tests/test_auto_discover.py tests/test_auto_discover_bug_condition.py tests/test_auto_discover_preservation.py tests/cli/test_func_settings_store.py tests/cli/test_single_file_cwd_isolation.py` green.
  - Done 2026-10-26. G-A: **1** (`project_dirs.py:176`). G-ID: **0**. T1a **9 passed**. Acceptance list: 87 passed, 5 skipped, 2 failed — `test_func_settings_store.py::TestChainPrecedence::test_default_when_nothing_sets_it` (and, under `-n 4` only, `test_global_beats_default`) raise `StopIteration` looking up a `tui.*` setting the catalog had not registered; the same test fails identically on the pre-change merge head `d8c68f3` (`-p no:randomly`, 1 failed / 21 passed), so it is pre-existing and order-dependent, not caused here.
  - Reachability: `func`/`func builtin info jobs` → `_cli` → `functualize.app.utils.auto_discover` → `project_config_layers`; TUI settings → `FuncSettingsStore.discover` → `resolve_cli_config_layers` → `list_project_config_files` → `project_config_layers`. Sabotage (committed first): `auto_discover` back to the inline walk → G1, G2, G3, G4, G7 ×2 **red**; `list_project_config_files` back to the inline walk → G8 **red**; each restored.
  - Not covered by an `examples/` caller: the newly exported `project_config_file_table` (public-API example rule, `contributor/reference/public-api-example-coverage.md`); flagged for review.
- [x] **T6 — Walk B, both stages (B1), and the vault key id** `[F: src/functualize/_app/boot.py]`
  - `discover_config_path` stops at `find_project_boundary(cwd)` when that is reached before `~`. `build_resolution_chain`'s `FileSource` locator uses `stop = find_project_boundary(Path(config_path)) or Path.home()` (D4 (a)). `build_vault_source` (`:1319`) uses `project_root_for(Path.cwd())`.
  - Reachability: the production path is `FunctualizeApp` boot → `_app/boot.py:1013` → `discover_config_path`; boot and `refresh()` → `_app/impl.py::_build_resolution_chain` → `build_resolution_chain`. Sabotage each stop separately (commit first): reverting stage 1 turns G12 red; reverting stage 2 turns G13 red.
  - Acceptance: T1c all green, G17 per D4; `tests/config/test_env_overlay_properties.py tests/config/test_legacy_ini_project.py tests/app/test_remote_first.py tests/app/test_vault_seam.py tests/integration/test_local_vault_e2e.py` green.
  - Done 2026-10-26. T1c **8 passed** (G17 = `hello-default`, D4 (a)). Acceptance list: **98 passed, 6 skipped**. Both stages share one helper, `_job_config_stop(start)`: the boundary when the walk reaches it before `~`, else `~`. Deviation, disclosed: when a boundary lies *above* `~` and the start is under `~`, `~` is kept (the literal `boundary or ~` would have widened stage 2 past `~`).
  - Reachability: `FunctualizeApp` boot → `boot.py` (`app._config_path = discover_config_path(…)`) → `_job_config_stop`; boot and `refresh()` → `_app/impl.py::_build_resolution_chain` → `build_resolution_chain` → `_job_config_stop`. Sabotage (committed first): stage 1 stop back to `~` → G12, G17, G18[root] **red**; stage 2 stop back to `~` → G13, G17 **red**; each restored. Disclosed gap: `build_vault_source`'s key id (`remote_first()` apps only) has no end-to-end observer under a root; T8's vault steps exercise the CLI key path, not this one.
- [x] **T7 — `_app/impl.py` identity** `[F: src/functualize/_app/impl.py, tests/app/test_project_root_identity_wiring.py (new)]`
  - The state locator (`:81-92`) and `build_cached_provider` (`:146-159`) take the standalone id from `project_identity_dir`; `ancestor_search=False` (child projects, ADR-011) unchanged.
  - Gate G-ID: `rg -n "compute_project_id\(str\((cwd|project_root)\)\)" src/functualize/_app/impl.py` → 0 (authoring: 2, `:92` and `:159`).
  - Public-path regression: `tests/app/test_project_root_identity_wiring.py` constructs `FunctualizeApp` in a `root = true` standalone project and a subfolder with isolated XDG roots and real directory discovery, so construction enters `boot_standard`. Observe both the app's state locator and the cached provider through their actual booted behavior: root and subfolder must use the root identity for state/cache, including a cold write and warm read; neither may use the subfolder identity. Do not call `build_resource_locator`, `build_cached_provider`, or `project_identity_dir` directly from the test. Include a no-root control and keep child-project `ancestor_search=False` behavior.
  - Reachability gate: commit the finished test first, then disconnect the `project_identity_dir(cwd)` call in `build_resource_locator` alone and run the new test; it must fail on the state assertion. Restore, disconnect the `project_identity_dir(project_root)` call in `build_cached_provider` alone and run it again; it must fail on the cache assertion. Restore and confirm the test passes. A combined sabotage does not prove each wire. Record both red results in this row and tick T7 in the same implementation commit.
  - Acceptance: G-ID = 0; `uv run pytest tests/app/test_project_root_identity_wiring.py tests/cli/test_root_boundary_identity.py tests/discovery/test_child_project_cache.py tests/discovery/test_cached_provider_wiring.py tests/integration/test_cold_warm_history_parity.py -q` green, with each independent sabotage red as above.
  - Scope amendment (2026-10-26): the T7 source was already committed at `36bd494e` and was transitional until this reachability gate passed; T7 remained unchecked then. With the original `[F:]` limited to `impl.py`, the four named files passed **18 passed, 4 skipped**. Replacing both production identity calls with their unbounded versions still left the three wiring files at **14 passed**. The green suite therefore did not prove either boot wire; the new test file is the minimum added scope needed to falsify that regression. The implementer restores the committed source before completing the task.
  - Done 2026-10-26. G-ID: **0**. Acceptance: **20 passed, 4 skipped**. Independent sabotage after committing the test: `build_resource_locator`'s identity call replaced with `cwd` → **1 failed, 1 passed** (subfolder state path); restored. `build_cached_provider`'s identity call replaced with `project_root` → **1 failed, 1 passed** (warm read imported the job a second time); restored. `git diff --check` clean. The test enters through `FunctualizeApp` → `boot_standard`, with a cold cache write, warm read, and no-root control. Existing child-project cache tests remain green.

## Wave 4 — smell 2 in `_cli` (disjoint files)

- [ ] **T5b — Settings store reads through the one source** `[F: src/functualize/_cli/config.py, src/functualize/_cli/data/func_settings.py]`
  - Delete `_cli/config.py::_functualize_table` (`:800-807`) and `func_settings.py::_functualize_table_of` (`:917-921`); both callers use the public `functualize.app.utils.project_config_file_table`.
  - Gate G-S2b: `rg -n 'tool\.get\("functualize"\)|"tool\.functualize"\)' src --type py`. Authoring time: 4 hits (`project_dirs.py:123`, `_cli/config.py:805`, `:806`, `_cli/pep723.py:152`) plus `_types/settings.py:105`. After T2 + T5b: only `_types/settings.py` and `_cli/pep723.py:152` (a script header, a different file kind, see `plan.md`).
  - Acceptance: `tests/cli/test_func_settings_store.py tests/cli/test_settings_store_second_app.py tests/core/test_settings_schema_types.py tests/cli/test_config_builtin.py` green; T1a G8 green.
- [ ] **T5c — TUI file lists take names from the one source** `[F: src/functualize/_cli/tui/app.py, src/functualize/_cli/tui/panels/config_files.py]`
  - `app.py:950-956` (new-file candidates) and `config_files.py:274-276` (fallback) take the project file names from `functualize.plugin.SettingsSources().project_file_names`. Display order, labels and cwd behaviour are unchanged; the legacy job-config name `functualize.toml` stays a literal (not a project file).
  - Acceptance: `tests/_cli/test_settings_files_pilot.py tests/cli/test_config_files_panel.py tests/cli/test_config_file_discovery.py` green.
- [ ] **T5d — `config path` lists the real project layers** `[F: src/functualize/_cli/builtins.py]` — **waits on D5**
  - D5 (a): replace `:2419-2420` and the two hand-checked files with `list_project_config_files(cwd)` plus the global file, keeping the `✓ used / ✗ missing` line shape. D5 (b): only take the two names from the one source.
  - Gate G-S2a: `rg -n '"\.functualize/\.functualize\.toml"|"\.functualize\.toml"|/ "\.functualize\.toml"' src --type py`. Authoring time: 8 hits in 6 files (`project_dirs.py:136`, `:137`, `tui/app.py:952`, `:955`, `config_files.py:274`, `builtins.py:2420`, `_types/settings.py:98`, `:99`). After T2 + T5c + T5d: exactly the 2 in `_types/settings.py`.
  - Acceptance: G19 per D5; `tests/cli/test_config_builtin.py tests/cli/test_config_files_env_status.py` green.

## Wave 5 — migration proof and the record

- [ ] **T8 — Verified migration procedure and docs** `[F: tests/cli/test_root_boundary_migration.py (new), docs/guides/configuration.md, CHANGELOG.md, contributor/architecture/codemaps/modules.md]`
  - The test replays N4 with real data, first on the pre-fix build (via a git worktree of `f30285c`). Ancestor `runs.json`/`scopes.json` come from running jobs, and a vault entry comes from `func builtin vault put`, with `FUNCTUALIZE_VAULT_KEY` set. Then, on HEAD:
    - (1) nested sees none of it, and the ancestor hashes are unchanged (G10);
    - (2) following `plan.md` § *D2 migration procedure* (`mkdir .functualize`, copy the chosen `runs.json`/`scopes.json`, `func builtin data clear`, `func builtin vault put` again), nested sees the copied runs and its own vault entry, and *not* the ancestor's other vault entries.
  - Docs: a new `docs/guides/configuration.md` section, "Project boundaries and `root = true`", with the shape's declaration table, the four walks, before/after, and the migration steps exactly as the test runs them. `CHANGELOG.md` → `## [Unreleased]` → `### Fixed`: one entry covering sources, settings, job config, and state/vault identity, with both migrations. `modules.md:89`: name `project_root.py` as the owner. No tracker key in any text.
  - Acceptance: `uv run pytest tests/cli/test_root_boundary_migration.py -q` green; `rg -n "root = true" docs/guides/configuration.md` ≥ 1 (authoring: 0).

## Wave 6 — checkpoint

- [ ] **T9 — Full verification** `[F: none — read-only]` `[verify-e2e:cli]`
  - `uv run ruff check src/ tests/ plugins/ examples/`; `uv run ruff format --check …`; `uv run mypy src/`; `uv run lint-imports`; `uv run pytest -x -q --no-header` (log to `/tmp/functualize-pytest.log`); `uv run pytest tests/perf/test_startup_budget.py -q` (R1); `uv run pytest examples/project/shared_plugins/tests -q` (R4, inheritance without a root).
  - AC6: from G1's tree, `func builtin config path` lists no `outer/` file as `✓ used`; `func builtin info` *Config Resolution* names the nested anchor; G9's `Mode:` line says standalone.
  - AC8: T1a–T1c are red on `f30285c` and green on head. AC12: gates G-S2a and G-S2b at their after-counts.
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
    { "id": 4, "tasks": ["T5b", "T5c", "T5d"] },
    { "id": 5, "tasks": ["T8"] },
    { "id": 6, "tasks": ["T9"] }
  ]
}
```
