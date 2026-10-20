# Plan — project root bounds discovered sources

## Alignment

- **Shape Intent:** SD/17104898, *Shape Intent — Project Root Bounds Job Sources (what root = true stops)*, version 7, `Authority = Approved`, Model A ("Root-stop for everything the walk resolves"), read live 2026-10-20.
- **Surfaces in scope, in the shape's words:** "Which job sources a nested project with `root = true` resolves: convention `.functualize/jobs/` and declared `jobs_directories`"; "The same rule for the other walked directory kinds: `.functualize/lib/`, `.functualize/plugins/`, `import_libs`, `plugins_directories`, `extra_directories`"; "`func builtin config path` and `func builtin info` agreeing with what actually loads"; "CLI flags and environment overrides keep their current precedence over file layers".
- **Surfaces out of scope, in the shape's words:** "The upward walk when **no** layer declares `root = true` (inheritance stays as today)"; "The XDG global layer `~/.config/functualize/config.toml`"; "Changes to the TOML merge semantics of non-directory keys (already root-stopped)"; "Job-name collisions between nested and ancestor jobs (MCH-189's shape)".
- **Where this plan departs from the shape's premises:** two Plan findings, P1 and P2 in `research.md` § *Plan retrieval*. They are put to the member as decisions D1 and D2, and `spec.md` was revised to the recommended answers (marked *Revised in Plan*). P1 falsifies the out-of-scope row's parenthetical "(already root-stopped)" for one consumer. P2 shows that the shape's E3 holds only for a nested project that has its own `.functualize/`.

## Workflow state

WorkflowMode `REPOSITORY_NATIVE` (`.claude/rules/spec-workflow.md`, `.claude/commands/agentic-plan.md`). Specify was confirmed by the member on 2026-10-20 (MCH-188, "Confirm spec draft"). This document is the Plan phase output, and Execute is **not** authorized until the member answers D1, D2 and the task review below.

## Architecture gate

### Retrieval performed (step 2)

| Tool | Bound to | Used for |
|---|---|---|
| zvec-grep `zg` 0.x at `/usr/local/bin/zg` | index built in this worktree (`zg index <abs worktree> -g 'src/**' -g 'docs/**' -g 'contributor/**' -g 'plugins/**' -g '*.md'`, 14 416 entities, 1 m 49 s) | prose on `root = true`, the settings layer chain, and the "walk A / walk C disagree" prior art |
| serena | activated by absolute worktree path | `find_referencing_symbols` for `merge_config_layers`, `collect_convention_directories`, `resolve_effective_directories_from_layers`, `resolve_project_config`, `list_project_config_files` |
| graphify | `graphify-out/graph.json`, **71 commits behind HEAD** | dependency *direction* only; line numbers taken from the checkout |
| rg | worktree | every count below |

Codemaps read: `contributor/architecture/codemaps/modules.md:89` (walk A lives in `_config/project_dirs.py`; `app/utils.py` re-exports it), `dependencies.md:37`, `data-flow.md:12` (boot step 3.5 reads the project once), `entry-points.md:61` (`auto_discover` is the CLI's entry).

### BEFORE

Layers: `_primitives/` = foundation; `_config/` = peer layer; `app/` = public; `_cli/` = public-only consumer (contract *"_cli uses public API only"*). Arrows point from importer to imported.

```
                 public: app/utils.py                                   _cli/ (public API only)
 ┌───────────────────────────────────────────────────────────┐     ┌──────────────────────────────┐
 │ auto_discover()            [Long Method, 870-1061]        │     │ _cli/config.py               │
 │  ├ WALK A copy #2  ResourceLocator.search_upward(cwd)     │     │  resolve_cli_config()  ──────┼──┐
 │  │    results = resolve_all_candidates(...)   :932        │     │  resolve_cli_config_layers() │  │
 │  │    merged = merge_config_layers(layers)  ◄─ STOPS      │     │     └► list_project_config_  │  │
 │  │    collect_convention_directories(results) ◄─ LEAK 1   │     │         files()  ◄─ LEAK 3   │  │
 │  │    resolve_effective_..._from_layers(                 │     │ _cli/data/func_settings.py   │  │
 │  │        config_layers=results)             ◄─ LEAK 2   │     │  FuncSettingsStore.discover()│  │
 │  └ WALK A copy #3 (local-only branch)        :988        │     │ _cli/tui/config_target_      │  │
 │ list_project_config_files()                               │◄────┤   discovery.py               │  │
 │  └ WALK A copy #4                            :510        │     └──────────────────────────────┘  │
 │ re-exports resolve_project_config ─────────────┐          │                                       │
 └────────────────────────────────────────────────┼──────────┘◄──────────────────────────────────────┘
          │ imports                               │
          ▼                                       ▼
 internal peer: _config/
 ┌───────────────────────────────┐   ┌────────────────────────────────────────────┐
 │ merge.py                      │◄──┤ project_dirs.py                            │
 │  merge_config_layers()        │   │  resolve_project_config()  WALK A copy #1  │
 │   root-stop is a private loop │   │      :197  → merged (stopped)              │
 │   inside the merge  :60-65    │   │  collect_convention_directories() no stop  │
 └───────────────────────────────┘   │  resolve_effective_directories_from_layers │
                                     │      iterates every raw layer  :363        │
                                     │  resolve_project_directories() (boot 3.5)  │
                                     │      merged → declared plugins (stopped)   │
                                     │      walk C find_functualize_dir → conv.   │
                                     └──────────────────┬─────────────────────────┘
                                                        ▼
 foundation: _primitives/locator.py   ResourceLocator.search_upward / resolve_all_candidates
                                      find_functualize_dir (walk C: nearest .functualize/)
```

The stop rule exists **only as a loop inside `merge_config_layers`**. It returns a merged dict and throws away *which* layers were active. Every other consumer receives the unstopped `results` list.

**Smells the BEFORE carries** (Refactoring.Guru catalogue names):

| Smell | Where | Evidence |
|---|---|---|
| **Duplicate Code** | walk A is written out four times: `_config/project_dirs.py:193-197`, `app/utils.py:506-510`, `:926-932`, `:986-988` | `rg -n "resolve_all_candidates\(PROJECT_CONFIG_CANDIDATES\)" src plugins` → 4 hits, 2 files |
| **Shotgun Surgery** | the `root = true` rule must be re-applied at each consumer of the walk; one of four does it | leak 1, leak 2, leak 3 (`research.md` § Plan retrieval) |
| **Feature Envy** (inverted: the knowledge is trapped) | `merge_config_layers` owns "which layers are active" but exposes only the merged dict, so `auto_discover` re-derives nothing and leaks | `_config/merge.py:60-65` |
| **Long Method** | `auto_discover`, 192 lines, two near-identical branches | `app/utils.py:870-1061` |

### AFTER

```
                 public: app/utils.py                                   _cli/ (unchanged files)
 ┌───────────────────────────────────────────────────────────┐     ┌──────────────────────────────┐
 │ auto_discover()                                           │     │ resolve_cli_config_layers()  │
 │   results = project_config_layers(cwd,                    │     │  └► list_project_config_     │
 │               search_ancestors=…)   ← bounded             │     │      files()  (now bounded)  │
 │   merged  = merge_config_layers(layers)                   │     └──────────────────────────────┘
 │   collect_convention_directories(dirs of results)         │
 │   resolve_effective_..._from_layers(config_layers=results)│
 │ list_project_config_files()  → project_config_layers(cwd) │
 └───────────────────────────┬───────────────────────────────┘
                             │ imports (public → internal: legal)
                             ▼
 internal peer: _config/
 ┌───────────────────────────────┐   ┌────────────────────────────────────────────┐
 │ merge.py                      │◄──┤ project_dirs.py                            │
 │  active_layer_count(layers)   │   │  project_config_layers(cwd, *,             │
 │    ← the ONE stop predicate   │   │      search_ancestors=True)  ← ONE walk A  │
 │  merge_config_layers() uses it│   │      = results[:active_layer_count(...)]   │
 └───────────────────────────────┘   │  resolve_project_config() → uses it        │
                                     │  (other functions unchanged)               │
                                     └──────────────────┬─────────────────────────┘
                                                        ▼
 foundation: _primitives/locator.py   unchanged
```

- **One stop predicate** (`active_layer_count` in `_config/merge.py`), used by both the merge and the walk. `merge_config_layers` keeps its contract and its tests. On an already-bounded list its stop is a no-op, so double application is harmless.
- **One walk A** (`project_config_layers` in `_config/project_dirs.py`). It returns the bounded `(directory, config)` pairs, nearest first. The four sites become one locator call. `search_ancestors=False` covers the local-only branch (explicit cwd, no upward search).
- Leak 1 and leak 2 close because `auto_discover` feeds the bounded list to both collectors. Leak 3 closes because `list_project_config_files` iterates the bounded list (D1).
- **Walk C is unchanged** (D2): `find_functualize_dir`, project mode, runtime-state location.

**Boundary check.** Every new edge already exists in the BEFORE: `app/utils.py → _config/project_dirs.py` (`:23-30`) and `project_dirs.py → merge.py` (`:40`). No `_cli/` file changes. No peer-layer import is added (`_config` imports only its sibling and `_primitives`). Contracts *"Internal never imports public"*, *"Peer layers are independent"* and *"_cli uses public API only"* (`pyproject.toml:344-457`) are untouched by construction. T5 runs `uv run lint-imports` as the proof.

### Candidates considered (step 6)

| Candidate | Smells it introduces | Verdict |
|---|---|---|
| **A. Bound once in `_config/project_dirs.py`, predicate shared from `merge.py`** (chosen) | none new; removes Duplicate Code ×3 and Shotgun Surgery | chosen |
| B. Apply the stop inside `ResourceLocator.resolve_all_candidates` | puts TOML key semantics (`root`) into `_primitives/`, which "import nothing internal" and know nothing about config meaning; **Divergent Change** for the locator, which also serves cache and state lookups | rejected |
| C. Patch each consumer (`collect_convention_directories`, `resolve_effective_directories_from_layers`, `list_project_config_files`) to skip layers above root | keeps four walks and adds three more copies of the predicate: worse **Shotgun Surgery**, the exact defect class | rejected |
| D. Add a `root_dir` field to `DiscoveryResult` and filter downstream | **Primitive Obsession** plus a new public field the spec forbids ("No new … surface") | rejected |

### Skills consulted (step 5)

- `design-patterns-refactoring` (user-level skill: *Dive Into Design Patterns* + the Refactoring.Guru catalogue). Used for the smell names above: *Duplicate Code*, *Shotgun Surgery* (fix: `Move Method` to consolidate), *Long Method*, *Feature Envy*, *Divergent Change*, *Primitive Obsession*.
- The repository's `python-design-patterns` skill (`.claude/skills/python-design-patterns`). It was **not loaded in this runtime**: the Multica run starts outside the repo's Claude project, so only its path is known. Its principles (single responsibility, KISS) agree with candidate A. Execute may load it.

## Technical approach

1. `_config/merge.py`: extract `active_layer_count(layers, root_key="root") -> int`, the number of layers up to and including the first whose `root_key` value `is True` (`len(layers)` when none). `merge_config_layers` calls it instead of its inline loop. Semantics are bit-identical: `is True`, not truthiness, as `tests/config/test_merge_config_layers.py::test_root_non_bool_does_not_stop` pins.
2. `_config/project_dirs.py`: add `project_config_layers(cwd, *, search_ancestors=True) -> list[tuple[Path, dict[str, Any]]]`. It builds the existing locator (`search_upward(start=cwd)` or `search_explicit(cwd)`, then `.search_platform_user("functualize")`), calls `resolve_all_candidates(PROJECT_CONFIG_CANDIDATES)`, and returns `results[:active_layer_count([c for _, c in results])]`. `resolve_project_config` calls it. Export it in `__all__`.
3. `app/utils.py`: `auto_discover` takes `results = project_config_layers(cwd, search_ancestors=search_ancestors)` in both branches and keeps everything downstream as is. `list_project_config_files` iterates `project_config_layers(cwd)`. The three inline locator constructions are deleted.
4. `CHANGELOG.md` `## [Unreleased]` → `### Fixed` entry, in the file's prose style, with the migration line: remove `root = true` to inherit, or declare the shared path explicitly.

`auto_discover`'s Long Method shrinks by the two locator blocks only. Splitting it further is not this feature's mandate (see Surviving smells).

## Files to change (hit sets in `tasks.md`)

| File | Layer | Why |
|---|---|---|
| `src/functualize/_config/merge.py` | `_config` | the stop predicate |
| `src/functualize/_config/project_dirs.py` | `_config` | the one bounded walk |
| `src/functualize/app/utils.py` | public `app` | both collectors and the settings-file list consume the bounded walk |
| `tests/cli/test_project_root_boundary.py` (new) | tests | AC1–AC5, AC7, AC9 through the public CLI |
| `tests/config/test_merge_config_layers.py`, `tests/config/test_project_dirs.py` | tests | unit pins for the predicate and the walk |
| `CHANGELOG.md` | docs | AC8 |
| `contributor/architecture/codemaps/modules.md` | docs | the walk-A sentence at `:89` names the new single entry |

Unchanged on purpose: `_primitives/locator.py`, `_cli/**`, `_app/boot.py` (its plugin path already reads the stopped `merged`), and the discovery cache format (see Risks).

## Risks

- **R1: warm cache serving the union.** Measured on HEAD: a cache warmed with `['nested-only', 'outer-only']`, followed by the ancestor marker's removal (the scanned directory set shrinks), gives `['nested-only']` on the next warm boot, with no version bump. The fix shrinks the same input, so no `CACHE_VERSION` bump is planned. AC7's gate is the proof. If it fails, the remedy is a version bump, and the task is re-planned rather than patched.
- **R2: tests that relied on the leak.** 13 test files write `root = true` (`rg -l "root = true|root=true|\"root\": True" tests`). All of them use it to *isolate* a tmp project, which is the direction this fix strengthens. T5 runs the full suite.
- **R3: platform-user layer.** `search_platform_user("functualize")` appends `~/.config/functualize/` as a candidate *directory* (a `.functualize.toml` placed there), after the ancestors. Today the merge already drops it above a root, and the bounded walk drops it for directories too. The XDG `config.toml` global layer is read separately (`read_toml_file(xdg …/config.toml)`) and is unaffected (spec Behavior 4).
- **R4: the shared-plugins example.** `examples/project/shared_plugins/{billing,shipping}` inherit the root's convention plugin through walk C and declare no `root = true`. They are unaffected by construction, and their test is part of T5's run.

## Surviving smells

| Smell | Where | Why it survives | Maintainer review? |
|---|---|---|---|
| **Long Method** | `app/utils.py::auto_discover` (≈180 lines after the change) | Splitting the two branches is a refactor with no behaviour mandate. Mixing it into a bug fix violates "never mix feature + refactor commits". The change removes the duplicated walk, which is the part that caused the bug | **yes**, to confirm it stays out of 0.5.0 |
| **Divergent Change** (two notions of "the project") | walk A (`project_config_layers`, bounded at `root = true`) vs walk C (`_primitives/locator.py::find_functualize_dir`, nearest `.functualize/`) | Kept by D2's recommendation. Walk C decides project mode and the location of every runtime-state file (fresh, scopes, runs, cache, vault paths), and bounding it moves user state. That is a separate shape | **yes**: D2 |
| **Large Class** analogue (module size) | `app/utils.py`, 2 206 lines | Pre-existing; this change shrinks it slightly. Not a class, so not the Forbidden-Patterns ~500-LOC *class* rule | no |

Nothing on the *Forbidden Patterns* list appears in the AFTER: no peer-layer import, no `_cli/` internal import, no global state, no hard-coded config path (the walk still goes through `ResourceLocator`), and no backward-compat shim.
