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

- **Revision 2 scope (pending M1):** the maintainer's direction on MCH-190
  (comment `01a153bd`, 2026-10-19) asks for one consistent single source of
  truth for the config vocabulary, after the unified job-namespace design
  (SD/19595276, MCH-194). SD/17137669 v2 calls that unification "a larger
  change than this ticket". Until the page records it, §3.7 of `spec.md` and
  waves 1–3 below are proposed, not approved.

## 1. Skills consulted

- `python-design-patterns` (in-repo) — single responsibility; "live with
  duplication vs. add an abstraction".
- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue) —
  *Duplicate Code*, *Shotgun Surgery*, *Primitive Obsession*, *Middle Man*,
  *Long Method*; techniques *Extract Class*, *Replace Data Value with
  Object*, *Remove Middle Man*.
- Precedent read: MCH-194's `.spec/features/job-name-command-path/plan.md`
  on `origin/fix/job-name-command-path` `5f27149f`. Its pattern is one typed
  owner in `_types/` (`CommandPath` in `_types/naming.py`), public re-export,
  every surface deriving from it, and a source ratchet (E8) so that the rule
  cannot be re-implemented elsewhere. This plan applies the same pattern to
  the config vocabulary.

## 2. Architecture pass — where the vocabulary lives today

Measured at `91947bb4` with an AST walk of `src/functualize/**` (docstrings
excluded). Tools: zvec-grep (worktree index), serena
`find_referencing_symbols` (`full_report`, `_functualize_table`), graphify
`get_neighbors full_report`, `uv run lint-imports` (7 kept, 0 broken).

- **13 collection literals restate ≥ 2 config key names, in 6 files**:
  `_cli/config.py` 6, `_cli/main.py` 2, `_config/project_dirs.py` 2,
  `_cli/info.py` 1, `_cli/dispatch.py` 1, `_cli/data/settings_schema.py` 1.
  Two more statements sit outside that count because they are tuples of pairs:
  `_cli/data/func_settings.py:180` (`_BASE_SETTINGS`, built from `_spec(...)`
  calls) and `_discovery/filter_factory.py:199` (`_DISCOVERY_FINGERPRINT_FIELDS`).
  Its own comment says it repeats `DiscoveryConfig` "because `_discovery` may
  not import the public `app.config`", and a drift test keeps it in line.
- **91 config-key string literals in read position** (`.get("k")`, `["k"]`,
  `"k" in …`) **in 9 files**: `_cli/main.py` 35, `app/utils.py` 19,
  `_cli/config.py` 15, `_cli/dispatch.py` 12, `_config/project_dirs.py` 5,
  `_cli/info.py` 2, `_app/boot.py` 1, `_config/vault_declarations.py` 1,
  `app/adapters/cli.py` 1. About half are reads of a config document
  (`merged_config.get("plugins")`). The other half are CLI-flag plumbing,
  dicts keyed by the same names (`cli_flags["require_file_import"] = …`,
  `_cli/main.py:304-320`, `_cli/dispatch.py:401-423`, `app/utils.py:843-867`).
- **The type for a single declaration already exists and is unused for
  this.** `_types/settings.py` declares `Setting`, `SettingsSources` (project
  and global file names) and `AppSettingsSchema` (settings, env prefix,
  `pyproject.toml` prefix, `env_var_for`, `section_in_file`). Its own docstring
  says it was "reconciled with the shipped `FuncSetting`" so that "there is
  still a single spelling of a setting's identity". func's *instance* of it,
  `FUNC_SCHEMA`, is built in `_cli/data/func_settings.py:512`, which is in
  the delivery layer. Neither `_config/`, `_discovery/`, `_engine/` nor `_app/`
  may import it, so each of them restates the names it needs.

### BEFORE

```
 [_types]      _types/settings.py   Setting, SettingsSources, AppSettingsSchema   (shape only, no instance)
                    ▲ public re-export: functualize.plugin
 [_config]     _config/project_dirs.py  LIST_KEYS, PROJECT_CONFIG_CANDIDATES      (statement #3)
 [peer]        _config/merge.py         root_key="root"
               _config/vault_declarations.py  "vault_secret"
 [_discovery]  _discovery/filter_factory.py   _DISCOVERY_FINGERPRINT_FIELDS        (statement #4, drift-tested)
 [_app]        _app/boot.py  resolve("strict","plugins")
 [_engine]     _engine/executor.py  _resolve_shell_setting("program"/"sudo_password")
 [public app]  app/config.py DiscoveryConfig fields; app/utils.py reads "discovery"/"scan_depth"/"vault_secret"
 [_cli]        _cli/data/func_settings.py  _BASE_SETTINGS, tui_settings(), FUNC_SCHEMA   (statement #1)
               _cli/data/settings_schema.py SETTING_SCHEMAS (9 tui)                (statement #1b)
               _cli/config.py  _RECOGNIZED_SECTIONS/_TOP_LEVEL_KEYS/_KEYS,
                               _VALID_OUTPUT_FORMATS                               (statement #2, drift-tested)
               _cli/main.py    "plugins"/"disabled"/"aliases" ×4 sites each
               _cli/builtins.py config_path: "pyproject.toml", ".functualize.toml"; config_show field list
 docs/cli/config.md  schema + env tables by hand                                   (statement #5)

 Each arrow that would remove a statement is illegal: _config/_discovery/_engine/_app → _cli is
 forbidden ("Peer layers are independent", "Internal never imports public"); _cli → _config is
 forbidden ("_cli uses public API only").
```

**Smells the BEFORE carries:** *Duplicate Code* (five statements of one
vocabulary, two held together only by drift tests); *Shotgun Surgery*
(adding a setting means editing `func_settings.py`, `_cli/config.py`, docs,
and, for a list key, `project_dirs.py` and `filter_factory.py`);
*Primitive Obsession* (a setting is a bare string at 91 read sites, and flags
travel as `dict[str, Any]` keyed by the same strings); *Middle Man*
(`FuncSetting` → `_as_setting` → `Setting` projects one record onto an
identical one); *Long Method* (`register_builtin_commands`, 728-3038).
Pre-existing **forbidden patterns** in the region: hard-coded config file
names (`builtins.py:2419-2420`); module-level mutable registries
(`_REGISTERED`, `_PREBOOT_OVERRIDES` at `func_settings.py:274`, `:283`).

## 3. Candidate AFTERs

| | Owner | Verdict |
|---|---|---|
| R1 | Revision 1: a checker module plus a drift test | **Rejected by the maintainer.** It adds a sixth statement |
| R2 | Owner in `_cli/data/` (where `FUNC_SCHEMA` is) | Rejected: `_config`, `_discovery`, `_engine` and `_app` cannot import `_cli`, so statements 3 and 4 stay |
| R3 | Owner in `_config/` | Rejected: `_cli` may not import `_config`, and `_discovery`/`_engine` are its peers |
| R4 | Owner in public `app/config.py` | Rejected: internal layers may not import public folders, which is exactly why `filter_factory.py` repeats the fields today |
| **R5** | **func's declaration as data in `_types/`, on the existing `AppSettingsSchema` type, re-exported publicly; every statement becomes a derivation; a source ratchet** | **Chosen.** `_types` is the only layer every consumer may import |

Introduced-smell check for R5:
- *Shotgun Surgery* is removed: a new setting is one `Setting(...)` line,
  plus docs, which the docs ratchet catches.
- *Middle Man* is removed: `FuncSetting` becomes a thin view, not a second
  record.
- Logic in `_types`: `keys_in`, `value_in` and `setting` are pure queries on
  frozen data. They follow the methods already on `AppSettingsSchema`
  (`env_var_for`, `section_in_file`) and MCH-194's `_types/naming.py`
  exception. No I/O and no state.
- *Large Class* risk: `AppSettingsSchema` gains four small methods, far from
  ~500 LOC (the file is 155 lines).
- No peer-layer import is added. `_types` still imports nothing internal.

### AFTER

```
 [_types]  _types/settings.py               Setting(+places, listed, env; type map/records),
                                            AppSettingsSchema(+setting, sections, keys_in, value_in)
              ▲
           _types/functualize_settings.py   ROOT, JOBS_DIRECTORIES, …, PLUGINS_DISABLED, ALIASES,
                                            VAULT_SECRET, every catalog setting → FUNCTUALIZE_SETTINGS   [THE ONE STATEMENT]
              ▲ imported directly by internal layers           ▲ public re-export
              │                                                │ functualize.app.config (+ functualize.plugin types, unchanged)
 [_config]   project_dirs: LIST_KEYS = derived; file names from .sources; merge: ROOT.key;
             vault_declarations: VAULT_SECRET.key
 [_discovery] filter_factory: fingerprint fields = [discovery] settings (+ pre_filter) — drift test retired
 [_app]      boot: PLUGINS_STRICT;          [_engine] executor: SHELL_PROGRAM, SHELL_SUDO_PASSWORD
 [app]       config.DiscoveryConfig fields pinned to [discovery] keys by test; utils reads via value_in
 [_cli]      data/func_settings: views over FUNCTUALIZE_SETTINGS (FuncSetting, FUNC_SETTINGS, FUNC_SCHEMA keep shape)
             data/settings_schema: SettingSchema derived from Setting; SETTING_SCHEMAS derived
             config: _RECOGNIZED_* and _VALID_OUTPUT_FORMATS derived; discovery resolved by looping the section
             main: PLUGINS_DISABLED / ALIASES / JOBS_DIRECTORIES via value_in
             data/config_vocabulary: unknown-key check = keys not in keys_in(); suggestion; describe()
             builtins config_path: file names from .sources; annotation;   info: config.unknown_keys
 tests/      ratchet: collection literals of config keys outside the owner = 0;
             read-position literals ≤ baseline (shrink-only); docs/cli/config.md ⊆ declaration
```

Legality: every new edge points at `_types` (allowed for all layers) or at a
public re-export (allowed for `_cli`). `uv run lint-imports` is a gate on
each wave.

## 4. Technical approach

1. **Pin first (AC14).** Before moving anything, one test records today's
   values: catalog order, defaults, choices, bounds, `cli_flag`/`phase`, env
   names, `_RECOGNIZED_*`, `LIST_KEYS`, the fingerprint field list, the file
   names, `cli.output` choices and the `resolve_env_overrides()` mapping for
   every documented variable. The refactor must leave them equal.
2. **Declare.** `_types/functualize_settings.py` holds one named `Setting`
   per key. List keys declare `places` in today's lookup order
   (`project_dirs.py:363-387`: top level first, then `[discovery]`). The
   table-shaped keys (`ALIASES` = `map`, `VAULT_SECRET` = `records`) and
   `ROOT` are `listed=False`, so no settings row appears that does not exist
   today. Env participation equals today's mapping (risk §7.1).
3. **Derive**, one owner-file group per task (tasks.md waves 1–2). No
   behaviour change, AC14 green after every task.
4. **Check** (waves 3–4): `config_vocabulary.find_unknown_keys` is "not in
   `FUNCTUALIZE_SETTINGS.keys_in(section)` ∪ registered", skipping `map`
   sections and unknown tables (3a). Suggestions use `difflib`, cutoff 0.6.
   Surfaces are as in Revision 1.
5. **Ratchet** (wave 5): AST tests that fail on a new collection literal of
   config key names, or a read-position literal above the per-file baseline,
   outside the owner, plus the docs ratchet (AC15).
6. **Registration** stays as it is: `register_settings` takes declared
   `Setting`s. tui registers the declared `TUI_*` settings, which only
   controls display. Validation knows `tui.*` statically.

## 5. Blast radius and sequencing

- Files: the hit sets in `tasks.md` — 18 source files (2 new) plus tests and docs.
- **Overlaps MCH-194**, whose plan edits `_cli/main.py`, `_cli/dispatch.py`,
  `_cli/info.py` and `_cli/builtins.py`. This plan touches `main.py`,
  `info.py` and `builtins.py` (not `dispatch.py` under M2-b). Whichever lands
  second rebases. Waves 0–2 avoid those files except `main.py` (task 2.4),
  which is placed last so that it can rebase onto MCH-194.
- **Feeds MCH-188** (SD/17104898, not started): its root-bounded walk reads
  `ROOT` and the file names from the declaration instead of new literals.

## 6. Decisions

- **D1 (taken):** 1a + 2a + 3a, unchanged.
- **M1 — shape scope** (member): record vocabulary unification as in scope
  on SD/17137669 (v3).
- **M2 — flag plumbing** (member): (a) declaration + config-document reads,
  flag-plumbing dicts kept as ratchet baseline; or (b) also type the plumbing.
  Recommended (a): see the hand-off.
- **M3 — the global file's stderr warning** (member): recommended removing it
  as a separate path; one checker, reported on 2a surfaces for every file.
- **M4 — module-level registries** (member): `_REGISTERED`/`_PREBOOT_OVERRIDES`
  are a pre-existing forbidden pattern in a file this plan edits. Recommended
  follow-up ticket; this plan does not extend them.
- **D2 (revised):** the hard-coded file names in `config_path` are removed
  (they come from `FUNCTUALIZE_SETTINGS.sources`). The cwd-only listing stays,
  because changing it is MCH-188's concern. This supersedes Revision 1's
  "leave it": the literal names were the forbidden part, and the declaration
  now owns them.

## Surviving smells

| Smell (catalogue) | Where | Why | Maintainer review? |
|---|---|---|---|
| *Primitive Obsession* | CLI-flag plumbing dicts keyed by setting names: `_cli/main.py:304-320`, `_cli/dispatch.py:401-423`, `app/utils.py:843-867` | Under M2-(a) they stay, pinned by the shrink-only ratchet. Typing them rewrites `dispatch.py`/`main.py` while MCH-194 is rewriting the same files | **Yes** (M2) |
| Forbidden pattern, pre-existing: module-level mutable state | `func_settings.py:274` `_REGISTERED`, `:283` `_PREBOOT_OVERRIDES` | Not introduced, not extended. Removing them threads registration through the app (the second-app seam), which is separate work | **Yes** (M4) |
| *Long Method*, pre-existing | `register_builtin_commands` | +≤ 6 lines | No |
| Logic in `_types` | `AppSettingsSchema.setting/sections/keys_in/value_in` | Pure queries on frozen data, same idiom as `env_var_for` and MCH-194's naming exception | No, but named so the review sees it |

Revision 1's *Duplicate Code* entry (the restated `_config` keys) is
**removed**. It no longer exists in this design.

## 7. Risks

1. **Env mapping asymmetry.** `extra_directories` is set at the top level
   (`FUNCTUALIZE_EXTRA_DIRECTORIES`, documented), but `exclude_patterns` is
   not (`FUNCTUALIZE_DISCOVERY_EXCLUDE_PATTERNS`). The declaration must
   reproduce both. The AC14 pin catches a mistake. Unifying them would be a
   behaviour change and is not proposed.
2. **Display.** `listed=False` keys must not add settings-panel rows or help
   entries. AC14 pins `SETTINGS_ORDER`.
3. A job named after a settings section: unchanged from Revision 1, report
   only.
4. **H2 (warm boot).** The declaration is imported where the names are
   already needed today (`_config`, boot). The checker stays lazy. Gate 6.1.
