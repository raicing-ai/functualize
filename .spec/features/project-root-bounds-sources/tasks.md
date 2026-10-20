# Tasks — project root bounds discovered sources

Execute is **not** authorized until the member has answered D1 and D2 (`plan.md` § Alignment, MCH-188) and reviewed this list and `plan.md` § *Surviving smells*.

Baseline measured at authoring time on this branch (`36c8f46`, parent `1b73983`), `func` from `uv sync --frozen --all-extras --all-packages`, isolated `HOME`/`XDG_*`. The tree is `outer/.functualize.toml` (empty unless stated), `outer/.functualize/jobs/outer_only.py`, `outer/nested/.functualize.toml` = `root = true`, and `outer/nested/.functualize/jobs/nested_only.py`, run from `outer/nested`:

| Gate | Baseline (HEAD) | Must be after |
|---|---|---|
| AC1 `builtin info jobs --json` names | `['nested-only', 'outer-only']`; `func outer-only` → `RAN outer_only` | `['nested-only']`; `Unknown command`, exit 1 |
| AC2 ancestor `jobs_directories = ["shared"]` | `['nested-only', 'outer-only', 'shared-job']` | `['nested-only']` |
| AC3 ancestor `extra_directories = ["extra"]` | `['extra-job', 'nested-only', 'outer-only']` | `['nested-only']` |
| AC3 ancestor `.functualize/lib/outerlib.py`, nested job `import outerlib` | `LIB 1` | `ModuleNotFoundError` |
| AC4 nested file emptied | `['nested-only', 'outer-only']` | unchanged |
| AC5 no ancestor file; nested `root = true` + `jobs_directories = ["../shared"]` | `['nested-only', 'shared-job']` | unchanged |
| AC7 warm cache (union), then the directory set shrinks | warm boot gives `['nested-only']` | AC1–AC5 identical cold and warm |
| AC9 ancestor `[cli] show_timing = true`, `FuncSettingsStore.discover().resolve()` | chain lists the ancestor file and resolves `true` | ancestor file absent from the chain; resolves the default |

## Wave 0 — gates first

- [ ] **T1 — Regression gates through the public CLI** `[F: tests/cli/test_project_root_boundary.py (new)]`
  - Inputs: `spec.md` AC1–AC5, AC7, AC9; the baseline table above; the `_run_func` idiom (`uv run --project <repo> func …`, `cwd=<tmp tree>`) from `tests/cli/test_eliminate_fallback_e2e.py:75-86`.
  - Write one test per baseline row. Use `subprocess` with `HOME`/`XDG_CONFIG_HOME`/`XDG_DATA_HOME`/`XDG_CACHE_HOME` pointed into `tmp_path`, so no developer config leaks in. AC7 runs AC1 and AC2 twice (cold, then warm), and also warms with the union before the root marker is added. AC9 calls `functualize._cli.data.func_settings.FuncSettingsStore.discover()` in-process with `monkeypatch.chdir`, because it is a resolver contract, not a CLI one.
  - Invariant: AC4 and AC5 tests **pass** on HEAD (they are the controls). AC1, AC2, AC3 (×2), AC7-union and AC9 **fail** on HEAD with the baseline values above.
  - Acceptance: `uv run pytest tests/cli/test_project_root_boundary.py -q` on HEAD shows exactly the failures listed (record the count in the task when done). Commit the red test before T2 so the sabotage step can revert source only.

## Wave 1 — the one predicate, the one walk

- [ ] **T2 — `active_layer_count` and `project_config_layers`** `[F: src/functualize/_config/merge.py, src/functualize/_config/project_dirs.py, tests/config/test_merge_config_layers.py, tests/config/test_project_dirs.py]`
  - Inputs: `plan.md` § Technical approach 1–2.
  - `merge.py`: add `active_layer_count(layers, root_key="root") -> int`; `merge_config_layers` uses it. Behaviour identical: every existing case in `tests/config/test_merge_config_layers.py` (14 collected at authoring time) passes unmodified. Add cases for the count: none root → `len`, first root → 1, middle root → index+1, `"true"` string → no stop.
  - `project_dirs.py`: add `project_config_layers(cwd, *, search_ancestors=True)` and add it to `__all__`. `resolve_project_config` returns `(results[0][0], merge_config_layers(layers))` built from it, with the same contract (`(cwd, {})` when empty). Unit test: a three-level tree with `root = true` in the middle returns two layers. `search_ancestors=False` returns at most the cwd layer plus the platform-user layer, bounded the same way.
  - Gate G-walk: `rg -n "resolve_all_candidates\(PROJECT_CONFIG_CANDIDATES\)" src/functualize/_config/project_dirs.py` → exactly 1 hit (authoring time: 1 hit at `:197`; it moves into the new function).
  - Acceptance: `uv run pytest tests/config/test_merge_config_layers.py tests/config/test_project_dirs.py tests/cli/test_config_upward_walk.py -q` green; `uv run mypy src/` clean.

## Wave 2 — the consumers

- [ ] **T3 — `auto_discover` and `list_project_config_files` read the bounded walk** `[F: src/functualize/app/utils.py]`
  - Inputs: `plan.md` § Technical approach 3; T2's `project_config_layers`.
  - Replace the three inline locator walks (`app/utils.py:506-510`, `:926-932`, `:986-988` at authoring time) with `project_config_layers(cwd, search_ancestors=…)`. Everything downstream is unchanged: anchor, `merge_config_layers`, `walk_directories` (+ cwd), `collect_convention_directories`, and `resolve_effective_directories_from_layers(config_layers=results)`.
  - Gate G-walk (repo-wide): `rg -n "resolve_all_candidates\(PROJECT_CONFIG_CANDIDATES\)" src plugins` → exactly 1 hit, in `_config/project_dirs.py`. Authoring time: 4 hits in 2 files (`project_dirs.py:197`, `utils.py:510`, `:932`, `:988`); the task's file set equals the 3 `utils.py` hits.
  - Reachability: the production path is `func` → `_cli/main.py` → `auto_discover` (`entry-points.md:61`) → `project_config_layers`. After committing, revert `auto_discover`'s branch to the inline locator (sabotage). T1's AC1/AC2/AC3 must turn red. Restore. The same for `list_project_config_files`: AC9 turns red. Commit before each sabotage.
  - Acceptance: `uv run pytest tests/cli/test_project_root_boundary.py -q` all green; `uv run pytest tests/cli/test_auto_discover.py tests/test_auto_discover.py tests/test_auto_discover_bug_condition.py tests/test_auto_discover_preservation.py tests/cli/test_func_settings_store.py tests/cli/test_single_file_cwd_isolation.py -q` green (the authoring-time hit set of tests that call the changed functions, plus the settings store).

## Wave 3 — record

- [ ] **T4 — Changelog and codemap** `[F: CHANGELOG.md, contributor/architecture/codemaps/modules.md]`
  - `CHANGELOG.md` → `## [Unreleased]` → `### Fixed`: one entry in the file's own prose style. It says that `root = true` now bounds job, library, plugin and extra directories and project settings files, not only the config merge. Migration: remove `root = true` to inherit an ancestor, or keep it and declare the shared path explicitly (`jobs_directories = ["../.functualize/jobs"]`). No tracker key in the text (`message-hygiene`).
  - `modules.md:89`: the walk-A sentence names `project_config_layers` as the one bounded walk.
  - Acceptance: `git diff --stat` touches only these two files; `rg -n "project_config_layers" contributor/architecture/codemaps/modules.md` → 1 hit.

## Wave 4 — checkpoint

- [ ] **T5 — Full verification** `[F: none — read-only]` `[verify-e2e:cli]`
  - `uv run ruff check src/ tests/ plugins/ examples/`; `uv run ruff format --check src/ tests/ plugins/ examples/`; `uv run mypy src/`; `uv run lint-imports` (zero violations; the AFTER adds no edge, see `plan.md` § Boundary check); `uv run pytest -x -q --no-header` (redirect to `/tmp/functualize-pytest.log`).
  - AC6: from the AC1 tree, `func builtin config path` lists no `outer/` file as `✓ used`, and `func builtin info` *Config Resolution* shows the nested anchor.
  - AC8: T1 is red on `1b73983` and green on the head.
  - `uv run python .github/scripts/dead_code_delta.py origin/master HEAD`. Expected: no `NEW_DEAD`. `active_layer_count` and `project_config_layers` each have a production caller.
  - Acceptance: every command above passes, and its output is pasted into the hand-off.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T1"] },
    { "id": 1, "tasks": ["T2"] },
    { "id": 2, "tasks": ["T3"] },
    { "id": 3, "tasks": ["T4"] },
    { "id": 4, "tasks": ["T5"] }
  ]
}
```
