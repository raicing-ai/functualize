# Plan — project root bounds discovered sources (D1a · D2b · D3b/B1)

## Alignment

- **Shape Intent:** SD/17104898, *Shape Intent — Project Root Bounds Job Sources (what root = true stops)*, version 13, `Authority = Approved`, read live 2026-10-22. Model A ("Root-stop for everything the walk resolves"), with the owner's scope decisions of 2026-10-21: "D1(a), selected — settings catalog", "D2(b), selected — project-folder lookup", "D3(b), selected — job configuration", and the D3 recommendation "**B1 — bound both search and layering**".
- **Member confirmations:** spec confirmed 2026-10-20; "confirm B1 and D2 data rule" 2026-10-22 (MCH-188).
- **Surfaces in scope, in the shape's words:** "Which job sources a nested project with `root = true` resolves"; "The same rule for the other walked directory kinds"; "A nested root's TUI settings list and save targets exclude ancestor project files"; "A `root = true` marker bounds the search for `.functualize/`"; "use the marker's directory as one stable identity for every subdirectory"; "A nested root excludes implicit [job-config] files above its marker, even when a nested file is missing a key".
- **Surfaces out of scope, in the shape's words:** "The upward walk when **no** layer declares `root = true`"; "The XDG global layer `~/.config/functualize/config.toml`"; "Job-name collisions between nested and ancestor jobs (MCH-189's shape)"; "N5's disappearing job without a root marker, and `builtin config path` omitting `.functualize/.functualize.toml`".
- **One open point the shape left to Plan:** "An explicit `--config-directory` is an intentional override; Plan must test its existing upward semantics and document the result rather than silently narrowing it." It was measured (`research.md` § *Plan retrieval 2*, P4) and put to the member as D4. **Decided 2026-10-26: D4 (a)** (MCH-188, "D4 a, smells 2 need to be fixed in this scope, tasks approved").
- **Surviving smell 2 promoted into scope (2026-10-26).** The duplicated project-config file list is fixed here; see § *Smell 2 fix*. One consequence that changes a surface (`func builtin config path`) is put to the member as **D5**.

## Workflow state

WorkflowMode `REPOSITORY_NATIVE` (`.claude/rules/spec-workflow.md`, `.claude/commands/agentic-plan.md`). CurrentPhase `Plan`, complete. Tasks approved by the member 2026-10-26; D4 answered (a). Execute may start; only task T5d waits on **D5**. The withdrawn first Plan (`73851a5`, D2a/D3a) is superseded by this one.

## Architecture gate

### Retrieval performed

| Tool | Bound to | Used for |
|---|---|---|
| zvec-grep `/usr/local/bin/zg` | worktree index (14 416 entities, built 2026-10-20) | prose on the walks, identity and vault-identity prior art |
| serena | activated by absolute worktree path | references of walk A symbols (2026-10-20 pass; unchanged files) |
| graphify | 71+ commits stale | direction only |
| rg | worktree at `f30285c` | every census below |

Codemaps read: `modules.md:89`, `dependencies.md:37`, `data-flow.md:12` (boot step 3.5), `entry-points.md:61`. Prior art that shaped the AFTER: `_config/vault_paths.py` module docstring ("The project is found by walking upward, not by hashing the working directory"), the `_primitives/locator.py::find_functualize_dir` docstring ("This used to exist twice … both `cache_format` and `fresh_format` must **bind this name into their own namespace**"), and `_app/impl.py::_build_resolution_chain` ("Boot and `refresh()` both come through here … One call site can't be forgotten").

### BEFORE — four walks, one partial stop

Layers: `_types` < `_primitives` (foundation, imports nothing internal but `_types`) < peer layers `_config` / `_discovery` / … < `_app` (composition root) < public `app/` < `_cli` (public API only). Arrows: importer → imported.

```
 _cli/*  ──(public API)──►  app/utils.py, app/vault.py, app/adapters/cli.py
                               │  auto_discover        ── WALK A copies #2,#3 ──► leaks: jobs, lib, declared dirs
                               │  list_project_config_files ── WALK A copy #4 ──► leak: TUI settings (D1)
                               │  compute_project_id(cwd)   :1884, :2049  (vault key id by cwd)
                               ▼
 _app/boot.py  discover_config_path  ── WALK B stage 1: cwd → ~        (no stop)  ─► leak N9
               build_resolution_chain── WALK B stage 2: config_path → ~ (no stop)  ─► leak N9 key-by-key
               build_vault_source    ── compute_project_id(Path.cwd()) :1319
 _app/impl.py  state locator :81-92, build_cached_provider :146-159 ── find_functualize_dir + cwd id
                               ▼
 _config/project_dirs.py  resolve_project_config ── WALK A copy #1 ──► merge_config_layers (STOPS)
                          PROJECT_CONFIG_CANDIDATES (+ _extract_functualize_section)
                          resolve_project_directories :613 ── find_functualize_dir ─► conv. plugins (N4 leak)
 _config/merge.py         merge_config_layers: the only `root is True` test (:60-65)
 _config/vault_paths.py   project_root_for ── find_functualize_dir (vault file identity)
                               ▼
 _primitives/locator.py       find_functualize_dir  ── WALK C: cwd → / (no stop) ─► N4: mode, state, plugins
 _primitives/cache_format.py  resolve_cache_path    ── walk C, else id(start)
 _primitives/fresh_format.py  resolve_fresh_location── walk C, else id(start)
```

**Smells the BEFORE carries** (Refactoring.Guru names, consulted via `design-patterns-refactoring`):

| Smell | Where |
|---|---|
| **Duplicate Code** | walk A ×4 (`rg "resolve_all_candidates\(PROJECT_CONFIG_CANDIDATES\)"` → 4 hits); project identity derived three ways: `find_functualize_dir(...).parent`, `compute_project_id(cwd)` (5 sites), `compute_project_id(start)` (2 fallbacks) |
| **Shotgun Surgery** | "where does this project stop?" is answered by four walks with different stops (filesystem root, `~`, first `.functualize/`); `root = true` reaches one |
| **Divergent Change** | the vault *file* is keyed by project root (`vault_paths.py`), its key lookup by cwd (`boot.py:1319`, `app/utils.py:1884`, `:2049`) |
| **Feature Envy** (knowledge trapped) | the root rule is a private loop inside `merge_config_layers`; no other walk can ask it |
| **Long Method** | `app/utils.py::auto_discover` (192 lines) |

### AFTER — one boundary, one identity

```
 _cli/*  ──►  app/utils.py  auto_discover, list_project_config_files ──► project_config_layers (bounded)
              app/utils.py  vault key ids :1884, :2049 ─────────────────► project_identity_dir
                               ▼
 _app/boot.py  discover_config_path(…, stop=min(boundary(cwd), ~))          ┐ B1: both stages,
               build_resolution_chain: FileSource stop = boundary(config_path) or ~  ┘ one predicate
               build_vault_source: id = compute_project_id(project_identity_dir(cwd))
 _app/impl.py  state locator / build_cached_provider: standalone id = project_identity_dir(…)
                               ▼
 _config/project_dirs.py  project_config_layers(cwd, *, search_ancestors) ── ONE walk A, bounded
                          re-exports PROJECT_CONFIG_CANDIDATES
 _config/merge.py         merge_config_layers uses is_root_config
 _config/vault_paths.py   project_root_for = project_identity_dir
                               ▼
 _primitives/project_root.py   (NEW — the one owner of "where a project stops")
     PROJECT_CONFIG_CANDIDATES, _extract_functualize_section   (moved down from _config)
     is_root_config(config)            ← the ONE `root is True` predicate
     find_project_boundary(start)      ← nearest dir whose project config says root = true
     find_functualize_dir(start)       ← WALK C, stops at the boundary (inclusive)
     project_identity_dir(start)       ← .functualize/.parent | boundary | start
          │ uses ResourceLocator's per-directory first-match rule (same rule as walk A)
          ▼
 _primitives/locator.py   ResourceLocator (unchanged), compute_project_id (unchanged)
 _primitives/cache_format.py / fresh_format.py: bind find_functualize_dir from project_root
                         (same unqualified-binding rule), standalone id = boundary or start
```

**Boundary check.** `_primitives/project_root.py` imports only `_primitives.locator` and stdlib (`tomllib`), so *"Primitives import nothing internal"* holds. `_config` → `_primitives` and `_app` → `_config`/`_primitives` are existing directions. No `_cli/` file changes. No peer-layer edge is added. T9 runs `uv run lint-imports` as the proof.

**Why the stop lives in `_primitives`.** Walk C is a primitive, called by readers that must not boot (`resolve_cache_path` from the CLI fast path, completions, the MCP translator; 13 call sites pass `Path.cwd()`). Any design that computes the boundary higher up has to thread it through all of them (*Shotgun Surgery*, candidate C3 below). The `root` key and the three file names are already foundation knowledge: `_types/settings.py:96-100` lists the same file names, and `locator.py` already imports `tomllib`.

### Candidates considered

| # | Candidate | Smells it introduces | Verdict |
|---|---|---|---|
| C1 | **One `_primitives/project_root.py` owns candidates, the predicate, boundary, walk C and identity; walks A and B consume it** | none new; removes Duplicate Code (walk A ×4, identity ×3) and the Divergent Change in vault identity | **chosen** |
| C2 | Keep candidates in `_config`, pass a boundary predicate *callable* down into `_primitives` | **Implicit `Callable` convention for a port** (a Forbidden Pattern) and **Speculative Generality** | rejected (forbidden) |
| C3 | Compute the boundary in `_config` and thread `stop=` through every walk-C caller | **Shotgun Surgery** across ≥13 call sites, including `_cli` readers that cannot reach `_config` | rejected |
| C4 | Process-wide memo of "the project" set at boot | **Global mutable state / module-level singleton** (Forbidden) | rejected |
| C5 | Bound walk B by adding a stop parameter to `ConfigSources` | widens a public API the spec forbids ("No new … surface"); boot and `refresh()` must both pass it (the drift `impl.py` documents) | rejected |

### D4: explicit `--config-directory` under a root (Plan finding P4)

Measured on `f30285c`: nested `root = true`, `--config-directory nested/cfg` (key missing there), ancestor `config.base.toml` has the key → the job prints `ANCESTOR`. Stage 2 layers from the chosen directory up to `~`, crossing the root. The chain builder cannot tell an explicit directory from a discovered one: `app/adapters/cli.py:1016-1017` writes it into `app._config_path`, then `refresh()` rebuilds through the same `_build_resolution_chain`.

- **(a) Recommended:** stage 2 stops at the boundary *of the directory it starts from*: `stop = find_project_boundary(config_path) or ~`. One rule, no new state. An explicit directory outside any root project layers exactly as today. Effect: the measured leak closes.
- **(b) Preserve today exactly:** carry an "explicit" flag from `cli.py` through `refresh()` into the chain builder. That is new state on the app and the forgotten-argument risk the builder exists to remove, and it keeps the leak through the flag.
- **(c) An explicit directory reads only itself:** changes the flag for every user, root or not. Rejected.

### Skills consulted

- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue): smell names above. Fixes applied: *Move Method* to consolidate the Shotgun Surgery into `project_root.py`, and *Extract Function* for the predicate.
- The repo's `python-design-patterns`: not loadable in this Multica runtime (the repo's Claude project settings do not load). Its stated principles (single responsibility, separation of concerns) match C1.

## Smell 2 fix: one declaration of the project config files (added 2026-10-26)

**What is duplicated.** One fact, "which files in a directory are project config, in what order, and which table of `pyproject.toml` holds the settings", is written out six times. Census: `rg -n '"\.functualize/\.functualize\.toml"|"\.functualize\.toml"|/ "\.functualize\.toml"' src --type py` → 8 hits in 6 files; `rg -n 'tool\.get\("functualize"\)|"tool\.functualize"\)' src --type py` → 4 hits.

| Copy | Role | Read by production code? |
|---|---|---|
| `_types/settings.py:96-105` `SettingsSources.project_file_names` + `_default_file_section_prefixes` | **public plugin API** (`functualize.plugin`, `docs/api/plugins.md:242-263`) | the prefixes yes (`AppSettingsSchema.section_prefix_for`); `project_file_names` **no** (only `tests/core/test_settings_schema_types.py:153`) |
| `_config/project_dirs.py:106-138` `PROJECT_CONFIG_CANDIDATES` + `_extract_functualize_section` | walk A (moves to `_primitives/project_root.py` in T2) | yes |
| `_cli/config.py:800-807` `_functualize_table` | settings-store read of one file | yes |
| `_cli/builtins.py:2419-2420` | `func builtin config path`: two files, cwd only | yes (the formerly separate `config path` defect) |
| `_cli/tui/app.py:950-956` | "create a new settings file" candidates in cwd | yes (write hint) |
| `_cli/tui/panels/config_files.py:274-276` | fallback list when no app is loaded | yes |

Smells by catalogue name: **Duplicate Code**, plus **Speculative Generality** on `project_file_names`, which is a public, documented field that no production code reads.

**AFTER: `_types/settings.py` is the one declaration; everything derives from it.**

```
 _types/settings.py   PROJECT_FILE_NAMES, PROJECT_FILE_SECTION_PREFIXES   ← the only literals
       ▲                      (SettingsSources / AppSettingsSchema defaults point at them; public API unchanged)
       │ imports (foundation → types: legal)
 _primitives/project_root.py  PROJECT_CONFIG_CANDIDATES = derived (name, section extractor)
                              project_config_file_table(path) -> (values, prefix)
       ▲
 _config/project_dirs.py (re-export) ─► app/utils.py  list_project_config_files, project_config_file_table (public)
                                              ▲ public API only
 _cli/config.py, _cli/data/func_settings.py ──┘  (_functualize_table deleted)
 _cli/tui/app.py, _cli/tui/panels/config_files.py, _cli/builtins.py
        ── names from functualize.plugin.SettingsSources().project_file_names (public)
```

- **No public API change.** `SettingsSources.project_file_names` and the `pyproject.toml` prefix keep their names, defaults and docs. They become the declaration production code actually reads, which removes the Speculative Generality: the documented field now means what it says for `func`.
- **Not a duplicate, kept:** `_cli/pep723.py:152` reads `[tool.functualize]` from a *script header* (PEP 723), a different file kind with its own two keys (`job`, `skill`). `_cli/tui/panels/config_files.py:275` `functualize.toml` is the legacy *job-config* file name, not a project config file.
- **Candidate check:** the derived candidate list must equal today's literally (same names, same order, same `pyproject.toml` extractor semantics). T2 pins that with a test, so walk A cannot drift.

### D5: should `func builtin config path` list the real project layers?

Today it checks two fixed files in the current directory only (`_cli/builtins.py:2419-2420`), so from a subdirectory it shows the project's files as missing, and it never shows `.functualize/.functualize.toml`. Once the list has one source, this surface is the last hand-written copy.

- **(a) Recommended:** `config path` lists `list_project_config_files(cwd)`, i.e. the bounded walk-A files (D1), plus the global file, keeping the `✓ used / ✗ missing` shape. From a subdirectory it shows the files that actually apply; `.functualize/.functualize.toml` appears; nothing above a root appears (AC6). This closes the defect previously recorded as separate.
- **(b)** Take the names from the one source but keep cwd-only behaviour. The duplicate goes, and the misleading output stays.

## Technical approach

1. **`_primitives/project_root.py` (new).** Move `PROJECT_CONFIG_CANDIDATES` and `_extract_functualize_section` here from `_config/project_dirs.py`, unchanged. Add:
   - `is_root_config(config) -> bool`, which is `config.get("root") is True` (string `"true"` does not stop; pinned by `test_root_non_bool_does_not_stop`);
   - `project_config_at(directory) -> dict | None`, which is `ResourceLocator().search_explicit(directory).resolve_all_candidates(PROJECT_CONFIG_CANDIDATES)`, i.e. the same per-directory first-match rule walk A uses;
   - `find_project_boundary(start) -> Path | None`, walking `start` upward to `/` and returning the first directory whose `project_config_at` is root;
   - `find_functualize_dir(start)`, moved from `locator.py` with its docstring. It walks upward; at each level it returns `d/.functualize` if that is a directory, and returns `None` once `d` is the boundary (inclusive);
   - `project_identity_dir(start) -> Path`, which is `find_functualize_dir(start).parent`, else `find_project_boundary(start)`, else `start`.
2. **`_primitives/locator.py`:** remove `find_functualize_dir` (moved; no compat shim, per *Forbidden Patterns*). **`cache_format.py`, `fresh_format.py`:** import `find_functualize_dir` from `project_root`, still bound unqualified into their own namespace (the `tests/conftest.py::_isolate_state_root` patch point). Their standalone id becomes `compute_project_id(str(find_project_boundary(start) or start))`.
3. **`_config/merge.py`:** `merge_config_layers` stops via `is_root_config` when `root_key == "root"`; the `root_key` parameter keeps its custom-key behaviour (`test_custom_root_key`). **`_config/project_dirs.py`:** re-export `PROJECT_CONFIG_CANDIDATES`; add `project_config_layers(cwd, *, search_ancestors=True)`, the walk-A results truncated after the first `is_root_config` layer; `resolve_project_config` uses it; `resolve_project_directories` imports `find_functualize_dir` from `project_root`. **`_config/vault_paths.py`:** `project_root_for` returns `project_identity_dir(start)`.
4. **`app/utils.py`:** `auto_discover` (both branches) and `list_project_config_files` read `project_config_layers` (D1, leaks 1–2). The vault-key ids at `:1884` and `:2049` use `project_root_for`.
5. **`_app/boot.py`:** `discover_config_path` stops at `find_project_boundary(cwd)` when that is reached before `~` (inclusive), then falls back to `~/.config/<app>` as today. `build_resolution_chain`'s `FileSource` locator uses `stop = find_project_boundary(Path(config_path)) or Path.home()` (B1 stage 2, D4 (a)). `build_vault_source` uses `project_root_for(Path.cwd())`. **`_app/impl.py`:** the state locator (`:81-92`) and `build_cached_provider` (`:146-159`) take the standalone id from `project_identity_dir`; the child-project `ancestor_search=False` path is unchanged (ADR-011).
6. **Docs:** a new "Project boundaries and `root = true`" section in `docs/guides/configuration.md`, built from the shape's declaration table, the four walks and the migration procedure (AC10). `CHANGELOG.md` gets a `### Fixed` entry with both migrations (sources; state and vault). `contributor/architecture/codemaps/modules.md:89` gets one sentence.

**D2 migration procedure (verified and documented by T8):** when a nested `root = true` project used an ancestor's `.functualize/`:
- (1) old data stays where it is, untouched;
- (2) to keep runtime records in the repository, `mkdir <root>/.functualize` and copy only the files you choose (`runs.json`, `scopes.json`) from the ancestor's folder; `fresh.json` and `cache.json` are derived, so skip them and let `func builtin data clear` rebuild;
- (3) vault: the key is per machine (`_config/vault_keys.py:155-160`, `:235-250` ignore `project_id`), so from the nested root run `func builtin vault sync` for declared remote secrets and `func builtin vault put …` for local ones. No file copy, so no ancestor secret enters the nested vault unless the user puts it.

## Files to change (hit sets in `tasks.md`)

| File | Layer | Task |
|---|---|---|
| `src/functualize/_primitives/project_root.py` (new) | foundation | T2 |
| `src/functualize/_primitives/locator.py` | foundation | T2 (remove the moved function) |
| `src/functualize/_primitives/cache_format.py`, `fresh_format.py` | foundation | T4 |
| `src/functualize/_config/merge.py`, `project_dirs.py` | `_config` | T3 |
| `src/functualize/_config/vault_paths.py` | `_config` | T4 |
| `src/functualize/app/utils.py` | public | T5 |
| `src/functualize/_app/boot.py` | composition root | T6 |
| `src/functualize/_app/impl.py` | composition root | T7 |
| tests: three new e2e gate files, unit pins, the migration test | tests | T1a–T1c, T2, T3, T8 |
| `src/functualize/_types/settings.py` | `_types` | T2 (smell 2: named constants) |
| `src/functualize/_cli/config.py`, `src/functualize/_cli/data/func_settings.py` | `_cli` | T5b (smell 2) |
| `src/functualize/_cli/tui/app.py`, `src/functualize/_cli/tui/panels/config_files.py` | `_cli` | T5c (smell 2) |
| `src/functualize/_cli/builtins.py` | `_cli` | T5d (smell 2 + D5) |
| `docs/guides/configuration.md`, `CHANGELOG.md`, `codemaps/modules.md` | docs | T8 |

## Risks

- **R1: hot-path cost.** `find_functualize_dir` now also checks project-config candidates per level and parses TOML only where a candidate file exists. It is reached by several readers per invocation. Gate: `tests/perf/test_startup_budget.py` in T9; if over budget, re-plan with a bounded-parse cache in the caller, never a module-level memo (*Forbidden*).
- **R2: the state sandbox.** `tests/conftest.py::_isolate_state_root` patches `fresh_format.find_functualize_dir`. T4 keeps the unqualified binding in both formats; T9's full suite run proves no test writes outside `tmp_path` (the docstring's own warning).
- **R3: identity moves only for root projects without `.functualize/`.** `project_identity_dir` equals today's answer whenever a `.functualize/` exists inside the boundary, or no root exists (it returns `start`, the standalone behaviour today). This is gated by H2's controls (N1, N5, N6 and standalone-without-root keep their measured outputs).
- **R4: 34 test files** reference the identity and walk-B symbols (`rg -l` census in `research.md`). Those that pin a fixed path under a root-marked tmp tree may change meaning; T9 triages any failure against this plan, not by editing expectations blindly.
- **R5: `--config-directory` (D4).** If the member picks (b), T6 grows a flag through `cli.py` → `refresh()`, and this plan returns to Plan for one task.

## Surviving smells

| Smell | Where | Why it survives | Maintainer review? |
|---|---|---|---|
| **Long Method** | `app/utils.py::auto_discover` | Unchanged length except removing two walk blocks. Splitting it is a refactor with no behaviour mandate, and mixing refactor and fix breaks the separation rule | reviewed 2026-10-26: the member asked to fix smell 2 only, so this stays |
| **Large module** | `_app/boot.py` (2 305 lines), `_app/impl.py` (1 752) | Pre-existing; this change edits three functions in place | no |

Nothing on the *Forbidden Patterns* list is in the AFTER: C2 (implicit `Callable` port) and C4 (global state) were rejected for that reason. There is no backward-compat shim: `locator.find_functualize_dir` moves and its six importers are updated.
