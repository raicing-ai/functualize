# config-unknown-keys — Plan (Revision 3)

## Alignment

- **Shape:** *Shape Intent — Unknown Keys in .functualize.toml (what is
  checked, how loudly, where)*, Confluence `SD/17137669` **v3**,
  `Authority = Approved`. v2 (2026-10-17) approved 1a + 2a + 3a through the
  maintainer's three "follow recommendation" inline comments (`18808859`,
  `18972740`, `18808867`). v3 (2026-10-20) records the maintainer's
  2026-10-19 answers on MCH-190 (comment `01a15669`): M1 (amend the shape),
  M2 (b), M3 (remove the global warning), M4 (fix the registries in scope),
  and the rule "every found issue must be solved and fixed in scope".
- **In scope, in the page's words (v3):** v2's three in-scope rows, plus
  "one declaration of the settings vocabulary in the types layer", "one list
  of settings files and one resolver for every reader", "settings-backed flags
  and environment variables derived from the declaration", "no process-wide
  registries", and "every defect found while doing the above" (`spec.md`
  §1.2, F2–F15).
- **Out of scope, in the page's words:** v2's four rows, unchanged; "where the
  upward walk stops beyond `root = true` — SD/17104898 (MCH-188)".
- **Must not change (v3):** "for a project whose settings live only in the
  current directory and hold only known keys, `config path` output is
  byte-identical; no run's exit code changes because of the check; every
  setting's value is unchanged except where the page's *User-visible changes*
  table says so".

## 1. Skills consulted

- `python-design-patterns` (in-repo): single responsibility, composition,
  "God-class decomposition".
- `design-patterns-refactoring` (user-level, Refactoring.Guru catalogue):
  *Duplicate Code*, *Shotgun Surgery*, *Divergent Change*, *Primitive
  Obsession*, *Middle Man*, *Long Method*, *Large Class*, *Temporal
  Coupling*-by-registration; techniques *Extract Class*, *Move Function*,
  *Replace Data Value with Object*, *Introduce Parameter Object*,
  *Replace Global with Parameter*.
- Precedent: MCH-194 `job-name-command-path/plan.md` (`5f27149f`). The
  pattern is one typed owner in `_types`, public re-export, every surface
  deriving from it, and a source ratchet.

## 2. Architecture pass — today (`91947bb4`)

Tools: zvec-grep (worktree index), serena (`find_referencing_symbols` on
`full_report`, `_functualize_table`), graphify (`get_neighbors full_report`),
AST walks (counts in `spec.md` §1.2), `uv run lint-imports` (7 kept, 0 broken),
live experiments (F3a, F3b).

### BEFORE

```
                         settings files (.functualize.toml, [tool.functualize], global config.toml)
                                │ read by 4 different readers
   ┌────────────────────────────┼──────────────────────────────┬──────────────────────────────┐
   ▼                            ▼                              ▼                              ▼
[_config] project_dirs     [_cli] config.read_global_config  [_cli] config.resolve_cli_       [_cli] builtins.config_path
 resolve_project_config     (own filter + own warning,        config_layers (walk, NO root    (cwd probes, own tomllib,
 (walk + root stop)          drops [plugins]/[shell])          stop) → FuncSettingsStore       "used" = exists)
   │                            │                              │
   ▼                            ▼                              ▼
 RESOLVER 1: _cli/config.resolve_cli_config → CliConfig    RESOLVER 2: FuncSettingsStore (+ _REGISTERED,
   (discovery filters, cli.output, aliases, dotenv…)          _PREBOOT_OVERRIDES globals) → TUI panel, cli.inline_tui,
   │                                                          surface gate, TUI shell.program, root generated flags
   ▼
 FunctualizeApp(config_sources=…)  ──►  RESOLVER 3: job ResolutionChain (config.*.toml, un-prefixed env)
                                          ◄── _app/boot plugins.strict, _engine/executor shell.program/sudo_password

 vocabulary statements: _cli/data/func_settings._BASE_SETTINGS (+ tui_settings registered at import),
 _cli/config._RECOGNIZED_*, _config/project_dirs.LIST_KEYS, _discovery/filter_factory fingerprint fields,
 _types/flag_grammar + _cli/main click options + _cli/dispatch parsing (flags), docs tables
 public → internal leaks: app/adapters/cli.py, app/adapters/surface_gate.py → _cli.data.func_settings
```

**Smells (catalogue names) and forbidden patterns in the BEFORE:**
*Duplicate Code* (vocabulary ×5, flags ×3, resolvers ×3); *Divergent Change*
(F3a, F3b, F4: the copies drifted); *Shotgun Surgery* (a new setting touches
up to seven files); *Primitive Obsession* (91 string reads; flags travel as
`dict[str, Any]`); *Middle Man* (`FuncSetting` → `_as_setting` → `Setting`);
*Temporal Coupling* (a setting exists only after a module is imported —
STATUS #22); *Long Method* (`register_builtin_commands` 2311 lines,
`resolve_cli_config` 306, `_extract_global_options` 164). **Forbidden:**
module-level mutable registries (`func_settings.py:274`, `:283`); hard-coded
config file names (`builtins.py:2419-2420`); god classes in files this plan
edits: `JobExecutionEngine` 2568 lines (`_engine/executor.py`) and
`FunctualizeInlineTUI` 2679 lines (`_cli/tui/app.py`) — decision M7.

## 3. Candidate AFTERs

| Question | Candidates | Chosen, and why |
|---|---|---|
| Where the declaration lives | `_cli/data` · `_config` · public `app/config` · `_types` | **`_types`** — the only layer every consumer may import (`_discovery`'s own comment says why the others fail) |
| What resolves settings | keep `resolve_cli_config` · keep `FuncSettingsStore` · a new settings resolver · **a `ResolutionChain` instance for settings** | **A chain instance.** The chain is already the system's resolver with provenance (`ResolvedValue.source_type/source_id/alternatives`). A new resolver would be a fourth. Two chain instances over two document kinds (settings documents; job `config.*` files) is one resolver *logic*, not duplication |
| Which files | `list_project_config_files` · `resolve_project_config` · cwd probes | **One `settings_layers()` in `_config`**, ResourceLocator walk with the `root = true` stop. The only reader of settings files |
| Registries | keep, fix ordering · DI registry · **declaration passed at construction** | **`ConfigSources(settings=schema)`** (grouped frozen config, the constitution's constructor idiom); pre-boot flags passed as data |
| Flags | keep three tables · **generate from `Setting.cli_flag`** | Generated. `flag_grammar` keeps only non-settings flags |
| `register_builtin_commands` | leave · **package of one module per group** | *Extract Function* + *Move Function*; same import path via package `__init__` |

Introduced-smell check:
- The chain gains a list-merge policy driven by the declaration (`merge` for
  `list` settings: concatenate + dedupe, which is today's rule) in one place.
  No *Divergent Change*.
- `ResolvedSettings` is a value object, not a service. No new global.
- `_types` gains pure queries (`keys_in`, `value_in`, `flag`, `extend`) on
  frozen data, in the idiom of the existing `env_var_for`/`section_in_file`
  and MCH-194's `_types/naming.py`.
- No peer-layer import: `_config` → `_types` only; `_app`/`_engine` receive
  `ResolvedSettings` as data via `ConfigSources`.
- `_cli` → public re-exports only. The public `app/adapters` stop importing
  `_cli`.

### AFTER

```
[_types]   settings.py                 Setting(+places, listed, surface, env), AppSettingsSchema(+extend, keys_in, value_in, flag)
           functualize_settings.py     FUNCTUALIZE_SETTINGS (+ named Setting constants), SCRIPT_METADATA      ← the ONE statement
           flag_grammar.py             non-settings flags only; settings flags = {s.cli_flag for s in schema}
              ▲ (every layer)
[_config]  settings_layers.py  NEW     settings_layers(schema, cwd)  ← the ONLY reader of settings files (walk + root stop)
           settings_resolution.py NEW  resolve_settings(schema, layers, flags, environ, vault) → ResolvedSettings
                                       = one ResolutionChain: CliSource → vault → EnvSource(prefix) → LayerSource×N → DefaultSource
           sources.py                  EnvSource(prefix=…), LayerSource (mapping-backed, source_id = file path)
           project_dirs / merge / vault_declarations: names from the declaration
[_discovery] filter_factory            fingerprint fields = declaration's [discovery] filters (+ pre_filter)
              ▲ re-exported
[app]      config.py                   FUNCTUALIZE_SETTINGS, constants, SettingsLayer, ResolvedSettings, resolve_settings;
                                       ConfigSources(settings=…, resolved=…)
           core / FunctualizeApp       .settings -> ResolvedSettings
           adapters/cli.py, surface_gate.py   read app.settings / schema (no _cli import)
[_app]     boot                        plugins.strict from app.settings; vault re-resolution of secret settings
[_engine]  executor                    shell.* from app.settings (data), never the job chain
[_cli]     dispatch / main             flags generated from the schema → Mapping[Setting, value] → resolve_settings
           config.py                   CliConfig = typed projection of ResolvedSettings (no resolution of its own)
           data/func_settings.py       FuncSettingsStore = editor/write-back over ResolvedSettings (no globals)
           data/config_vocabulary.py   unknown keys = not in schema.keys_in()
           builtins/ (package)         one module per group; config_path lists settings_layers, status from provenance
           tui/                        rows from schema (surface="tui"), values from app.settings
           pep723.py                   SCRIPT_METADATA
tests/spec ratchets: vocabulary literals, read-position literals, settings-file reads, job-chain reads of
           settings sections, registries, flag strings, docs ⊆ declaration
```

## 4. Technical approach (one paragraph per area; tasks in `tasks.md`)

1. **Pin first.** Literal expected values recorded at `91947bb4`: catalog,
   flags, env names, and resolved values for a fixture matrix (single dir,
   nested with and without `root`, global only, env, flags). §3.8 rows are
   pinned as today's behaviour in a separate test that the fix flips
   deliberately, so each change is visible as a diff of expectations.
2. **Declare** in `_types`. Flags taken verbatim from `_cli/main.py:117-200`.
   Env names from `env_var_for`. Defaults, choices and bounds from
   `_BASE_SETTINGS` and `SETTING_SCHEMAS`.
3. **Layers and resolver** in `_config`. `EnvSource` gains a `prefix`, and
   `LayerSource` reads one layer's table by section/key with `places` order.
   List merge equals `_merge_lists_dedup` (`_cli/config.py:287`).
4. **App seam.** `ConfigSources(settings=…)`. The CLI resolves before boot,
   using the pre-boot flag scan as the flag layer, and hands the snapshot in.
   Boot re-resolves only `secret` settings with the app's vault source, and
   the result is `app.settings`.
5. **Consumers switch**, one owner-file group per task. Each deletes its own
   statement, so the ratchet baselines fall as tasks land.
6. **The check and the surfaces** (approved v2), on the new layers and
   provenance.
7. **Reserved names** (F14) via the existing `discovery_failures` channel.
   Job config files with a reserved table go through `FileSource`'s existing
   event-bus reporting, surfaced by the same channel.
8. **Builtins split** (F10) — mechanical, `func builtin --help` byte-identical.
9. **Docs, fixtures, STATUS.** Close STATUS #22 (and #29 per M5) in
   `.spec/STATUS.md`. Migrate the durable rule ("one declaration in
   `_types/functualize_settings.py`; ratchets") to an ADR before the cleanup
   commit.

## 5. Blast radius and sequencing

- Source files: 30 existing files edited (the `[F]` hit sets in `tasks.md`),
  4 new modules, and `_cli/builtins.py` replaced by an 11-module package.
- **MCH-194** (`fix/job-name-command-path`) edits `_cli/main.py`,
  `_cli/dispatch.py`, `_cli/info.py`, `_cli/builtins.py`, `_cli/tui/*`. The
  maintainer accepts the conflicts. Whichever merges second rebases; the
  builtins split (wave 1) is mechanical, so its rebase is a re-run of the move.
- **MCH-188** reads `settings_layers()` for its root-bound decision: one
  function to change.

## 6. Decisions

| # | Decision | State |
|---|---|---|
| D1 | 1a + 2a + 3a | approved (v2) |
| M1 | amend SD/17137669 to v3 | **done** 2026-10-20 on instruction |
| M2 | (b): type the flag plumbing too | taken |
| M3 | remove the global file's own warning | taken |
| M4 | remove the registries in scope | taken |
| M5 | `[tool.functualize] skill` (STATUS #29): remove now, or keep it declared and transitional | **open** — recommended: remove |
| M6 | the canonical name, and therefore the one env var, of `extra_directories`/`exclude_patterns` | **open** — recommended: `[discovery]` (their settings rows and every docs example), so `FUNCTUALIZE_DISCOVERY_EXTRA_DIRECTORIES`; the documented `FUNCTUALIZE_EXTRA_DIRECTORIES` goes |
| M7 | the god classes and long functions in files this plan edits | **open** — recommended: same carrier, a second PR after the config PR, with its own architecture pass |

## Surviving smells

| Smell | Where | Why | Maintainer review? |
|---|---|---|---|
| Forbidden: god class (pre-existing) | `JobExecutionEngine` (2568 lines), `FunctualizeInlineTUI` (2679 lines) | Not introduced and not grown: this plan's edits there replace one settings read each. Fixing them is M7 | **Yes** (M7) |
| *Long Method* (pre-existing, files edited) | `_cli/main.py` `_run_cli` 352, `_dispatch_group` 278, `_handle_job` 241, `cli_app` 224, `_handle_single_file` 219; `_app/boot.py` `boot_standard` 463, `boot_static` 241, `wire_children_to_pipeline` 157; `app/utils.py` `auto_discover` 192, `vault_sync` 185; `app/adapters/cli.py` `_register_callback` 217; `_engine/executor.py` `_execute_lifecycle` 359 | Same as above. `resolve_cli_config` (306) and `_extract_global_options` (164) are **removed** by this plan, not surviving | **Yes** (M7) |
| Logic in `_types` | `AppSettingsSchema.extend/keys_in/value_in/flag` | Pure queries on frozen data; established idiom | No; named for the review |

Every other smell named in §2 is removed by a task in `tasks.md`.

## 7. Risks

1. **Vault for `shell.sudo_password`.** Today a vault value can reach it only
   through the job chain's `[shell]` section. Task 4.1 pins today's vault
   behaviour with a test *before* moving, and keeps the result through the
   settings chain's vault source.
2. **Pre-boot cost.** Resolution before boot exists today
   (`resolve_cli_config`). `tests/perf/test_startup_budget.py` gates the
   warm path (AC10).
3. **Conflicts with MCH-194.** Accepted by the maintainer. The ratchets make
   a bad merge fail loudly rather than silently re-add a statement.
4. **Hidden readers.** A reader the AST walk misses (a dynamic key) would
   survive. Gate: after wave 5, `rg` for every declared key name in `src/`
   outside the owner must return only `Setting` constant references and the
   resolver.
