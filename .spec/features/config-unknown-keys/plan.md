# config-unknown-keys — Plan (Revision 5)

> **Revision 5 (2026-10-23).** This revision corrects one invariant this plan
> stated too broadly, and adds the surface vocabulary (F16). It changes no
> AFTER shape for settings. See §6 (M8) and `tasks.md` → *Revision 5*.

## Alignment

- **Shape:** *Shape Intent — Unknown Keys in .functualize.toml (what is
  checked, how loudly, where)*, Confluence `SD/17137669` **v3** (updated
  2026-10-20 03:48:22 UTC), `Authority = Approved`. Read live on 2026-10-21
  before this revision. The three inline approval comments (`18808859`,
  `18972740`, `18808867`, "follow recommendation") are attached.
- **Decisions:** v2 approved D1 = 1a + 2a + 3a. v3's decision record holds
  M1–M4 and the rule from MCH-190 comment `01a15669`. M5–M7 were answered by
  the maintainer on MCH-190 comment `01a15ee0` (2026-10-21 14:32 UTC):
  "M5 = follow your recommendation, remove it. M6 = follow your
  recommendation, for consistency. M7 = follow your recommendation". The
  page's decision-record row still reads "M5–M7 | Open"; this revision
  builds on `01a15ee0`, and the page row is reported in the hand-off rather
  than edited unasked.
- **In scope, verbatim from v3:**
  - v2: "Unknown **scalar/array keys** at the top level and inside known
    setting sections (`[cli]`, `[discovery]`, registered sections) of
    `.functualize.toml` and `pyproject.toml` `[tool.functualize]`"; "A "did you
    mean" suggestion from the known vocabulary"; "`func builtin config path`
    and the JSON of `func builtin info`"; "The XDG global `config.toml` gets
    the same check".
  - v3: "One declaration of the settings vocabulary in the types layer; every
    reader, flag, env var, file list and doc derives from it"; "One list of
    settings files and one resolver for every reader (CLI, TUI, app, engine,
    builtins)"; "Settings-backed flags and environment variables derived from
    the declaration; flag values carried typed, not as string-keyed dicts";
    "No process-wide registries; an app declares its own settings at
    construction, through public API"; "`config path` lists the files
    resolution actually uses; `✓ used` = supplies a value in effect,
    `○ found` = exists but supplies none (what the docs already say)"; "A job
    or group named like a settings section, and a settings table in a
    `config.*.toml` job file, are reported"; "Every defect found on the way,
    listed as F2–F15 in the feature's `spec.md`".
- **Out of scope, verbatim:** "Validating **values** (types, enum members) — a
  separate concern"; "Unknown **tables** that could be job sections —
  validating them needs the discovered job set; deferred (see dimension 3)";
  "Adding a `--json` flag to `config path` — owned by SD/2850883's
  output-flag conventions"; "Unknown parameters inside a job section — per-job
  schema validation"; "Where the upward walk stops beyond `root = true`
  (bounding by a project root): SD/17104898, MCH-188. After this change it is
  one function to edit".
- **Must not change, verbatim (v3):** "for a project whose settings live only
  in the current directory and hold only known keys, `config path` output is
  byte-identical. No run's exit code changes because of the check. Every
  setting's value is unchanged except as listed below."
- **D3:** `config path` keeps the status word `used` (with the v3 meaning
  above) and adds the annotation. It is not reopened.

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

## 2. Architecture pass — today (`bb3aac77`)

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
 public → _cli settings reads: app/adapters/cli.py, app/adapters/surface_gate.py → _cli.data.func_settings;
   app/commands.py → _cli.config.resolve_cli_config
 public → _cli other edges (rev5, measured at 40c2a503, 15 sites in all): _cli.orchestrator (surface
   vocabulary, F16); _cli.builtins, _cli.info, _cli.inline_tui, _cli.annotation_utils (delivery — M8)
```

**Smells (catalogue names) and forbidden patterns in the BEFORE:**
*Duplicate Code* (vocabulary ×5, flags ×3, resolvers ×3); *Divergent Change*
(F3a, F3b, F4: the copies drifted); *Shotgun Surgery* (a new setting touches
up to seven files); *Primitive Obsession* (91 string reads; flags travel as
`dict[str, Any]`); *Middle Man* (`FuncSetting` → `_as_setting` → `Setting`);
*Temporal Coupling* (a setting exists only after a module is imported —
STATUS #22); *Long Method* (`register_builtin_commands` 2326 lines,
`resolve_cli_config` 306, `_extract_global_options` 164). **Forbidden:**
module-level mutable registries (`func_settings.py:274`, `:283`); hard-coded
config file names (`builtins.py:2419-2420`); god classes in files this plan
edits: `JobExecutionEngine` 2568 lines (`_engine/executor.py`) and
`FunctualizeInlineTUI` 2704 lines (`_cli/tui/app.py`) — M7 closed: PR 2.

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
- `_cli` → public re-exports only. **No public folder reads a setting, a
  settings store or a settings vocabulary through `_cli`.** Every settings
  read goes through `app.settings` / the declaration (AC31). Rev3/rev4 wrote
  this as "the public `app/adapters` stop importing `_cli`". That was broader
  than `spec.md` F7, AC21 and contracts C5/C6 require: they put the adapters'
  *settings* reads on the public seam, and say nothing about the delivery
  imports listed under M8.

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
           adapters/cli.py, surface_gate.py   read app.settings / schema (no settings import from _cli; delivery edges: M8)
           adapters/surface_gate.py    + RenderSurface preference ladder (moved from _cli/orchestrator.py, F16)
[_types]   enums.py                    + RenderSurface — the one statement of the surface values
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

1. **Pin first.** Literal expected values recorded at `bb3aac77`: catalog,
   flags, env names, and resolved values for a fixture matrix (single dir,
   nested with and without `root`, global only, env, flags). §3.8 rows are
   pinned as today's behaviour in a separate test that the fix flips
   deliberately, so each change is visible as a diff of expectations.
2. **Declare** in `_types`. Flags taken verbatim from `_cli/main.py:140-223`.
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
7. **Reserved names** (F14). A discovered job or group named like a declared
   settings section produces a `DiscoveryFailure` with its own `error_type`,
   built beside `job_name_collision` (`_types/discovery_report.py:152`) and
   emitted from `_discovery/collisions.py`. It therefore reaches every surface
   #118 already wired for collisions. A job config file with a reserved
   top-level table is reported through the same record from `FileSource`.
8. **Builtins split** (F10) — mechanical, `func builtin --help` byte-identical.
9. **Docs, fixtures, STATUS.** Close STATUS #22 and #29 (M5: removed, no consumer arrived) in
   `.spec/STATUS.md`. Migrate the durable rule ("one declaration in
   `_types/functualize_settings.py`; ratchets") to an ADR before the cleanup
   commit.

## 5. Blast radius and sequencing

- Source files: 30 existing files edited (the `[F]` hit sets in `tasks.md`),
  4 new modules, and `_cli/builtins.py` replaced by an 11-module package.
- **MCH-194 has landed** (`bb3aac77`, #118), and this branch is rebased onto
  it. There is no longer a parallel branch to conflict with. #118 added the
  typed collision channel (`_types/discovery_report.py:78` `DiscoveryFailure`,
  `:152` `job_name_collision`, produced in `_discovery/collisions.py`), which
  F14 reuses with its own `error_type`, so no second report channel appears.
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
| M5 | `[tool.functualize] skill` (STATUS #29) | **closed** (`01a15ee0`): removed; `SCRIPT_METADATA` = `job` only; a script that writes it gets the existing unknown-key warning |
| M6 | the one environment name of `extra_directories`/`exclude_patterns` | **closed** (`01a15ee0`): `[discovery]` canonical — `FUNCTUALIZE_DISCOVERY_EXTRA_DIRECTORIES`, `FUNCTUALIZE_DISCOVERY_EXCLUDE_PATTERNS`; `FUNCTUALIZE_EXTRA_DIRECTORIES` is no longer read. Both keys keep both accepted file places |
| M7 | the god classes and long functions in files this plan edits | **closed** (`01a15ee0`): (a) — PR 2 on this issue and branch line, after PR 1 merges, with its own architecture pass before any engine/TUI edit |
| D3 | the status word `used` | answered: kept, with the v3 meaning, plus the annotation |
| M8 | the 9 public→`_cli` **delivery** imports that are not settings: `app/adapters/cli.py:838` `:1360` `:1621` (`_cli.info`), `:953` (`_cli.builtins`), `:1255` and `app/adapters/tui.py:54` (`_cli.inline_tui`), `app/commands.py:356` (`_cli.builtins.get_builtin`), `app/adapters/click_params.py:92` `:722` (`_cli.annotation_utils`) | **open — for the maintainer.** (a) record as the documented delivery layer (`contributor/architecture/codemaps/dependencies.md:80-90` lists `app/adapters/*` and `_cli/*` as one delivery layer; no import-linter contract forbids it; each import is function-local by design to avoid the `app` ↔ `_cli` cycle). (b) treat the package-level `app` ↔ `_cli` cycle as a found issue and put it in **PR 2's architecture pass**, which already decomposes `FunctualizeInlineTUI` (the `inline_tui` path), as an adapter extension seam. Recommended: **(b)**, because the cycle is real at the package level, the no-leftovers rule applies, and PR 2's pass is where the delivery layer is being reshaped anyway. Either way PR 1 does not change these 9 sites; 8.1 pins them so the outcome is visible |

## Surviving smells

| Smell | Where | Why | Maintainer review? |
|---|---|---|---|
| Forbidden: god class (pre-existing) | `JobExecutionEngine` `_engine/executor.py:205-2772` (2568 lines), `FunctualizeInlineTUI` `_cli/tui/app.py:125-2828` (2704 lines) | Not introduced and not grown: PR 1 replaces one settings read in each. **Maintainer-accepted for PR 1 only** (M7 = (a)); PR 2 on this issue decomposes them after PR 1 merges | Answered (M7) — owner: PR 2 |
| *Long Method* (pre-existing, files edited; AST at `bb3aac77`) | `_cli/main.py` `_run_cli` 358 (`:2033`), `_dispatch_group` 278 (`:959`), `_handle_job` 250 (`:1353`), `cli_app` 224 (`:229`), `_handle_single_file` 219 (`:1670`); `_app/boot.py` `boot_standard` 463, `boot_static` 241, `wire_children_to_pipeline` 157; `app/utils.py` `auto_discover` 192, `vault_sync` 185; `app/adapters/cli.py` `_register_callback` 217; `_engine/executor.py` `_execute_lifecycle` 359 | Same as above. `resolve_cli_config` (306) and `_extract_global_options` (164) are **removed** by this plan, not surviving. `register_builtin_commands` (2326) is split in PR 1 (task 1.3) | Answered (M7) — owner: PR 2 |
| Logic in `_types` | `AppSettingsSchema.extend/keys_in/value_in/flag` | Pure queries on frozen data; established idiom | No; named for the review |
| Package-level cycle `functualize.app` ↔ `functualize._cli` (pre-existing) | the 9 delivery imports of M8 | Not introduced, not grown; function-local imports keep it import-safe. Disposition is M8 | **Yes** (M8) |

Every other smell named in §2 is removed by a task in `tasks.md`.

## 7. Risks

1. **Vault for `shell.sudo_password`.** Today a vault value can reach it only
   through the job chain's `[shell]` section. Task 4.1 pins today's vault
   behaviour with a test *before* moving, and keeps the result through the
   settings chain's vault source.
2. **Pre-boot cost.** Resolution before boot exists today
   (`resolve_cli_config`). `tests/perf/test_startup_budget.py` gates the
   warm path (AC10).
3. **`master` moves under the branch.** It moved twice during Plan
   (`1b73983c`, `bb3aac77`). Every Execute wave starts by rebasing and
   re-running the pin. The ratchets make a bad rebase fail loudly rather
   than silently re-add a statement.
4. **Hidden readers.** A reader the AST walk misses (a dynamic key) would
   survive. Gate: after wave 5, `rg` for every declared key name in `src/`
   outside the owner must return only `Setting` constant references and the
   resolver.
