# config-unknown-keys — Plan

## Alignment

- **Shape:** *Shape Intent — Unknown Keys in .functualize.toml (what is
  checked, how loudly, where)* — Confluence `SD/17137669`, **version 2**
  (updated 2026-10-17 03:48:14 UTC), `Status = Approved`,
  `Authority = Approved`. Read live on 2026-10-17 before this plan was written.
- **Approval record:** three inline comments by the maintainer, each
  "follow recommendation" (`18808859` 03:46:36Z, `18972740` 03:47:04Z,
  `18808867` 03:47:31Z). The build shape is the page's own
  "**Recommendation: 1a + 2a + 3a.**" The page's intro sentence "It is **not
  approved**" is stale draft prose; the `Authority` row governs.
- **In scope, in the shape's words:**
  - "Unknown **scalar/array keys** at the top level and inside known setting
    sections (`[cli]`, `[discovery]`, registered sections) of
    `.functualize.toml` and `pyproject.toml` `[tool.functualize]`"
  - "A "did you mean" suggestion from the known vocabulary"
  - "`func builtin config path` and the JSON of `func builtin info`"
  - "The XDG global `config.toml` gets the same check"
- **Out of scope, in the shape's words:** "Validating **values** (types, enum
  members)"; "Unknown **tables** that could be job sections"; "Adding a
  `--json` flag to `config path` — owned by SD/2850883's output-flag
  conventions"; "Unknown parameters inside a job section — per-job schema
  validation".
- **Must not change, in the shape's words:** "a file with only known keys
  produces exactly today's output; no run's exit code changes because of the
  check."
- **Shape risks answered here:** Risk 1 (registered settings load late) → §4.2;
  Risk 2 (`pyproject.toml` neighbours) → only `[tool.functualize]` is read, via
  the existing `_functualize_table`.
- **Related, not carried:** SD/17104898 (MCH-188) shares the `config path`
  surface; which files `config path` lists is that page's concern.

## 1. Skills consulted

- `python-design-patterns` (in-repo, `.claude/skills/python-design-patterns`) —
  KISS, single responsibility, "live with duplication vs. add an abstraction".
- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue) — the
  smell names below (*Duplicate Code*, *Shotgun Surgery*, *Long Method*,
  *Divergent Change*) and their routing.

## 2. Architecture pass — the region today

Tools: zvec-grep (index built in this worktree, 912 files), serena
(`find_referencing_symbols` on `full_report`, `_functualize_table`), graphify
(`get_neighbors full_report`), `uv run lint-imports` (7 kept, 0 broken at
`d1c7e40a`). Codemaps read: `contributor/architecture/codemaps/overview.md`
(layer vocabulary). No codemap mentions `_cli/data/func_settings.py` or
`config path`; nothing contradicts the drawing.

### BEFORE

```
 layer: delivery  _cli/  (may import only public folders + _cli siblings)
 ┌───────────────────────────────────────────────────────────────────────────┐
 │ _cli/builtins.py  register_builtin_commands (728-3038)                    │
 │   config_path (2412-2467) ── reads files itself: tomllib.loads(...)       │
 │        │  prints ✓/○/✗ on existence (+ "any values" for global)          │
 │        │  NO key check                                                    │
 │   info_group / info_all ──────────► _cli/info.py full_report (364-425)    │
 │                                          report["config"] = {anchor,...}  │
 │                                          NO key check                     │
 │                                                                           │
 │ _cli/data/func_settings.py  _BASE_SETTINGS, tui_settings(), _REGISTERED   │
 │        │ imports                                                          │
 │        ▼                                                                  │
 │ _cli/config.py  _RECOGNIZED_SECTIONS/_TOP_LEVEL_KEYS/_KEYS (vocabulary #2)│
 │   read_global_config ── warns on stderr + drops unknown keys (global only)│
 │   _functualize_table, resolve_cli_config_layers                           │
 └──────────────┬────────────────────────────────────────────────────────────┘
                │ public API only (import-linter "_cli uses public API only")
                ▼
 public  app/utils.py  list_project_config_files, resolve_user_config_dir
                │
                ▼
 peer layer  _config/  project_dirs.LIST_KEYS, merge.root_key="root",
             vault_declarations "vault_secret"           (vocabulary #3, unreachable from _cli)
 _cli/main.py  reads [plugins] disabled                  (vocabulary #4)
```

**Smells the BEFORE already carries** (catalogue names):

| Smell | Where |
|---|---|
| *Duplicate Code* — the settings vocabulary is stated four times | `func_settings._BASE_SETTINGS`; `_cli/config._RECOGNIZED_*` (already guarded by the drift test `tests/cli/test_func_settings_store.py:230`); `_config/project_dirs.LIST_KEYS` + `merge.root_key` + `"vault_secret"`; `_cli/main.py:362` `[plugins] disabled` |
| *Long Method* | `register_builtin_commands`, 2311 lines (728-3038), every builtin as a closure |
| *Duplicate Code* — TOML read inline | `config_path` re-parses each file with `tomllib.loads` instead of `_functualize_table` |
| **Forbidden pattern, pre-existing:** "Hard-coding config file paths" | `config_path` builds `cwd / "pyproject.toml"`, `cwd / ".functualize.toml"` (`builtins.py:2419-2420`) instead of the `ResourceLocator` walk — see §6 decision D2 |

## 3. Candidate AFTERs

**A1 — check inside `_cli/config.py`, reusing `_RECOGNIZED_*`.** Rejected:
`_RECOGNIZED_SECTIONS` lacks `plugins` and `shell`, so `[plugins] strict` and
`[shell] program` would become false positives (H1 fails); fixing that means
changing the global reader's filter, which changes today's behaviour.

**A2 — unify the four vocabularies first.** Rejected for this ticket: `_cli`
cannot import `_config` (import-linter), so unification means a new public
surface or moving `LIST_KEYS`; the shape names that as "a larger change than
this ticket", reserved for when E1 fails — it did not.

**A3 (chosen) — one new `_cli/data` module owns the check; both surfaces
call it.** Vocabulary = live catalog (`FUNC_SETTINGS`) ∪ `tui_settings()` ∪ a
small literal of keys read outside the catalog, pinned by a drift test.

Introduced-smell check for A3: the literal is new *Duplicate Code* of
`_config` names (declared below, guarded by test); no *Shotgun Surgery* (one
new module, two one-line call sites); no global state (reads the existing
registry, holds none); no peer-layer import; `register_builtin_commands` grows
by ≤ 6 lines, not a class.

### AFTER

```
 layer: delivery  _cli/
 ┌────────────────────────────────────────────────────────────────────────────┐
 │ _cli/builtins.py  config_path ──(lazy import)──┐                          │
 │                   info_group / info_all        │                          │
 │                        │                       ▼                          │
 │                        ▼            _cli/data/config_vocabulary.py  [NEW] │
 │ _cli/info.py full_report ─(lazy)──►   find_unknown_keys / describe /      │
 │   report["config"]["unknown_keys"]    unknown_keys_in_file / _in_layers   │
 │                                       vocabulary = FUNC_SETTINGS          │
 │                                                 ∪ tui_settings()          │
 │                                                 ∪ _READ_OUTSIDE_CATALOG   │
 │                                         │ imports            │ imports    │
 │                                         ▼                    ▼            │
 │                         _cli/data/func_settings.py    _cli/config.py      │
 │                         (unchanged)                   _functualize_table, │
 │                                                       resolve_cli_config_ │
 │                                                       layers (unchanged)  │
 └───────────────────────────────────────┬────────────────────────────────────┘
                                         │ public API only (unchanged)
                                         ▼
 public  app/utils.py (unchanged)
 peer    _config/ (unchanged; NOT imported — names pinned by a test instead)
 tests/cli/test_config_vocabulary.py ──imports──► _config.project_dirs.LIST_KEYS,
                                                  _cli.data.config_vocabulary   (drift test)
```

Boundary check: the new module imports `difflib`, `dataclasses`, `pathlib`,
`collections.abc`, `typing`, `functualize._cli.config`,
`functualize._cli.data.func_settings` — all legal under the seven contracts.
`func_settings` already imports `_cli.config`, and `_cli.config` imports
neither, so no cycle.

## 4. Technical approach

### 4.1 `config_vocabulary.py`

- `_READ_OUTSIDE_CATALOG`: top level `{root, jobs_directories,
  plugins_directories, extra_directories, exclude_patterns, vault_secret}`;
  `discovery: {jobs_directories, import_libs, plugins_directories,
  extra_directories, exclude_patterns}`; `plugins: {disabled}`. Free-form
  sections: `{aliases}`. Each entry carries a comment naming its reader.
- `_vocabulary()` built per call (cheap; not cached — the registry is live):
  `{section: set(keys)}` with `""` for top level.
- `find_unknown_keys(values, file=)`: walk top-level items; non-dict value →
  check against `""`; dict whose name is a known section (and not free-form)
  → check its non-dict values; any other dict → skip. Document order.
- Suggestion: `difflib.get_close_matches(key, same_scope_keys, n=1,
  cutoff=0.6)` — the plugins' rule (`functualize_secrets_aws/_reference.py:126`).
- `unknown_keys_in_file(path)`: `_functualize_table(path)` (same import idiom
  as `func_settings.py:918`), then `find_unknown_keys`. Missing/broken file → `()`.
- `unknown_keys_in_layers(layers)`: over `layers` that exist, dedup by path.
- `describe(findings)`: C1 suffix or `""`.

### 4.2 Risk 1 (late registration)

`tui.*` is always known via `tui_settings()` (catalog data, no import of the
`tui` package). A third-party section registered later is, until registered,
an unknown *table* → unchecked under 3a → no false positive. Residual: a
component registering a **top-level** (section `""`) setting after the check
runs. Measured: no such registration exists (`rg -n 'register_settings\('`
→ `_cli/tui/__init__.py:86` (`tui`), `examples/standalone/deploy_tool/…:54`
(`deploy`)). Declared as a risk, not engineered around.

### 4.3 `config path`

After each printed file line is computed, append
`describe(unknown_keys_in_file(path))` for that path. Only the three paths the
command already prints are inspected; no path is added or computed.

### 4.4 `info --json`

In `full_report`, `report["config"]["unknown_keys"] = [asdict-like dicts]`
from `unknown_keys_in_layers(resolve_cli_config_layers())`. Plain renderer
untouched.

### 4.5 Docs and changelog

- `docs/cli/config.md`: `config path` section (annotation + example), the
  *Error Handling* table row "Unrecognized key …" (now reported by
  `config path` / `info --json` for every file kind).
- `CHANGELOG.md` → `## [Unreleased]`: `### Fixed — <one sentence>` in the
  file's entry style (heading sentence + one paragraph).

## 5. Blast radius (pass 3b)

| Symbol | References (serena / rg) | Effect |
|---|---|---|
| `full_report` | `builtins.py` `info_group` (2800, 2809, 2813), `info_all` (3008, 3014) | JSON gains one key; plain renderer reads named keys only (`info.py:469-473`) |
| `config_path` | CLI only; tests `tests/cli/test_config_builtin.py:312-416` (substring asserts, all still true) | suffix only when findings exist |
| `_functualize_table` | `_cli/config.py:827`, `func_settings.py:918-920` | read-only reuse |
| `FUNC_SETTINGS`, `tui_settings` | read-only | none |

## 6. Decisions

- **D1 (taken, from the shape):** 1a + 2a + 3a.
- **D2 (needs maintainer review):** `config_path` hard-codes its candidate
  paths — a *Forbidden Patterns* entry — and this feature edits that function
  without removing it. Removing it means listing files via the
  `ResourceLocator` walk, which changes which files `config path` prints:
  that breaks the shape's must-not-change clause and is SD/17104898
  (MCH-188)'s surface. Recommendation: do not fix here; the new code adds no
  hard-coded path (it inspects only paths the command already holds, and
  `info` uses `resolve_cli_config_layers`). Put to the maintainer in the
  hand-off, not silently accepted.
- **D3 (note, non-blocking):** FOSS-127's "Verification for a fix" also says
  "`config path` no longer describes a file as used when none of its keys were
  applied". The approved shape keeps the status word and annotates the line;
  changing what `✓ used` means is not in the shape. Following the shape.

## Surviving smells

| Smell (catalogue) | Where | Why accepted | Maintainer review? |
|---|---|---|---|
| *Duplicate Code* | `_READ_OUTSIDE_CATALOG` in `config_vocabulary.py` restates `_config/project_dirs.LIST_KEYS`, `merge.root_key`, `"vault_secret"`, and `_cli/main.py`'s `[plugins] disabled` | `_cli` may not import `_config`; unifying is the shape's "larger change". Pinned by a drift test that imports both sides (same idiom as `test_catalog_covers_the_recognized_config_surface`) | **Yes** — it is a fifth statement of the vocabulary |
| *Duplicate Code* (pre-existing, unchanged) | `_cli/config._RECOGNIZED_*` vs catalog | Already drift-tested; changing the global reader's filter is behaviour change outside the shape | No |
| *Long Method* (pre-existing) | `register_builtin_commands` 728-3038 | Feature adds ≤ 6 lines; decomposing it is unrelated work | No |
| Forbidden pattern, pre-existing: hard-coded config paths | `builtins.py:2419-2420` | Not introduced, not extended; removal belongs to MCH-188 (D2) | **Yes** (D2) |

## 7. Risks

- A job literally named `cli`, `discovery`, `plugins`, `shell`, `vault` or
  `tui` would have its scalar parameters reported as unknown setting keys. No
  such job is defined in `examples/` or `evals/`
  (`rg -n '^\s*def (cli|discovery|plugins|shell|vault|tui|aliases)\(' examples evals`
  → 0 hits); report-only (1a), so nothing breaks.
- H2 (warm boot): the module is imported lazily inside `config_path` and
  `full_report` only; gate T4 asserts it is absent from `sys.modules` after a
  job run.
