# config-unknown-keys — Specification

A key that is not a functualize setting is not accepted in silence.
`func builtin config path` names the keys it did not understand, so a typo in
`.functualize.toml` is visible where the user looks for configuration, and
`func builtin info --json` carries the same findings in a machine-readable
field.

Shape: *Shape Intent — Unknown Keys in .functualize.toml (what is checked, how
loudly, where)*, Confluence `SD/17137669` **v2**, `Authority = Approved`. The
maintainer resolved each of the page's three dimensions with an inline
comment reading "follow recommendation" (`18808859`, `18972740`, `18808867`).
This spec therefore builds the page's own recommendation, **1a + 2a + 3a**,
and no variant of it. See `plan.md` → `## Alignment`.

> **Revision 2 (2026-10-19) — proposed, not confirmed.** The maintainer asked
> (MCH-190 comment `01a153bd`) for one consistent single source of truth for
> the config vocabulary, with no duplication, after the pattern of the
> unified job namespace (SD/19595276). That is the change SD/17137669 v2 itself
> names as "a larger change than this ticket", so §3.7 and AC12–AC16 are
> **outside the approved shape until the page records them** (`plan.md` →
> decision M1). §1–§3.6 are unchanged, except §3.5's handling of the global
> file's warning, which now depends on decision M3.

## 1. Problem

Measured on `master` `d1c7e40a` (2026-10-17, `func` 0.4.0, isolated `HOME`):

```console
$ cat .functualize.toml
root = true
roots = true                       # typo for `root`
definitely_not_a_setting = 1

[cli]
outptu = "json"                    # typo for `output`

$ func builtin config path
  ✗ missing …/home/.config/functualize/config.toml
  ✗ missing …/pyproject.toml
  ✓ used    …/.functualize.toml    # none of the three unknown keys is named
$ echo $?
0
$ func builtin info --json | grep -c -i 'roots\|outptu\|definitely'
0
```

`config path` prints `✓ used` when `.functualize.toml` exists
(`src/functualize/_cli/builtins.py:2462-2467`); nothing on that path reads the
file's keys. `docs/cli/config.md:239` defines `✓ used` as "file exists and
contributed values" — the code decides it on existence alone.

### 1.1 What exists today (verified)

| Fact | Evidence |
|---|---|
| The **global** `config.toml` already warns on stderr, on every read, for an unknown key inside a recognized section, and drops it | `_cli/config.py:145-152` (`read_global_config`); measured: `Warning: …/config.toml: unrecognized key 'show_timng' in [cli], ignoring` |
| The same reader **silently drops** an unknown top-level key (`roots = true`) and every section outside `{discovery, cli, aliases, tui, vault}` | `_cli/config.py:126-133` |
| Project files (`.functualize.toml`, `pyproject.toml [tool.functualize]`) get **no** key check at all | `rg -n 'unrecognized key\|unknown key' src/functualize` → the only config-file key warnings are `_cli/config.py:150` (global file) and `_cli/pep723.py:159` (PEP 723 inline script metadata — a different file kind, out of scope) |
| The settings vocabulary lives in four places | `_cli/data/func_settings.py:180` `_BASE_SETTINGS`; `func_settings.py:164` `tui_settings()` (registered by the shell at `_cli/tui/__init__.py:86`); `_cli/config.py:26-67` `_RECOGNIZED_*`; keys read directly by `_config/` (`project_dirs.py:63` `LIST_KEYS`, `merge.py:36` `root`, `vault_declarations.py:42` `vault_secret`) and by `_cli/main.py:362` (`[plugins] disabled`) |
| `[aliases]` keys are user-chosen names, not settings | `_cli/config.py:136-139` |
| Top-level tables are job (and group) sections | `_config/sources.py:650-685` `_section_data` |
| `[shell]` and `[plugins] strict` are resolved through the same job-section chain | `_engine/executor.py:1932-1940`; `_app/boot.py:2078-2081` |
| `func builtin info --json` carries an always-present `config` object | `_cli/info.py:396-401` |
| No `difflib` in `src/` today; the secrets plugins already suggest the intended key with `difflib.get_close_matches(…, n=1, cutoff=0.6)` | `rg -c difflib src/` → exit 1; `plugins/credentials/functualize-secrets-aws/src/functualize_secrets_aws/_reference.py:124-127` |

### 1.2 Census (shape experiment E1)

The vocabulary in §3.2 was run over every functualize config in the
repository (`examples/`, `evals/`, `docs/` TOML blocks: 20 files and every
`toml` fence; `tests/`: 203 TOML string constants in 75 files).

- `examples/`, `evals/`, `docs/`: **0 findings.**
- `tests/`: every finding is either a deliberate unknown-key fixture
  (`tests/cli/test_cli_config.py:106,125,186`,
  `tests/cli/test_cli_config_vault.py:85`), a non-functualize TOML document
  (format-provider and locator tests), or a key functualize does not read where
  it is written: `scan_depth` at top level
  (`tests/_cli/test_runtime_detection.py:219`), `require_file_import` at top
  level (`tests/_cli/test_self_doctor.py:159`), `name`
  (`tests/spec/test_disabled_is_honoured_by_the_builtin_commands.py:121`),
  `extra` (`tests/cli/test_config_upward_walk.py:134`). Those are true
  positives: `scan_depth` is only read under `[discovery]`
  (`app/utils.py:739-751`). None of those tests asserts on `config path` or on
  `info --json`'s `config` block, and the check changes no exit code, so none
  changes outcome.

H1 holds: one vocabulary assembled from the named sources knows every key
functualize reads; the shape's "wrong if" condition did not fire.

## 2. Users and stories

- **A project author** who typed `roots = true` runs `func builtin config path`
  to see why the setting has no effect, and is told the key is unknown and
  that `root` was probably meant.
- **An agent** fetches `func builtin info --json` at the start of a session and
  reads the same findings from one field, without parsing prose.
- **Anyone running jobs** sees no change: no new stderr line, no new exit code,
  no extra work on the run path.

## 3. Behaviour

### 3.1 Files checked

The functualize-scoped table of each file `config path` reports, and of each
layer `info` reports:

- `.functualize.toml` (and `.functualize/.functualize.toml`) — the whole
  document;
- `pyproject.toml` — only `[tool.functualize]` (shape Risk 2); every other
  table belongs to other tools;
- the global `config.toml` — the whole document (shape: "The XDG global
  `config.toml` gets the same check").

### 3.2 What counts as an unknown key (dimension 3 → **3a, keys only**)

> "**3a. Keys only (recommended).** Scalars/arrays at top level and inside
> known sections. Tables are assumed to be job sections." — SD/17137669 v2

- A **key** is an entry whose value is not a TOML table (scalar, array, or
  array of tables).
- **Top level:** a key is known if it is a top-level setting of the catalog
  (`dotenv`, `dotenv_path`, `import_libs`) or a key functualize reads at the
  top level elsewhere (`root`, `jobs_directories`, `plugins_directories`,
  `extra_directories`, `exclude_patterns`, `vault_secret`).
- **Known setting section:** a table whose name is a section of the settings
  catalog — `cli`, `discovery`, `plugins`, `shell`, `vault`, `tui`, and any
  section a component has registered when the check runs. Inside it, a key is
  known if the catalog defines it there, or functualize reads it there
  elsewhere (`[discovery]`: the five list keys; `[plugins]`: `disabled`).
- `[aliases]` is free-form: its keys are never checked.
- Every other table — job sections, group sections, plugin-owned sections, an
  unregistered component's section — is **not** checked, and neither is a
  table nested inside a known section.
- `tui.*` keys are known whether or not the shell has been imported in this
  process (shape Risk 1).

### 3.3 The suggestion

When an unknown key is close to a known key **of the same scope** (same
section, or top level), the finding names it. Closeness is the plugins'
existing rule: the single best match at similarity ≥ 0.6. No close match → no
suggestion.

### 3.4 Strictness (dimension 1 → **1a, warn and continue**)

> "**1a. Warn and continue (recommended).** The run proceeds; the key is
> reported." — SD/17137669 v2

The check never changes an exit code, never stops a run, and never removes a
key from what is applied (the global reader's existing filter is unchanged).

### 3.5 Surface (dimension 2 → **2a, `config path` + `builtin info`**)

> "**2a.** `config path` **+** `builtin info` **(recommended).** `config path`
> annotates the file line (`✓ used …/.functualize.toml — unknown key "roots"
> (did you mean "root"?)`); `func builtin info --json` lists the finding in a
> machine-readable field." — SD/17137669 v2

- `func builtin config path` appends to the line of each file it prints one
  annotation per unknown key, in document order, joined by `; `:

  ```console
    ✓ used    …/.functualize.toml — unknown key "roots" (did you mean "root"?); unknown key "definitely_not_a_setting"; unknown key "cli.outptu" (did you mean "cli.output"?)
  ```

  A key inside a section is named by its dotted name (`cli.outptu`), the
  catalog's own naming. The status word (`✓ used` / `○ found` / `✗ missing`)
  and the set of files listed are unchanged.
- `func builtin info --json` (and `info all --json`) carries
  `config.unknown_keys`: always present, `[]` when there are none (the rule
  `discovery_failures` and `config` already follow). See `contracts.md`.
- No startup warning (2b) is added. The global reader's existing stderr
  warning (`_cli/config.py:150`) is the one place a key is reported outside
  2a. Revision 2 removes it as a separate vocabulary, so there is one
  checker. Whether that checker also writes to stderr for the global file is
  decision **M3** (recommended: no; the global file is reported like every
  other file, on `config path` and `info --json`).

### 3.6 Must not change

> "Behaviour that must **not** change: a file with only known keys produces
> exactly today's output; no run's exit code changes because of the check."
> — SD/17137669 v2

- `config path` output for files with only known keys is byte-identical.
- `info --json` differs only by the added `config.unknown_keys` key.
- `func <job>` runs do not import or execute the check.

### 3.7 One vocabulary (Revision 2 — pending M1)

There is exactly **one declaration** of what a functualize config document
may carry, and every reader, filter, check, environment mapping and file-name
list derives from it.

- **What the declaration holds:** every key functualize reads from a config
  document, with its canonical place (top level or a section), any other place
  it is accepted (the directory lists are accepted both at the top level and
  under `[discovery]`), its type (including a free-form map for `[aliases]`
  and an array of tables for `[[vault_secret]]`), whether it is shown as a
  settings row, and whether an environment variable sets it. It also holds the
  document frame that already sits on the same type: the project and global
  file names and the `pyproject.toml` prefix `tool.functualize`.
- **What "derives" means:** no module outside the declaration restates a set,
  tuple, list or dict of config key names, and no reader of a config document
  names a key by string literal; it names the declared setting.
- **What a user sees:** nothing beyond §3.1–§3.6. Today's settings rows, help
  text, environment variable names and resolution results are unchanged — the
  refactor is pinned by tests that record today's values first.
- **What keeps it single:** a source ratchet test fails when a collection of
  config key names, or a config-key string literal in a config-read position,
  appears outside the declaration — a ratchet in the sense of SD/19595276 E8:
  the baseline can only shrink.

Each maps to a shape experiment (E1–E5) or a ticket acceptance clause.

| # | Given | When | Then |
|---|---|---|---|
| AC1 (E2) | `.functualize.toml` = `root = true`, `roots = true`, `definitely_not_a_setting = 1` | `func builtin config path` | the `.functualize.toml` line names `roots` with suggestion `root`, and `definitely_not_a_setting` with none; exit 0 |
| AC2 (E2) | same, plus `[cli] outptu = "json"` | same | the line also names `cli.outptu` with suggestion `cli.output` |
| AC3 (E3) | AC2's file | `func builtin info --json` | `config.unknown_keys` lists the three findings with `file`, `key`, `suggestion`; exit 0 |
| AC4 (E4) | a file with a `[my-job]` table and no job named `my-job` | both commands | no finding |
| AC5 (E5) | a file with only known keys (incl. `[aliases]` entries, `[[vault_secret]]`, `[plugins] disabled`, `[discovery] jobs_directories`) | `config path` | output byte-identical to `d1c7e40a`; `config.unknown_keys == []` |
| AC6 | `pyproject.toml` with `[tool.functualize] roots = true` and `[tool.ruff] line-length = 88` | `config path` | names `roots`; nothing from `[tool.ruff]` |
| AC7 | global `config.toml` with `roots = true` and `[cli] show_timng = true` | `config path` | the global line names `roots` and `cli.show_timng` (suggestion `cli.show_timing`); stderr per decision M3 |
| AC8 | `[tui] them = "x"` with the shell **not** imported | check | finding `tui.them`, suggestion `tui.theme`; and `[tui] theme = "x"` → no finding |
| AC9 (E1) | every functualize config file under `examples/` and `evals/` | check | 0 findings |
| AC10 | `func <job>` | run | the check module is not imported |
| AC11 | ticket | regression test | the AC1 test fails on `e00d870` and passes at the fix head |
| AC12 (§3.7) | the source tree | ratchet: collection literals of ≥2 config key names outside the declaration module | **0** (baseline at `91947bb4`: 13 literals in 6 files) |
| AC13 (§3.7) | the source tree | ratchet: config-key literals in a read position (`.get("k")`, `["k"]`, `"k" in …`) outside the declaration | ≤ the recorded per-file baseline, which only shrinks (at `91947bb4`: 91 in 9 files; after this feature: only the flag-plumbing sites decision M2 leaves) |
| AC14 (§3.7) | today's catalog, `_RECOGNIZED_*` sets, env mapping, `LIST_KEYS`, `PROJECT_CONFIG_CANDIDATES` names, `cli.output` choices | pinned in a test **before** the refactor | every value equal after it |
| AC15 (§3.7) | every `toml` block and the env-var tables in `docs/cli/config.md` | docs ratchet | 0 keys the declaration does not know; every declared, listed setting documented |
| AC16 (§3.7) | `root`, `vault_secret`, `plugins`/`plugins.disabled`, `aliases`, and the five list keys | AC13's walk restricted to these names, **config-document reads only** (flag plumbing excluded per M2) | **0** outside the declaration (at `91947bb4` the unrestricted walk over these names reads 59 literals in 8 files: `_cli/main.py` 26, `app/utils.py` 14, `_cli/config.py` 12, `_cli/dispatch.py` 2, `_config/project_dirs.py` 2, `_app/boot.py` 1, `_cli/info.py` 1, `_config/vault_declarations.py` 1) |

## 5. Out of scope

From the shape's *Boundaries and non-goals*, verbatim in substance:

- validating **values** (types, enum members);
- unknown **tables** that could be job sections (3b);
- a `--json` flag on `config path` (owned by SD/2850883);
- unknown parameters inside a job section;
- a startup warning (2b) and a strict mode (1b/1c) — "available as follow-ups";
- which files `config path` lists, and how it walks for them — shared with
  SD/17104898 (MCH-188), not this feature;
- the `[tool.functualize]` table of a PEP 723 script (`_cli/pep723.py`,
  keys `job`, `skill`) — a different document kind with its own two-key
  vocabulary, stated once; not a duplicate;
- typing the CLI-flag plumbing dicts (`cli_flags`, `overrides`, `effective`)
  — decision M2.
