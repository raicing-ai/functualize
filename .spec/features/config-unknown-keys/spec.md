# config-unknown-keys — Specification (Revision 5)

A key that is not a functualize setting is not accepted in silence, and the
settings vocabulary that decides it is stated **once**. Every reader, resolver,
flag, environment variable, file list, report and document derives from that
one declaration.

Shape: Confluence `SD/17137669` **v3** (scope amended 2026-10-20 on the
maintainer's instruction, MCH-190 comment `01a15669`). It keeps v2's approved
1a + 2a + 3a and adds vocabulary, resolver and registry unification (decisions
M1–M4), so nothing found on the way is left as a follow-up. `plan.md` →
`## Alignment` quotes it. Revision 4 folds in the maintainer's closed
answers to M5–M7 (MCH-190 comment `01a15ee0`, 2026-10-21): remove the PEP 723
`skill` key, use the `[discovery]` environment names, and split the
god-class work into PR 2.

Base: `master` `bb3aac77`. Every line citation and count below was
re-measured on that head on 2026-10-21 (`git grep -n` per anchor; AST walks),
and F1, F3a and F3b were re-run there (isolated `HOME`, the worktree's
editable venv).

## 1. Problem

### 1.1 The reported defect (FOSS-127)

```console
$ cat .functualize.toml
root = true
roots = true                       # typo for `root`
definitely_not_a_setting = 1
[cli]
outptu = "json"                    # typo for `output`

$ func builtin config path         # exit 0
  ✗ missing …/home/.config/functualize/config.toml
  ✗ missing …/pyproject.toml
  ✓ used    …/.functualize.toml    # no unknown key named
$ func builtin info --json | grep -c -i 'roots\|outptu\|definitely'
0
```

### 1.2 Everything else found on the way (all in scope — maintainer, 2026-10-19)

| # | Finding | Evidence |
|---|---|---|
| F2 | The vocabulary is stated five times, and 91 key names are read by string | AST walk of `src/functualize`: 13 collection literals restating ≥ 2 config key names, in 6 files; `_cli/data/func_settings.py:180` `_BASE_SETTINGS`; `_discovery/filter_factory.py:199` (its comment: repeated "because `_discovery` may not import the public `app.config`"); 91 read-position literals (`.get("k")`, `["k"]`, `"k" in`) in 9 files |
| F3a | **Three resolvers** for one set of settings, and they disagree. `root = true` is honoured by the CLI and ignored by the settings store | project `.functualize.toml` = `root = true`, parent `.functualize.toml` = `[cli] output = "json"` → `resolve_cli_config().output == "rich"`, `FuncSettingsStore.discover()` → `cli.output == "json"`; store layers include the parent file. The store feeds the TUI settings panel, `cli.inline_tui` (`app/adapters/cli.py:1215`), `shell.program` in the TUI (`_cli/tui/shell_mode.py:252`), the surface gate (`app/adapters/surface_gate.py:81`) |
| F3b | A declared setting is read by its consumer from a different file kind than the one it is declared, shown and documented in | `[shell] program` in `.functualize.toml`: store says `/bin/from-dotfunctualize`, engine (`_engine/executor.py:2016`, job `ResolutionChain`) says `None`. In `config.base.toml`: engine honours it, store/TUI show nothing. `plugins.strict` is resolved the same way (`_app/boot.py:2082`) |
| F4 | One setting, three environment names | `shell.sudo_password`: docs `FUNCTUALIZE_SUDO_PASSWORD` (`docs/guides/shell.md:97`), catalog rule `FUNCTUALIZE_SHELL_SUDO_PASSWORD`, engine's chain `SHELL_SUDO_PASSWORD` (un-prefixed `EnvSource`). And `extra_directories` takes `FUNCTUALIZE_EXTRA_DIRECTORIES` (documented) while `exclude_patterns` does not |
| F5 | Settings-backed CLI flags are stated three times, with a fourth generator beside them | `_types/flag_grammar.py:46` (`GLOBAL_OPTIONS_ALWAYS_VALUE`), `_cli/main.py:140-223` (16 click options; `@click.pass_context` at `:228`), `_cli/dispatch.py:294`, `:490` (hand parsing), and `Setting.cli_flag` generation (`app/adapters/cli.py:1274`) |
| F6 | Module-level mutable registries (constitution: forbidden) | `_cli/data/func_settings.py:274` `_REGISTERED`, `:283` `_PREBOOT_OVERRIDES`. Consequence recorded as `.spec/STATUS.md` #22: `tui.default_surface` is inert on a direct `func <job>` run because the shell registers it as an import side effect, and tests pass or fail by import order |
| F7 | The public API cannot express a second app's settings | `app/adapters/cli.py:1212`, `:1274`, `:1303` and `app/adapters/surface_gate.py:74` import `functualize._cli.data.func_settings`; `examples/standalone/deploy_tool/deploy_tool/main.py` imports `functualize._cli.*` and reads the private `store._layers` |
| F8 | `config path` invents its own file list, and its status words do not mean what the docs say | hard-coded names `_cli/builtins.py:2419-2420`; cwd-only probes vs. the upward walk resolution uses; `✓ used` = "exists" (`:2462-2467`) while `docs/cli/config.md:239-240` says "contributed values" / "all values were overridden" — never computed |
| F9 | The global file has its own reader, its own warning, and drops whole sections | `_cli/config.py:80-158`: warns per run for unknown keys in 5 recognised sections, silently drops `[plugins]`, `[shell]` and unknown top-level keys |
| F10 | *Long Method* | `register_builtin_commands`, `_cli/builtins.py:728-3053` (2326 lines by AST, 10 command groups as closures) |
| F11 | Test fixtures write keys functualize does not read where they are written | `tests/_cli/test_runtime_detection.py:219` (`scan_depth` top level), `tests/_cli/test_self_doctor.py:160` (`require_file_import` top level), `tests/spec/test_disabled_is_honoured_by_the_builtin_commands.py:121` (`name`), `tests/cli/test_config_upward_walk.py:134` (`extra`) |
| F12 | Docs disagree with the code | `docs/cli/config.md` *Error Handling* table ("Unrecognized section … silently ignored" / "key … warning") and env table; `docs/guides/shell.md:97` |
| F13 | A TRANSITIONAL in a file this change rewrites, deferred to "a separate follow-up" | `_types/flag_grammar.py` `OPTIONAL_VALUE_VALID_SET` rename |
| F14 | A job or group named like a settings section is ambiguous | a job `shell`, `cli`, `discovery`, `plugins`, `vault`, `tui` or `aliases` shares its config table with settings |
| F15 | `[tool.functualize] skill` in a PEP 723 script is accepted and read by nothing | `.spec/STATUS.md` #29, `_cli/pep723.py:53` `frozenset({"job", "skill"})` — **M5 closed: removed** (§3.10) |
| F16 | The surface values `{"panel", "stdout"}` are stated four times (rev5) | `_cli/orchestrator.py:28-29` (`RenderSurface`), `:76-79` (`_parse`), `job/decorators.py:115` (`_VALID_SURFACE_HINTS`), `_types/functualize_settings.py:43` (`tui.default_surface` choices); the public surface gate reaches it through `_cli` (`app/adapters/surface_gate.py:75`) |
| F17 | Public folders import `_cli` 15 times in 5 files (rev5, measured at `40c2a503`) | 6 are settings or surface reads (`app/adapters/cli.py:1212`, `:1274`, `:1303`; `surface_gate.py:74`, `:75`; `app/commands.py:340`), which this spec removes. 9 are delivery wiring (`cli.py:838`, `:953`, `:1255`, `:1360`, `:1621`; `app/adapters/tui.py:54`; `commands.py:356`; `click_params.py:92`, `:722`) — decision **M8** (`plan.md` §6) |

## 2. Users and stories

- A **project author** with a typo runs `func builtin config path` and is told
  which key is unknown and what was probably meant.
- An **agent** reads the same findings from `func builtin info --json`.
- A **user setting `shell.program`** writes it where the settings panel, help
  and docs say. The engine honours it there, the TUI shows the same value, and
  one environment variable overrides it.
- A **project with `root = true`** sees the same value for every setting in
  the CLI, the TUI and the engine.
- An **app author** (the `deploy_tool` example) declares their own settings
  through public API only, at app construction, with no import-order effects.

## 3. Behaviour

### 3.1 One declaration

- One declaration lists every key a functualize settings document may carry,
  with its canonical place, other accepted places, type (scalar, list, bool,
  int, enum, free-form `map` for `[aliases]`, `records` for
  `[[vault_secret]]`, `secret`), default, environment variable, CLI flag, and
  whether it is a settings row. It also holds the document frame: project
  and global file names, and the `pyproject.toml` prefix `tool.functualize`.
- An app extends the declaration with its own settings at construction. No
  process-wide registration exists.
- `tui.*` settings are declared statically and marked as belonging to the
  shell surface. They resolve on every path (closes STATUS #22) and are
  listed as rows only where the shell is.

### 3.2 One layer list

The files that participate in settings resolution are computed once:
upward walk, `root = true` stop, global file last. The same list feeds
resolution, the settings store, `config path` and `info`.

### 3.3 One resolver

Every read of a declared setting, whether by the CLI before boot, the app at
boot, the engine, the TUI or the builtins, comes from one resolution over
(CLI flags → app vault for `secret` settings → environment → layers →
declared default). The result is one frozen snapshot with provenance. The job
`ResolutionChain` never resolves a declared settings section.

### 3.4 Flags and environment from the declaration

- Every settings-backed root flag is generated from its setting's `cli_flag`.
  Parsed flags form the top resolution layer, keyed by the declared setting,
  not by string.
- The pre-boot scan reads the active declaration and passes what it found as
  data. Non-settings flags (`--log-level`, `--perf-*`, `--emit-format`,
  `--config-directory`) stay in `flag_grammar.py`, renamed per F13.
- Every setting has exactly one environment variable,
  `AppSettingsSchema.env_var_for`. Changes to user-visible names: §3.8.

### 3.5 The unknown-key check (approved v2: 1a + 2a + 3a)

- **Files:** every layer of §3.2 (whole document; `pyproject.toml` only
  `[tool.functualize]`).
- **Known:** declared in that place by the active declaration.
- **Checked:** non-table entries at the top level and inside declared
  sections; `map` sections, unknown tables and tables nested in sections are
  not checked.
- **Suggestion:** the best same-scope match at similarity ≥ 0.6.
- **Strictness (1a):** warn and continue. The check changes no exit code and
  never drops a key that would otherwise apply.
- **Surface (2a):** `config path` annotates each file line; `info --json`
  carries `config.unknown_keys` (`contracts.md` C1, C2). No startup warning.
  The global reader's separate warning is removed (M3); the global file is
  reported like every other file.

### 3.6 `config path`

- **Lists:** exactly the layers of §3.2, plus the expected locations that are
  not layers (missing anchor candidates, a `pyproject.toml` without
  `[tool.functualize]`, a missing global file). The order is ascending
  precedence, which is today's order: global first, nearest project file
  last (`contracts.md` C1).
- **Status:**
  - `✓ used`: the file supplies at least one value in effect (a winning
    value, or a contribution to a merged list).
  - `○ found`: the file exists and supplies none: it is empty, holds only
    unknown keys, or is wholly overridden.
  - `✗ missing`: the file does not exist.

  This is what `docs/cli/config.md` already promises, and the "Verification
  for a fix" clause of FOSS-127.
- **Annotations:** unknown keys, per §3.5.

### 3.7 Reserved section names (F14)

A discovered job or group whose canonical name equals a declared settings
section is reported through the existing discovery-failure channel. It
appears on `info --json` `discovery_failures` and on the CLI's existing
discovery-failure surfaces, naming the section and the source file. The job
still registers.

A job config file (`config.*.toml`, read by the job `ResolutionChain`) whose
top-level table is named like a declared settings section (`[shell]`,
`[plugins]`, …) is reported on the same channel. The finding names the file
and the settings document the table belongs in, so moving `[shell]` out of
`config.base.toml` (§3.8) is never silent.

### 3.8 User-visible changes (pre-release: no shims, no aliases — constitution)

| Change | Before | After |
|---|---|---|
| `[shell]`, `[plugins]` settings location | honoured only in `config.*.toml` job files (F3b) | honoured in the settings documents (`.functualize.toml`, `[tool.functualize]`, global `config.toml`) where they are declared, shown and documented; a `[shell]`/`[plugins]` table in a job config file is reported as a reserved-name table (§3.7) |
| `shell.*`, `plugins.strict` environment | `SHELL_PROGRAM`, `SHELL_SUDO_PASSWORD`, `PLUGINS_STRICT` | `FUNCTUALIZE_SHELL_PROGRAM`, `FUNCTUALIZE_SHELL_SUDO_PASSWORD`, `FUNCTUALIZE_PLUGINS_STRICT` (the documented `FUNCTUALIZE_SUDO_PASSWORD` was never read and goes from the docs) |
| list keys' environment (**M6 closed**) | `FUNCTUALIZE_EXTRA_DIRECTORIES` (top level, `docs/cli/config.md:148`) | `FUNCTUALIZE_DISCOVERY_EXTRA_DIRECTORIES`; `exclude_patterns` keeps `FUNCTUALIZE_DISCOVERY_EXCLUDE_PATTERNS` (`docs/cli/config.md:177`). Both keys stay accepted at the top level and under `[discovery]` in files; only the environment name has one form. A CI job exporting `FUNCTUALIZE_EXTRA_DIRECTORIES=/opt/jobs` is no longer read, and `CHANGELOG` `### Changed` names the replacement |
| PEP 723 `[tool.functualize] skill` (**M5 closed**) | accepted, read by nothing (STATUS #29) | rejected: the script gets the existing unknown-key warning (`_cli/pep723.py`); STATUS #29 closes as *removed, no consumer arrived*; `CHANGELOG` `### Changed` |
| `root = true` in settings | ignored by the TUI, the settings store, `cli.inline_tui` and the surface gate | honoured everywhere |
| `config path` | cwd-only list; `used` = exists | the resolution layers; `used`/`found` as §3.6 |
| global file warning | stderr on every run, for 5 sections | removed; reported by `config path`/`info` |
| app settings (`deploy_tool`) | `register_settings(...)` at import from `functualize._cli` | declared at app construction through `functualize.app.config` |

### 3.9 Must not change

- For a project whose settings live only in the current directory, and whose
  files hold only known keys, `config path` output is byte-identical (E5).
- Every setting's resolved value is unchanged, except where §3.8 says so.
  This is pinned against `bb3aac77` before the refactor (AC14).
- No exit code changes because of the check.
- `func <job>` does not import the check, and a warm `func <job>` stays inside
  `tests/perf/test_startup_budget.py`.

### 3.10 PEP 723 script metadata (M5 closed)

`[tool.functualize]` in a PEP 723 script is its own small document kind
(`SCRIPT_METADATA` in the declaration) with exactly one key, `job`. A script
that writes `skill` gets the warning `_cli/pep723.py` already prints for any
unknown key. Nothing else about script handling changes.

### 3.11 Delivery (M7 closed: (a))

- **PR 1** carries everything in this spec.
- **PR 2**, on this issue and branch line, decomposes `JobExecutionEngine`
  (`_engine/executor.py:205-2772`, 2568 lines) and `FunctualizeInlineTUI`
  (`_cli/tui/app.py:125-2828`, 2704 lines), together with the long functions
  in `plan.md` → *Surviving smells*. It starts only after PR 1 merges, and its
  own architecture pass (BEFORE/AFTER, smell check, plan, tasks) comes before
  any engine or TUI edit.
- Until then, both classes stay in *Surviving smells* as maintainer-accepted
  with a named owner (PR 2), not dropped.

## 4. Acceptance criteria

| # | Given / When | Then |
|---|---|---|
| AC1 | §1.1 file, `config path` | names `roots` → `root` and `definitely_not_a_setting`; exit 0 (re-run on `bb3aac77`: today prints `✓ used …/.functualize.toml` with no finding, exit 0) |
| AC2 | + `[cli] outptu` | names `cli.outptu` → `cli.output` |
| AC3 | `info --json` (+ `info all --json`) | `config.unknown_keys` lists the three with `file`, `key`, `suggestion` |
| AC4 | `[my-job]` table, no such job | no finding |
| AC5 | only known keys, incl. `[aliases]`, `[[vault_secret]]`, `[plugins] disabled`, `[discovery] jobs_directories` | `config path` output byte-identical to `bb3aac77`; `unknown_keys == []` |
| AC6 | `pyproject.toml` `[tool.functualize] roots` + `[tool.ruff]` | `roots` only |
| AC7 | global `roots = true`, `[cli] show_timng` | the global line names both; **no** stderr warning |
| AC8 | `[tui] them`, shell never imported | `tui.them` → `tui.theme` |
| AC9 | every config under `examples/`, `evals/`, `docs/` TOML blocks | 0 findings |
| AC10 | warm `func <job>` | check module not imported; startup budget green |
| AC11 | regression | the AC1 test fails on `e00d870` and passes at head |
| AC12 | ratchet | 0 collection literals of config key names outside the declaration (baseline at `bb3aac77`: 13 / 6 files) |
| AC13 | ratchet | 0 config-key string literals in read position outside the declaration and the settings resolver (baseline at `bb3aac77`: 91 / 9 files) |
| AC14 | pin | catalog order, defaults, choices, bounds, descriptions, flags and resolved values for a fixture matrix equal `bb3aac77`, except the rows §3.8 lists |
| AC15 | docs ratchet | every key in `docs/` TOML blocks and env tables is declared; every listed setting is documented |
| AC16 | F3a fixture (`root = true` + parent `output = "json"`) | CLI, settings store, TUI panel value and `info --json` all report `rich` |
| AC17 | F3b fixture (`[shell] program` in `.functualize.toml`) | the engine runs raw shell commands with that program; the TUI shows the same value; `FUNCTUALIZE_SHELL_PROGRAM` overrides both |
| AC18 | ratchet | no `ResolutionChain.resolve(<k>, <declared section>)` call; no settings-file TOML read outside the layer module |
| AC19 | `FUNCTUALIZE_TUI_DEFAULT_SURFACE=stdout`, direct `func <job>`, clean process | the surface gate opens (STATUS #22); `tests/adapters/` green when run alone |
| AC20 | ratchet | no module-level mutable registry in `_cli/data/`; `register_settings`, `_REGISTERED`, `_PREBOOT_OVERRIDES` absent from `src/` |
| AC21 | `deploy_tool` example | imports nothing from `functualize._` ; its tests green |
| AC22 | every settings-backed root flag | generated from the declaration; `rg` finds each flag string once in `src/` |
| AC23 | a job named `shell` | a discovery failure names the reserved section; the job still runs |
| AC24 | parent dir has `.functualize.toml`, cwd has `root = true` file | `config path` lists exactly the layers resolution uses; statuses per §3.6 |
| AC25 | `register_builtin_commands` | ≤ 60 lines; each builtin group in its own module; `func builtin --help` output byte-identical |
| AC26 | F11 fixtures | rewritten to the keys they mean; their tests green |
| AC27 | `config.base.toml` with `[shell] program = …` | a finding names the file and `.functualize.toml` `[shell]` as the place it belongs; exit 0 |
| AC28 (M6) | `FUNCTUALIZE_DISCOVERY_EXTRA_DIRECTORIES=/x` | `/x` is an extra directory; `FUNCTUALIZE_EXTRA_DIRECTORIES=/x` alone is not read; the pin's env-name table has exactly one name per setting |
| AC29 (M5) | a PEP 723 script with `[tool.functualize] skill = "s"` | the existing unknown-key warning names `skill`; `job` is still honoured; `ScriptMetadata` has no `skill` field |
| AC30 (F16) | the source tree | the surface values are stated only by `RenderSurface` in `_types/enums.py`; the `tui.default_surface` choices and the `surface_hint` validation derive from it; `functualize._cli.orchestrator` no longer exists |
| AC31 (F7, F17) | the source tree | no import of `functualize._cli.data`, `functualize._cli.config` or `functualize._cli.orchestrator` from any public folder; the 9 delivery imports of M8 are pinned, so their outcome is a visible edit |

## 5. Out of scope

From the shape (unchanged in v3): validating values (types, enum members);
unknown tables that could be job sections (3b); a `--json` flag on
`config path` (SD/2850883); unknown parameters inside a job section; a
startup warning (2b) and strict mode (1b/1c). Not this feature's question:
*where* the walk stops beyond `root = true` (bounding by a project root) is
SD/17104898 (MCH-188). After this feature it is one change, in the single
layer function.
