# Shape Intent: Standalone Distribution & Self-Management

**Status: specified, not yet implemented**
**Date: 2026-09-02** (consolidated 2026-07-16 from the Plan 008 family; revised 2026-07-18
after adversarial scrutiny; restructured 2026-08-27; **re-audited 2026-09-02 against HEAD
`39a0be2`**)

> **Provenance correction (2026-09-02).** The 2026-08-27 pass reported itself as audited
> "against HEAD `3503495`". That commit is **not an ancestor of this branch**:
> `git merge-base 3503495 HEAD` is `f12644c`, and seven PRs (#7, #8, #10, #12, #13, #14,
> #15 — 94 files, +6325/−1279 in `src/`) merged on the fork it missed. Every verdict below
> was re-checked on 2026-09-02 against real HEAD. **All 57 verdicts survived unchanged**;
> roughly twenty citations moved, two supporting rationales were falsified, and one new
> open decision (**O4**) was opened. **All four decisions O1–O4 were resolved 2026-09-03**;
> nothing now blocks any section. Working notes:
> `.spec/scrutiny-reports/standalone-distribution-2026-09-02.md`.
**Scope: `_cli/` delivery plus a release-time PyApp build pipeline. No kernel changes, no
new layer, no new public API. The daemon is explicitly out of scope.**

Make functualize installable and manageable without Python knowledge leaking into the UX:
detect how the running `func` was installed, expose that through `func builtin self`, and
let `func builtin plugin` install and remove plugin packages using the right tool for that
installation — plus a PyApp-built single binary for users who have no Python at all.

**Current state: none of this exists.** Re-verified 2026-09-02 against `39a0be2`:
`grep -rn "FUNCTUALIZE_RUNTIME\|install.json\|PYAPP\|InstallMode" src/ tests/ docs/` returns
**zero** hits — the single unrelated `_app/boot.py` comment the 2026-08-27 pass found is gone
too — and `git log --all -i --grep='pyapp' --grep='func self' --grep='standalone'` returns
only this document's own commits. None of `_cli/runtime.py`, `_cli/manifest.py`,
`_cli/self_cmd.py` or `_cli/plugin_cmd.py` exists.

---

## Core principle

**One installation has one owner, and every mutating command names that owner's tool.**
A `func` installed by uv is upgraded by uv; one installed by PyApp is upgraded by PyApp; a
consumer app built on functualize upgrades *itself*, not functualize. Where the owner
cannot be determined the command **refuses and explains** rather than guessing — a wrong
guess prints commands that do not exist and runs updaters against binaries they do not own.

Everything else in this document follows from that: the detection ladder establishes the
owner, the manifest remembers what was added to it, and the mode table maps owner → command.

---

## Audiences

Four, not three. The fourth exists whether or not it was designed for: `CliAdapter` mounts
the whole `builtin` subtree into a consumer application **by default** — the mount is guarded
by `if register_builtins:`, a constructor parameter defaulting to `True`
(`src/functualize/app/adapters/cli.py:761,771,806-812`). Both scaffold templates instantiate a
bare `CliAdapter()` and never opt out (`_cli/scaffold/templates/simple/main.py.j2:11`,
`.../full-interactivity/main.py.j2:20`), so a scaffolded app does get these commands — but
`self`/`plugin` must not *assume* the subtree is mounted, because a consumer can pass
`register_builtins=False`.

| Mode | Audience | Installation | Python env | Owning distribution |
|------|----------|-------------|------------|---------------------|
| **standalone** | Non-Python dev, ops | binary download, `brew install functualize` | PyApp-managed | `functualize` |
| **tool** | Python dev with uv/pipx | `uv tool install "functualize[cli]"` | uv/pipx isolated env | `functualize` |
| **project** | Framework user | `uv add "functualize[cli]"` | project `.venv/` | `functualize` |
| **embedded** | User of an app *built on* functualize | `uv tool install -e .` in a scaffolded project | that app's env | **the consumer app** |

Two degraded modes exist for honesty, not as targets: **tool (pip)** (no venv: bare pip,
system Python, conda) and **unknown** (an unrecognised venv — dev checkout, functualize as
a transitive dependency).

> **Terminology.** "Standalone" already means *single-file scripts run through `func`* in
> this repo (`examples/standalone/`, `tests/standalone/`, developer Mode **D** in
> `contributor/architecture/developer-modes.md`). The enum introduced here is
> `InstallMode`, never `Mode` — `_cli/dispatch.Mode` is a live enum whose members already
> include `UNKNOWN`.

---

## Decisions already pinned (do not re-litigate without new evidence)

| Decision | Rationale | Evidence |
|---|---|---|
| **PyApp** for the standalone binary | single binary, uv-powered, proven by Hatch shipping the same way. Nuitka is fragile with pydantic-core; PyInstaller has slow startup and AV false positives; Docker is poor CLI UX | not re-verified 2026-08-27; no live evidence against it |
| **`PYAPP_SELF_COMMAND=pyapp`** | see below — the decision survived, its original justification did not | PyApp CLI config docs |
| **`sys.prefix`, not `VIRTUAL_ENV`**, for uv/pipx detection | `VIRTUAL_ENV` is set by shell *activation*, not by executing a venv interpreter through a shebang — which is exactly how a uv-tool binary runs | re-verified on uv 0.11.18: a tool interpreter reports `sys.prefix` under `~/.local/share/uv/tools/<tool>` and `VIRTUAL_ENV: None` |
| **Receipt-merge** for tool (uv) plugin installs | `uv tool install` is declarative and drops prior `--with` entries | re-demonstrated on uv 0.11.18: a second install printed `- six==1.17.0` and rewrote the receipt. `uv tool --help` offers no `add`/`inject` to delegate to |
| **Explicit `unknown` mode**, never a standalone fallback | a dev checkout falling through to standalone gets bundled-uv commands that do not exist | 2026-07-18 scrutiny F5 |
| **Make `needs_terminal` path-aware; keep the names `install`/`uninstall`** (closes **O4**, decided 2026-09-03) | the flattened aggregate is the actual defect; renaming only dodges it until the next family ships an overlapping verb. Fixing the predicate makes cross-family collisions structurally impossible and frees the names that actually describe package management | see the prerequisite in §4.1 |

### The PyApp `self` collision — decision retained, rationale replaced

PyApp's management group is named **`self`** by default and PyApp intercepts
`<binary> self …` *before Python starts*. The 2026-07-18 revision pinned
`PYAPP_SELF_COMMAND=pyapp` to avoid that collision.

**That collision no longer exists.** Under [ADR-004](../../contributor/adr/004-cli-shell-convergence.md)
functualize's group is `func builtin self`, whose first token is `builtin` — PyApp never
sees a `self` it would claim. The blocking finding was resolved by a change made for
unrelated reasons.

**The pin stays, for a weaker reason.** Left at the default, `func self update` would be a
working command in standalone mode and a job-not-found error everywhere else — a phantom
that exists on exactly one install path. Renaming keeps the surface uniform and keeps
PyApp's updater reachable at `func pyapp update|remove|restore` (documented as internal).
Alternatives: `PYAPP_SELF_COMMAND=none` (loses the updater — rejected); leaving it at
`self` (the phantom above — rejected).

---

## Decisions — all resolved 2026-09-03

Nothing blocks any section. O1–O3 were the 2026-08-27 open set; O4 was opened and closed
during the 2026-09-03 re-audit.

| # | Question | Decision | Consequence |
|---|---|---|---|
| **O1** | PyApp build recipe | **B — pre-baked distribution, fully offline** | CI gains a distribution-baking step that does not exist today. First run needs no network at all; the ~3s figure becomes plausible. See §5.1 |
| **O2** | `PYAPP_PROJECT_FEATURES` | **`all` — batteries included** | Every first-party plugin ships in the binary. ~104 MB payload (measured below); nothing is ever installed at runtime for first-party features |
| **O3** | `self paths` / `self config-info` | **Fold; drop both commands** | `builtin self` holds only `doctor` and `update`. The three genuinely new lines go into `builtin info` and `info all`. See §3 |
| **O4** | Mutating plugin subcommand names | **Fix the predicate, keep `install`/`uninstall`** | Prerequisite **P1** in §4.1, listed under *Decisions already pinned* |

### O1 + O2 together — the size picture

Measured 2026-09-03 as uncompressed `site-packages` in a fully synced dev venv. **These are
inputs to the decision, not the CI assertion `PY.3` requires** — that must be a measured
binary size.

| Extra | Payload | Largest contributors |
|---|---|---|
| `cli` | ~19 MB | `textual` 6.1M, `pydantic_core` 4.9M, `pydantic` 3.0M, `rich` 2.4M, `jinja2` 1.2M, `click` 832K |
| **`all` (chosen)** | **~104 MB** | adds `litellm` 55M, `tokenizers` 11M, `openai` 8.5M, `pydantic_ai` 4.2M, `tiktoken` 3.4M, `fastmcp` 3.2M |

**~82 MB of the ~85 MB delta is `functualize-ai-pydantic` alone** (`pydantic-ai` +
`litellm`). Every other plugin is nearly free: `functualize-http`, `-lambda`,
`-state-sqlite` and `-tasks-local` declare no third-party dependency at all, while `-ai`,
`-state`, `-tasks` need only `pydantic` and `-flow-viz`, `-inline` only `textual` — all
four already in `cli`.

> **The rejected middle.** A curated `standalone` extra (everything except
> `functualize-ai-pydantic`) would have cost ~23 MB and delivered 10 of the 11 plugins. It
> was declined in favour of a binary that is genuinely complete on a machine with no
> network and no Python — which is the audience the binary exists for. Recorded because the
> ~5x size difference is the kind of thing a future reader will want the reasoning for.

**Out of scope: the daemon.** `.spec/STATUS.md` records that `persistent-process.md` and
`kernel-persistent-process-api.md` "no longer exist anywhere in the repo" and that the
daemon "has no spec … no unblocking event". The former `func self daemon *` subcommands are
**removed**, not carried as contingent lines. Do not re-derive them from this document.

**Superseded cross-references.** The former `remove-typer.md` and `shell-and-task-runner.md`
graduated to [ADR-004](../../contributor/adr/004-cli-shell-convergence.md) and
[ADR-005](../../contributor/adr/005-shell-and-task-runner.md) (both accepted 2026-07-24).
Typer is gone; author everything click-native. PEP 723 script dependencies ship today in
`_cli/pep723.py`.

---

## Implementation directive

**60 assertions, re-audited 2026-09-02 against HEAD `39a0be2`, decisions closed 2026-09-03:
7 PASS, 51 GAP, 2 RESOLVED-as-not-built.** (`RT.2`, `PY.6`, `PY.7` were added on 2026-09-03;
`SELF.3` and `SELF.4` became "this command is not built" when O3 resolved to fold.) Every
assertion below carries its verdict inline, with the `file:line` the verdict rests on. The
7 PASSes are pre-existing compliance — mechanisms that already exist and must be *used*,
not built (`SELF.2`, `PLG.3`, `PER.4`, `MOD.2`, `MOD.4`, `MOD.5`, `MOD.6`). Four of them
remove work the 2026-07-18 revision had scoped in.

Every citation below is pinned to `39a0be2`. `_plugins/`, `_config/registry.py`,
`_primitives/entry_points.py` and `_cli/completions/provenance.py` are **byte-identical
since `f12644c`**, so citations into them are exact and need no re-derivation;
`_cli/builtins.py` (1376 → **1801** lines) and `app/adapters/cli.py` moved the most.

**DO NOT immediately edit files.** Instead:

1. Read the current code for each assertion below.
2. Confirm each `PASS`/`GAP` verdict in the tables — they were re-audited on 2026-09-02
   against `39a0be2`, and the codebase has moved *twice* under this document already.
3. Present every GAP as a work item with the exact file, line range, and what would change.
4. Resolve **O1–O2** with a maintainer before starting §5. **O3** is a recommendation,
   not a blocker. **O4 is closed** — §4 now carries the path-aware-predicate prerequisite
   as its first task.
5. Assertions marked PASS need no edit — note them as pre-existing compliance.

---

## 1. Runtime mode detection

New module `_cli/runtime.py`: stdlib only, ~160 LOC. Exports `InstallMode` and a **pure**
`detect(prefix, base_prefix, environ, argv0)` — pure because `sys.prefix` cannot be
monkeypatched via environment, so an impure function is not unit-testable.

### 1.1 Environment kind (axis 1) — first match wins

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `RMD.1` | `FUNCTUALIZE_RUNTIME` set → that mode verbatim (CI/testing override) | **GAP** — name is free; no `FUNCTUALIZE_RUNTIME` anywhere in `src/`. Adjacent names in use are `FUNCTUALIZE_ENV` (config overlay), `_DOTENV`, `_IMPORT_LIBS`, `_TUI_*` |
| `RMD.2` | `PYAPP=1` or `PYAPP_COMMAND_NAME` set → `standalone` | **GAP** — signal confirmed against PyApp runtime docs ("a single environment variable called `PYAPP` is injected with the value of `1`") |
| `RMD.3` | `sys.prefix` under the uv tools dir (`uv tool dir`, default `$XDG_DATA_HOME/uv/tools`) → `tool_uv` | **GAP** — signal re-verified on uv 0.11.18 |
| `RMD.4` | `sys.prefix` contains `pipx/venvs` → `tool_pipx`; `PIPX_HOME` is **not** consulted (unset for default installs) | **GAP, signal UNVERIFIED** — no pipx on the 2026-08-27 scrutiny host. Settle it the way uv was settled: install a tool with pipx, read `sys.prefix` from its shim |
| `RMD.5` | A nearby `pyproject.toml` declaring functualize → `project` | **GAP** |
| `RMD.6` | `sys.prefix == sys.base_prefix` → `tool_pip`, degraded | **GAP** |
| `RMD.7` | Anything else → `unknown`, degraded. Never `standalone` | **GAP** |
| `RMD.8` | `detect()` is pure — takes prefix, base prefix, environ and argv0 as arguments and reads no globals | **GAP** |

> **`RMD.5` is on a hot path and must stay at rung 5.** It is a directory walk plus a TOML
> parse — `contributor/reference/pitfalls.md` #16's exact shape ("a syscall on the left of
> `and`", 17,249 stats per boot, 63% of boot time). It is safe **only** because rungs 1–4
> are pure env and string checks that answer first in every non-project case. Keep that
> ordering, bound the upward walk at the same anchor `resolve_cli_config` already uses, and
> never move a filesystem rung above a pure one.

### 1.2 Owning distribution (axis 2)

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `RMO.1` | Detection returns which distribution provides the running console script, derived from `sys.argv[0]`'s basename reverse-mapped through `importlib.metadata` | **GAP** |
| `RMO.2` | For `func`/`functualize` the owner is `functualize`; for a scaffolded app's script it is that app's distribution | **GAP** — both scaffold templates declare `[project.scripts]` as `{{ project_name }} = "{{ package_name }}.main:run"` (`_cli/scaffold/templates/simple/pyproject.toml.j2:11-12`, `.../full-interactivity/pyproject.toml.j2:14-15` — **not** `main.py.j2`, as the 2026-08-27 pass wrote), so the two are genuinely distinct |
| `RMO.3` | Every mutating command names the axis-2 distribution, never a hardcoded `functualize` | **GAP** |

### 1.3 Mode → behavior

`<dist>` is the axis-2 owning distribution.

| Behavior | standalone | tool (uv) | tool (pipx) | project | tool (pip) / unknown |
|-----------|-----------|-----------|-------------|---------|----------------------|
| `plugin install X` | bundled `uv pip install X` + record in manifest | receipt-merged `uv tool install <dist> --with <all prior> --with X` | `pipx inject <dist> X` | `uv add X` | print `pip install X`, exit `REFUSED` |
| `self update` | `func pyapp update`, then reconcile manifest plugins | `uv tool upgrade <dist>` | `pipx upgrade <dist>` | `uv lock --upgrade-package <dist> && uv sync` | refuse with guidance, exit `REFUSED` |
| Python ownership | functualize | uv | pipx | project venv | user |

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `RMB.1` | Every degraded-mode refusal exits `ExitCode.REFUSED` (3), printing guidance and executing nothing | **GAP** — `ExitCode` exists with exactly this member (`_types/exit_codes.py:42`), imported at `app/utils.py:51` and exported at `:112`. PR #13 additionally wired `RunStatus.REFUSED → ExitCode.REFUSED` into the status table (`_types/exit_codes.py:63`), so REFUSED is now reachable from job status as well as from a CLI refusal — the code is load-bearing, not decorative |
| `RMB.2` | Coexisting PyApp + uv-tool installs are both recorded in the manifest; PATH decides which runs | **GAP** |
| `RMB.3` | CI with no venv resolves to `tool_pip` and doctor reports it as such | **GAP** |

---

## 2. Install manifest and first run

New module `_cli/manifest.py`: stdlib + `json`, ~110 LOC.

```json
{
  "schema_version": 1,
  "installations": [{
    "binary_path": "/usr/local/bin/func",
    "runtime_mode": "standalone",
    "owning_distribution": "functualize",
    "python_version": "3.12.4",
    "functualize_version": "0.1.0",
    "plugins": ["functualize-state-sqlite"],
    "first_run_at": "2026-06-20T10:30:00Z"
  }]
}
```

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `MAN.1` | The manifest lives at `resolve_user_config_dir() / "install.json"` — never a hardcoded `~/.config` | **GAP** — no manifest exists. The helper it must use does: `resolve_user_config_dir()` at `app/utils.py:861`, exported at `:152`, respecting `XDG_CONFIG_HOME`, with **nine** existing call sites (`_cli/config.py:464,798`; `_cli/builtins.py:1127,1257,1315`; `_cli/main.py:668`; `_cli/data/func_settings.py:667`; `_cli/tui/config_target_discovery.py:113`; `app/utils.py:1147,1195`) |
| `MAN.2` | The manifest is append-only; installation records are never deleted | **GAP** |
| `MAN.3` | Records carry `owning_distribution` (axis 2), so an embedded-mode install is distinguishable from a functualize-owned one | **GAP** — new in the 2026-08-27 revision |
| `MAN.4` | Doctor flags entries whose `binary_path` no longer exists rather than trusting them | **GAP** |
| `FR.1` | On first run a hint is printed (`Run 'func builtin self doctor' for a health check.`) and nothing is blocked | **GAP** |
| `FR.2` | The hint fires on the first real invocation after PyApp's bootstrap completes | **GAP** — PyApp exposes no mid-bootstrap hook; its docs state "all subsequent invocations will only check if the installation directory exists and nothing else" |
| `FR.3` | The warm path costs one `stat()`; `functualize._cli.manifest` is **absent from `sys.modules`** after a warm second invocation | **GAP, and undefended by any existing gate** — `tests/perf/test_startup_budget.py:98,108,118,128` budgets only `FunctualizeApp.__init__` phases (`BUDGET_TOTAL_BOOT_MS = 500.0`), and those are skipped under coverage and xdist. **The guard moved**: `tests/perf/conftest.py` was deleted by PR #13 and its `pytest_collection_modifyitems` now lives at `tests/conftest.py:129-148`. The pre-boot CLI path still has no wall-clock budget at all, so this must be a *structural* assertion, not a timing one |

---

## 3. `func builtin self`

```
func builtin self doctor        # Health check (extensible by plugins)
func builtin self update        # Mode-aware update with confirmation
```

**Two commands, not four (O3 resolved 2026-09-03: fold).** `self paths` and
`self config-info` are **dropped**. The three genuinely new facts — install mode, owning
distribution, and the install manifest — are added to `builtin info` and to the `info all`
document, which already carries a `--format json` path (`_cli/builtins.py:1543-1799`).
`builtin config path` is unchanged and remains the one place that answers "where are my
config files".

### 3.1 Namespace — load-bearing

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `SELF.1` | The group is mounted as a child of `builtin`, spelled `func builtin self …`. There is **no** top-level `func self` | **GAP (and the single biggest correction in the 2026-08-27 revision)** — ADR-004 §Phase A.3 reserved `builtin` as the *one* top-level segment. `register_builtin_commands` states "There are **no top-level spellings and no deprecation aliases**" (`_cli/builtins.py:559,571`); `BUILTIN_NAMES == frozenset({BUILTIN_ROOT})` (`:174`); the trie rejects the name for jobs, groups and plugin namespaces (`_types/naming.py:417-421`, `_app/boot.py:1246-1254`, `_app/impl.py:269-276`); and `tests/_cli/test_builtin_command_pilot.py:356` asserts the top level holds exactly `BUILTIN_NAMES`. **A top-level `self` group fails that test.** |
| `SELF.2` | The depth `builtin` → `self` → subcommand is representable without registry changes | **PASS, re-verified 2026-09-02** — `BuiltinCommand.subcommands` is one level and `builtin_subcommands()` returns the two-level map (`_cli/builtins.py:191-201`) |
| `SELF.3` | `self paths` is **not built** | **RESOLVED (O3, fold)** — `builtin config path` already prints the XDG global path, `pyproject.toml [tool.functualize]` and `.functualize.toml` with used/found/missing status (`_cli/builtins.py:1252-1308`). Shipping a second path command is `pitfalls.md` #6. The assertion is now "this command does not exist" |
| `SELF.4` | `self config-info` is **not built**; install mode, owning distribution and the manifest are surfaced through `builtin info` and `info all` instead | **RESOLVED (O3, fold)** — `info` is a `click.group(invoke_without_command=True)` (`_cli/builtins.py:1543-1799`, registry rows `:134-145`) with `jobs`, `schema` and **`all`** ("everything info knows, as one document"), plus an `_emit_json` helper and a `resolve_renderer(json_out, cli_config) == "json"` branch. Bare `info` keeps printing the overview. **Work item: extend `info` and `info all` with three fields, and add them to the JSON payload — do not add a command** |
| `SELF.5` | Structured output for `self` uses a command-owned `--format json`, not `--json` and not the global `--output`. (Under O3 the *read-only* install facts ride `info`'s existing JSON path instead, so this now governs `self doctor` only) | **GAP** — `builtin workflow list` establishes command-owned `--format` as deliberately distinct from the global `--output {auto,json,ndjson,raw,none}` (`_cli/builtins.py:763,795`, `_cli/dispatch.py:88,100`) |
| `SELF.6` | In standalone mode `self update` re-execs `func pyapp update`, then reconciles manifest-recorded plugins | **GAP** |

### 3.2 Doctor architecture — rewritten 2026-08-27

The 2026-07-18 design placed doctor as an ordinary builtin. **It cannot work there.**
`cli_app`, the click group callback, runs `resolve_cli_config` → `_load_dotenv` →
`_apply_import_libs` → `auto_discover` → `FunctualizeApp(...)` → `app.refresh()` and only
then wires `ctx.obj` (`_cli/main.py:160-330`; the chain is at `:277,284,292,301,306,319`,
`ctx.obj` at `:325`). Every builtin subcommand runs after a full boot, so:

- **"core import + version", "config resolution chain", "execution smoke test"** had to
  succeed for doctor to be *reached*. They can only ever print OK — `pitfalls.md` #1's
  shape relocated into a health check, which is worse than a dead setting: a health check
  that cannot report ill.
- **"plugin loading" fails the other way.** `_load_file_plugin` catches `Exception`, logs a
  warning and returns `None` (`_plugins/loader.py:748,761-773` — this file is unchanged
  since `f12644c`, so the citation is exact), and **no failure record is kept** — no `failed_plugins`/`load_errors` attribute exists anywhere in `_plugins/` or
  `app/core.py`. Demonstrated 2026-08-27: a `.functualize/plugins/` module containing
  `raise RuntimeError(...)` leaves `func builtin version` at exit 0 with only a log line.
  A post-boot doctor would report "plugins: ok". That is `pitfalls.md` #2 reaching the
  diagnostic layer.

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `DOC.1` | `self doctor` is intercepted **pre-boot** in `_run_cli`, beside `--version` and `scan_early_setting_flags` | **GAP** — the escape hatch exists and is the repo's own idiom for commands that must answer before the app exists: `_run_cli` at `_cli/main.py:1694`, the position-aware `--version` scan at `:1707-1751`, `scan_early_setting_flags` at `:1758-1760` |
| `DOC.2` | Boot-shaped checks run in a **child process**, so a boot that dies is a reportable result rather than doctor's own traceback | **GAP** |
| `DOC.3` | Doctor reports a plugin that failed to load | **GAP, and currently unobtainable** — needs either a log handler around the child probe or a load-failure record added to `PluginLoader` in a separate change. Until one exists, **the plugin check is omitted, not faked** |
| `DOC.4` | Every check that can only be satisfied by the process doctor is already running in is **deleted**, not kept as decoration | **GAP** |
| `DOC.5` | Surviving checks: Python ≥ 3.11 (critical), CLI extras (warning), job discovery from CWD (info), child boot probe (critical), manifest-vs-installed plugin reconciliation in standalone mode (warning), stale `binary_path` entries (info), terminal capabilities (info), runtime mode + owning distribution (info) | **GAP** — the Python floor matches `requires-python = ">=3.11"` (`pyproject.toml:10`, exact) |

---

## 4. `func builtin plugin`

```
func builtin plugin list
func builtin plugin install <pkg>     # mode-aware; prints the exact command + y/N confirmation
func builtin plugin uninstall <pkg>
```

`install`/`uninstall` — the names that describe the operation. They are safe **only after**
the path-aware-predicate prerequisite lands; see the terminal-ownership note below and
`PLG.5`.

### 4.1 What counts as a plugin

The codebase reads **eight** distinct `functualize.*` entry-point groups, not one:

| Group | Read at |
|---|---|
| `functualize.plugins` | `_plugins/loader.py:326` |
| `functualize.domains` | `_plugins/domain_registry.py:156` |
| `functualize.ai_providers` / `state_providers` / `tasks_providers` | `_plugins/domain_registry.py:246` (per-domain) |
| `functualize.format_providers` | `_config/registry.py:169` |
| `functualize.remote_providers` | `_config/registry.py:193` |
| `functualize.interactivity_providers` | declared by `plugins/functualize-inline/pyproject.toml:24-25` |

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `PLG.1` | `plugin list` spans all eight groups and labels which group each entry came from | **GAP** — the document's own worked example proves why: **`functualize-inline` does not register in `functualize.plugins` at all.** A listing reading only `app.plugin_loader.loaded_plugins` (today the sole surface `_cli` uses — `_cli/completions/provenance.py:154`) would not show it |
| `PLG.2` | `plugin list` shows both the plugin name and the distribution name | **GAP** — `loaded_plugins` maps plugin name → entry-point name (`_plugins/loader.py:251-256`), e.g. `inline`; `uninstall` needs `functualize-inline`. The mapping does not exist and must be built via `importlib.metadata` |
| `PLG.3` | `plugin list` needs no new public API | **PASS** — `_cli` already reads `app.plugin_loader.loaded_plugins` by attribute access (`_cli/completions/provenance.py:154`), which the import-linter contract permits. **If a public listing API is added instead, an ADR is mandatory** (`AGENTS.md` → Mandatory reading: "Proposing a new … public API surface") |
| `PLG.4` | Every mutating command prints the exact command it will run and asks for confirmation before any side effect | **GAP** |
| `PLG.5` | Declaring the mutating subcommands terminal introduces no cross-family false positive, because `needs_terminal` resolves the family before matching | **GAP — now a prerequisite, not a naming constraint (O4 closed 2026-09-03).** The 2026-07-18 answer (pick non-colliding names) was falsified by `skills install`; the decision is to fix the predicate instead. See the note below |
| `PLG.6` | `plugin install` is not followed by an in-process plugin read in the same invocation | **GAP** — see `PLG.8` |
| `PLG.7` | Mutating subcommands are declared in `BuiltinCommand.terminal_subcommands` so the inline TUI hands off instead of capturing | **GAP, gated on P1** — the mechanism exists and is the repo idiom: `_builtin_needs_terminal` (`app/commands.py:306-316`, exact) collapses the family predicate per node, and `_cli/tui/job_execution.py:425-427` routes through `_node_needs_terminal` to `_run_builtin_handoff` (defined `:459`) — the same path `builtin config edit` takes. **Declare `install`/`uninstall` terminal only after P1 lands**, or the flattened root predicate reports a false positive for `skills install` |
| `PLG.8` | The entry-point snapshot invariant is honored or corrected | **GAP** — `_primitives/entry_points.py` documents its process-wide snapshot as "deliberately never invalidated on its own: … **nothing functualize does installs a distribution into the running interpreter.**" In standalone mode `plugin install` runs `uv pip install` into the PyApp-managed venv, which *is* the running interpreter's environment, making that sentence false. `clear_entry_point_cache()` exists but lives in `_primitives`, which `_cli` may not import — so either the command exits after printing (recommended) or the docstring is corrected and a public re-export added under an ADR |

> **Prerequisite P1 — make `needs_terminal` path-aware.** *(Closes O4, decided 2026-09-03.
> Supersedes the 2026-07-18 "pick non-colliding names" answer.)*
>
> **The defect.** `BUILTIN_ROOT_COMMAND.terminal_subcommands` is a **flattened** tuple across
> all families (`_cli/builtins.py:167-170`) and `needs_terminal` matches without knowing which
> family an argument belongs to (`:47-48`):
>
> ```python
> def needs_terminal(self, args: list[str]) -> bool:
>     return any(arg in self.terminal_subcommands for arg in args)
> ```
>
> So any name declared terminal by *one* family matches in *every* family. The 2026-07-18
> revision worked around this by choosing names no other family used; `skills install`
> (PR #14, `:99-107`) removed the last such pair, and the next family to ship an overlapping
> verb would remove the next one. **The workaround does not converge — the predicate is fixed
> instead.**
>
> **The fix.** Resolve the family before matching. `get_builtin` already answers for both the
> root and each family (`:219-229`), so the lookup needs no new state:
>
> ```python
> # sketch, not a specification — the spec phase picks the shape
> def needs_terminal(self, args: list[str]) -> bool:
>     if self.name == BUILTIN_ROOT and args:
>         child = get_builtin(args[0])
>         if child is not None:
>             return child.needs_terminal(list(args[1:]))
>     return any(arg in self.terminal_subcommands for arg in args)
> ```
>
> Three shapes are viable and the spec phase must choose one: (a) the branch above, which
> couples the dataclass to same-module registry state; (b) a `RootBuiltinCommand` subclass
> overriding the method; (c) give the root real child references instead of `(name,
> description)` pairs. (c) is the cleanest typing and the largest diff.
>
> **Constraints the fix must satisfy — all four are already asserted by existing tests:**
>
> | Must keep holding | Pinned at |
> |---|---|
> | `root.needs_terminal(["config", "edit"]) is True` | `tests/_cli/test_builtin_handoff.py:100` |
> | `_node_needs_terminal(app, [BUILTIN_ROOT, "config", "edit"])` is True, and the negative case stays False | `tests/_cli/test_builtin_handoff.py:109-110` |
> | Family-scoped single-segment calls keep their meaning: `leaf.needs_terminal == source.needs_terminal([leaf.name])` | `tests/core/test_click_command_provider.py:94` |
> | The root **node** is not itself terminal: `_root(app).needs_terminal is False` | `tests/core/test_click_command_provider.py:97` |
>
> **And one documented decision it must not break.** `_types/commands.py:52-70` records that
> `CommandNode.needs_terminal` is a plain bool *because* `BuiltinCommand.needs_terminal` is a
> predicate over args, with the tree calling `needs_terminal([segment])` per child (`:65`).
> `tests/core/test_command_node_protocol.py:100-108` asserts the bool-not-callable half. P1
> changes how the **root** answers; it must leave the per-family predicate and the node
> contract exactly as they are.
>
> **Scope.** P1 touches `_cli/builtins.py` only, is independently testable, and lands as §4's
> first task — before any `plugin` command is declared terminal. It is a shared-registry
> change this feature now carries, which the 2026-08-27 revision had scoped out.
>
> **What P1 does *not* fix — see the note below.**

> **Adjacent defect found 2026-09-03 — `skills install` is mis-declared. Not fixed by P1.**
>
> **The direct-CLI path is correct and must not be changed.** `skills_install` runs
> `subprocess.call(["npx", "skills", "add", …])` with no stdio kwargs, so the child inherits
> fd 0/1/2 and gets the real TTY. `npx skills add` is interactive (confirmed by the
> maintainer, 2026-09-03) and works today from a terminal. **`subprocess.call` is the right
> primitive here — do not replace it, and do not capture its output.**
>
> **The defect is the TUI path only.** The `skills` family declares no
> `terminal_subcommands` — `config` is still the only family that declares any (verified:
> `get_builtin('skills').needs_terminal(['install'])` is `False`). So from the inline shell
> the command takes the worker route, where output is captured with
> `contextlib.redirect_stdout(io.StringIO())` (`_cli/tui/job_execution.py:333,339`). That
> rebinds Python-level `sys.stdout` only; the child still inherits fd 1, so `npx` prompts
> onto the real terminal underneath the running TUI.
>
> **The fix is the declaration, not the call.** With `terminal_subcommands=("install",)` on
> the `skills` registry entry, `_node_needs_terminal` routes to `_run_builtin_handoff` →
> `app.request_handoff(tokens)` → `App.exit()`, and the orchestrator re-runs the command on
> the direct stdout surface — the same EXCLUSIVE route a `tty: TTY` job and a `!` shell
> command take, and the route `config edit` already takes. `subprocess.call` then has the
> real terminal and behaves exactly as it does from the CLI.
>
> **Why not the `Shell` capability.** It exists, and `pty=True` plus `watchers`/`Responder`
> looks like a fit, but (a) it is job-scoped DI — `_make_shell(ctx)` needs `ctx.engine` and
> `ctx.context`, and a builtin is a click callback with no RunContext; (b) `_cli` may import
> the public `functualize.job.Shell` protocol but **not** the wiring in
> `_engine/capabilities/shell.py`; and (c) a pty proxy is for streaming into a surface and
> answering prompts programmatically, not for handing a human the terminal. Handoff is the
> construct for that, and it already exists.
>
> **Relation to P1.** P1 makes this *more* visible, not less: with a path-aware predicate,
> `root.needs_terminal(["skills", "install"])` delegates to the `skills` family, which
> declares nothing, and correctly returns False — leaving the missing declaration as the only
> remaining bug.
>
> **Out of scope here.** File separately: one line on the `skills` entry plus a TUI Pilot test
> asserting handoff rather than worker execution.
>
> **Root cause, and a separate intent.** This defect and P1 share one root: terminal
> ownership for a builtin is declared on a *registry row, by family, as a string*, so it can
> be forgotten (this bug) or collide (P1). For a job the same fact is declared *on the
> function, by signature*, and can do neither. That observation is written up as
> [builtins-as-jobs.md](builtins-as-jobs.md) — **undecided**, and deliberately independent:
> P1 is needed regardless, because `version`, `config` and `cache` are never converting.

### 4.2 Plugin persistence — load-bearing

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `PER.1` | In tool (uv) mode, `plugin install`/`uninstall` read `uv-receipt.toml` from the tool dir and re-emit **all** prior requirements plus/minus the change | **GAP, requirement re-confirmed** — on uv 0.11.18, `uv tool install pycowsay --with six` then `uv tool install pycowsay --with idna` printed `- six==1.17.0` and rewrote the receipt to drop it. `uv tool --help` lists no `add`/`inject`, so this cannot be delegated |
| `PER.2` | The merge reconstructs a PEP 508 requirement from **every** key present, not just `name`, and round-trips unknown keys rather than dropping them | **GAP** — observed shapes: `{ name = "pycowsay" }`, `{ name = "idna", specifier = ">=3.0" }`, `{ name = "a0", url = "https://…zip" }`. The previous revision spoke of "`--with` entries" as if they were plain names |
| `PER.3` | In standalone mode the manifest records added plugins, and `self update` (plus doctor runs) reinstalls missing recorded ones via bundled uv, with confirmation | **GAP** — PyApp update/restore rebuilds the managed venv from the project requirement only, wiping `uv pip install`ed plugins |
| `PER.4` | `uv tool upgrade` is left to preserve receipt-recorded settings — no special handling once the receipt is correct | **PASS (upstream behavior)** |

---

## 5. PyApp build and distribution

**Unblocked 2026-09-03: O1 = recipe B (pre-baked, offline), O2 = `all`.** The section
below is written to those answers.

### 5.1 The embedding claim was falsified

The 2026-07-18 revision stated that building with `PYAPP_DISTRIBUTION_EMBED` and an
embedded project wheel makes "first run offline-capable and the ~3s bootstrap figure hold".
**PyApp does not work that way.** Its runtime documentation lists first-run network
requirements as: retrieving the distribution, **downloading uv or pip if not cached**, and
**installing project dependencies**. `PYAPP_DISTRIBUTION_EMBED` removes only the first.

Concretely, `functualize[cli]` pulls `pydantic`, `python-dotenv`, `jinja2`, `click`,
`rich`, `textual`, `textual[syntax]` and `textual-autocomplete`
(`pyproject.toml:23-25,68-73`) — every one fetched from PyPI at first run. And
`PYAPP_UV_ENABLED=1` means uv performs "virtual environment creation and project
installation", i.e. uv is needed *during* bootstrap, not (as previously written) "on first
plugin/PEP 723 use". The two chosen settings are not jointly offline-capable.

| | **A** — network first run | **B — CHOSEN** |
|---|---|---|
| Build | `PYAPP_DISTRIBUTION_EMBED=1` + `PYAPP_PROJECT_PATH=<wheel>` | a python-build-standalone distribution with functualize **already installed**, embedded, plus `PYAPP_SKIP_INSTALL=1` |
| First run | needs network for uv + dependencies | **fully offline** |
| Size | smaller binary; latency is a network lottery | larger binary; ~3s figure plausible |
| Effort | ships today | **needs a distribution-baking CI step that does not exist** |

Recipe B is the shape Hatch ships and is what the withdrawn "offline-capable, ~3s" numbers
were implicitly describing. **Chosen 2026-09-03.** The size half of that withdrawn figure
does *not* come back: with O2 = `all` the payload is ~104 MB uncompressed, so 35–50 MB was
never the right target for this configuration. `PY.3` still requires CI to assert a
**measured** binary size rather than any estimate in this document.

The cost is explicit: **a distribution-baking CI step is new work with no prior art in this
repo.** It must produce, per platform, a python-build-standalone tarball with
`functualize[all]` already installed, and that artifact — not the wheel — is what
`PYAPP_DISTRIBUTION_PATH` embeds.

### 5.2 Build configuration

The previous revision named three variables. The minimum viable set:

| Variable | Value | Note |
|---|---|---|
| `PYAPP_PROJECT_NAME` | `functualize` | required |
| `PYAPP_PROJECT_VERSION` | release version | required |
| `PYAPP_PROJECT_PATH` | path to the built wheel | **the option that actually embeds the project** — previously unnamed |
| `PYAPP_PROJECT_FEATURES` | **`all`** | O2, resolved 2026-09-03. ~104 MB payload; see the size table under *Decisions* |
| `PYAPP_EXEC_SPEC` | `functualize._cli.main:main` | matches `[project.scripts]` (`pyproject.toml:33-35`) — previously unspecified |
| `PYAPP_SELF_COMMAND` | `pyapp` | see the collision section |
| `PYAPP_UV_ENABLED` | `1` | uv for venv creation, installs, PEP 723 |
| `PYAPP_DISTRIBUTION_EMBED` | `1` | O1 recipe B — embeds the **baked** distribution, not a bare interpreter |
| `PYAPP_DISTRIBUTION_PATH` | the baked tarball | **new, and the whole point of recipe B**: a python-build-standalone distribution with `functualize[all]` pre-installed |
| `PYAPP_SKIP_INSTALL` | `1` | O1 recipe B — nothing is installed at first run, so nothing needs the network |

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `PY.1` | Release-tag CI builds x86_64/aarch64 × linux/macos binaries | **GAP** |
| `PY.2` | The build sets every variable in the table above, none defaulted implicitly | **GAP** |
| `PY.6` | A distribution-baking CI step produces, per platform, a python-build-standalone tarball with `functualize[all]` pre-installed, and that artifact is what `PYAPP_DISTRIBUTION_PATH` embeds | **GAP, new work with no prior art here** — O1 recipe B's entire cost. `.github/workflows/release.yml` today builds a wheel and publishes it (`build` → `publish` → `github-release`); it bakes nothing |
| `PY.7` | The binary launches with the network disabled — the claim recipe B was chosen for is **tested**, not assumed | **GAP** — an offline smoke test in CI (no network namespace / blocked egress) running `func builtin version` and one real job |
| `PY.3` | CI asserts the actual binary size on release builds — a **measured** number, not an estimate quoted here | **GAP** |
| `PY.4` | Distribution: GitHub Releases + `install.sh` + Homebrew formula | **GAP** |
| `PY.5` | The README install section gains a standalone row | **GAP, now unblocked** — O1 is answered, so the instructions are writable: download, `chmod +x`, run. No Python prerequisite and no network caveat, which is recipe B's selling point. Insert alongside the existing uv/pip rows (`README.md:46-71`) |

---

## 6. Module layout and mounting

| Module | LOC est. | Layer / dependencies |
|--------|----------|----------------------|
| `_cli/runtime.py` | ~160 | stdlib only. Docstring declares "stdlib + `_cli` siblings only", matching `_cli/data/func_settings.py:31` |
| `_cli/manifest.py` | ~110 | stdlib + `json`; path via `resolve_user_config_dir()` (a public import — allowed) |
| `_cli/self_cmd.py` | ~200 | public API only. Exports `self_app: click.Group` |
| `_cli/plugin_cmd.py` | ~220 | public API + `subprocess` + `importlib.metadata`. Exports `plugin_app: click.Group`. Raised from 180: eight entry-point groups and the name→distribution mapping were not in the original estimate |

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `MOD.1` | `_cli/builtins.py` is **not** converted to a package | **GAP (scope reduction), and the argument got stronger** — the 2026-07-18 revision called it a "724-line module" whose commands would "move unchanged" into `_cli/builtins/`; the 2026-08-27 pass measured 1376. At `39a0be2` it is **1801 lines**, and `register_builtin_commands` spans `:556-1801` — one **1246-line** function containing **103** nested `def`/decorator sites, all closures over local groups. Moving them is a refactor, not a move |
| `MOD.2` | `self_app`/`plugin_app` are defined in sibling `_cli` modules and mounted in two lines each | **PASS, and no longer a single-precedent idiom** — `scaffold` does exactly this (`_cli/builtins.py:1526`), and PR #14 added a **second** instance, `skills` (`:1521`). The 2026-08-27 report flagged this as "an anecdote promoted to idiom"; with two consistent instances that flag lifts |
| `MOD.3` | Two `BuiltinCommand` entries are appended to `BUILTIN_COMMANDS`; no other registry surface changes | **GAP** |
| `MOD.4` | No cache-format bump is required | **PASS** — follows from MOD.1/MOD.2; nothing serialized changes |
| `MOD.5` | The registry-mirror test covers the new commands without being edited | **PASS, re-verified 2026-09-02** — `test_registry_matches_the_real_click_commands` derives its expectations from `BUILTIN_COMMANDS` and walks both levels (`tests/_cli/test_builtin_command_pilot.py:332-373`, exact). This corrects the 2026-07-18 claim that the test "is extended to cover them". Note its docstring still says "eight children" while the registry now holds 14 — stale, pre-existing, unrelated to this feature |
| `MOD.6` | No module-size rule is violated | **PASS, re-verified 2026-09-02** — there is **no ~250-LOC module ceiling** in this repo; the only limits are a ~500-LOC *class* ceiling (`.spec/CONSTITUTION.md:90`) and two named facades (RunContext ≤500, FunctualizeApp ≤300 — `:171-172`). `builtins.py` is now 1801 lines and `main.py` 1973 |
| `MOD.7` | New modules import public folders only | **GAP (contract already enforces it)** — `pyproject.toml` contract "_cli uses public API only"; `_cli/__init__.py` docstring |

### Routing

`func builtin …` is classified `Mode.BUILTIN` in `detect_mode` and dispatched through the
click group (`_cli/dispatch.py:249-257`, exact) — **not** through `_dispatch_group`
(`_cli/main.py:905`; `:774` in the 2026-07-18 revision, `:881` in the 2026-08-27 one),
which handles job groups. That branch carries a
live `# TRANSITIONAL(cli-shell-convergence §2.B.1)` marker noting that the planned fold of
`builtin` into the trie is "deferred and unscheduled".

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `RT.1` | This work does not depend on the `builtin`-into-trie fold, and does not silently complete it | **GAP** — if any transitional state is introduced, it carries its own `# TRANSITIONAL(<step>): …` marker per `.spec/CONSTITUTION.md` |
| `RT.2` | **P1** changes only how the *root* `BuiltinCommand` answers `needs_terminal`; the per-family predicate and the `CommandNode` bool contract (`_types/commands.py:52-70`) are untouched | **GAP, new 2026-09-03** — P1 is a shared-registry change, so it must not become a silent widening of the node protocol |

---

## Cross-cutting invariants

| Invariant | Description |
|---|---|
| `X.1` | Exactly one name is reserved at top level, and it is `builtin`. This feature adds no top-level name and no deprecation alias |
| `X.2` | Every mutating command names the axis-2 owning distribution. A hardcoded `functualize` anywhere in a generated command string is a defect |
| `X.3` | A command that cannot determine its owner refuses with `ExitCode.REFUSED` and prints guidance. It never guesses, and never executes a partial action |
| `X.4` | No check reports health it did not observe. A check whose only possible outcome is OK is deleted, not shipped |
| `X.5` | The pre-boot path gains at most one `stat()`. No new module is imported on a warm invocation that does not need it |
| `X.6` | Detection logic lives in exactly one place (`_cli/runtime.py`) and is a pure function. No surface re-derives the mode |
| `X.7` | Every command reachable from the CLI is reachable from the inline TUI and from a consumer app's CLI, and behaves correctly in all three |

---

## Verification checklist for the implementing agent

Audit each assertion against the current codebase before writing code:

- `RMD.1–8`, `RMO.1–3`, `RMB.1–3`: new `src/functualize/_cli/runtime.py`; compare against
  `src/functualize/_cli/config.py` (`resolve_cli_config`, the anchor walk) and
  `src/functualize/_types/exit_codes.py`
- `MAN.1–4`, `FR.1–3`: new `src/functualize/_cli/manifest.py`;
  `src/functualize/app/utils.py:861` (`resolve_user_config_dir`, exported `:152`);
  `src/functualize/_cli/main.py:1694-1760` (`_run_cli` pre-boot region);
  `tests/conftest.py:129-148` (the perf-budget skip guard, moved from the now-deleted
  `tests/perf/conftest.py`)
- `SELF.1–6`: `src/functualize/_cli/builtins.py:22-230` (registry), `:1252-1308`
  (`config path`), `:1543-1799` (`info` — now a **group**, registry rows `:134-145`),
  `:763,795` (`--format` precedent);
  `src/functualize/_types/naming.py:175,417-421`
- `DOC.1–5`: `src/functualize/_cli/main.py:160-330` (the boot-before-builtin problem) and
  `:1694-1760` (the pre-boot escape hatch); `src/functualize/_plugins/loader.py:748,761-773`
- `PLG.1–8` (**every citation in this group is exact — these files are byte-identical
  since `f12644c`**): `src/functualize/_plugins/loader.py:249-256,326`;
  `src/functualize/_plugins/domain_registry.py:156,246`;
  `src/functualize/_config/registry.py:169,193`;
  `src/functualize/_cli/completions/provenance.py:151-154`;
  `src/functualize/_primitives/entry_points.py`;
  `src/functualize/app/commands.py:306-316`;
  `src/functualize/_cli/tui/job_execution.py:425-427,459`
- `PER.1–4`: no repo code — verify against a real `uv-receipt.toml` under `uv tool dir`
- `PY.1–5`: `.github/workflows/`, `README.md`
- `MOD.1–7`, `RT.1`: `src/functualize/_cli/builtins.py:556-1801`;
  `src/functualize/_cli/dispatch.py:249-257`;
  `tests/_cli/test_builtin_command_pilot.py:332-373`; `pyproject.toml` import-linter contracts

**Report format**: for each assertion, state `PASS` (code already satisfies, no change) or
`GAP` (with exact `file:line` and proposed change). Group GAPs by file. Wait for approval
before editing.

---

## Test tiers

Per `.spec/TESTING.md`.

| # | Criterion | Tier |
|---|---|---|
| T1 | `detect()` returns the exact `InstallMode` for each synthetic `(prefix, base_prefix, environ, argv0)` — asserting the right answer, never `!= wrong` (`pitfalls.md` #15) | unit |
| T2 | Axis 2 returns the consumer distribution for a scaffolded app's console script | unit |
| T3 | Receipt merge round-trips every observed key shape (`name`, `name+specifier`, `name+url`) and preserves unknown keys | property (`_properties.py`) |
| T4 | `func builtin self doctor` on a project whose `.functualize/plugins/` module raises **reports the failure** | CLI integration (`cli_run` + `project_tree`) |
| T5 | `func builtin self doctor` still produces a report when the app cannot boot | CLI integration |
| T6 | `func builtin plugin install X` in `unknown` mode prints guidance, executes nothing, exits `ExitCode.REFUSED` | CLI integration |
| T7 | `func builtin plugin list` shows an `interactivity_providers` entry with both its plugin name and its distribution name | CLI integration |
| T8 | Manifest written under `xdg_dirs.functualize_config`; hint printed on the first invocation only | CLI integration |
| T9 | `functualize._cli.manifest` absent from `sys.modules` after a warm second invocation | CLI integration (structural stand-in for the absent pre-boot budget) |
| T10 | `builtin plugin install` requests a terminal handoff from the inline TUI rather than running on the worker | TUI Pilot |
| T12 | **P1**: `root.needs_terminal(["skills", "install"])` is **False** while `root.needs_terminal(["plugin", "install"])` is **True** — the same word, resolved per family. Assert the right answer, not `!= wrong` (`pitfalls.md` #15) | unit |
| T13 | **P1** regression: the four constraints in §4.1's table still hold — run the existing `tests/_cli/test_builtin_handoff.py` and `tests/core/test_click_command_provider.py` unchanged | existing suites, no new test |
| T11 | Registry mirrors the real click tree | already covered — no new test (`MOD.5`) |

> `tests/conftest.py:170-187` (`_isolate_home`) strips `FUNCTUALIZE_*` and `XDG_*` autouse, so every test
> above must pass `FUNCTUALIZE_RUNTIME` explicitly via `cli_run(env=…)`. `sys.prefix`
> cannot be set by environment at all — which is why `RMD.8` requires `detect()` to be pure.
> Per `.spec/CONSTITUTION.md` → *Acceptance Gates*, run each criterion at authoring time and
> make each task's file scope equal its actual hit set.

### Wiring paths to name at close

Per `contributor/guides/wiring-discipline.md` §2 and §5, name every production path — cold
**and** warm — and sabotage the wire:

- **cold** — `_run_cli` → `detect_mode` → `Mode.BUILTIN` → `cli_app` → `builtin` group →
  `self`/`plugin`
- **warm** — the same route over a populated `cache.json`
- **pre-boot** — `_run_cli`'s `--version`-adjacent interception for `self doctor` and the
  first-run hint
- **TUI** — `job_execution.run_builtin` → `_node_needs_terminal` → `_run_builtin_handoff`
- **P1** — `app/commands.build_command_tree` → `_builtin_needs_terminal(family, segment)` →
  `BuiltinCommand.needs_terminal`. Sabotage by reverting the root branch to the flat `any(...)`
  and confirm T12 fails
- **consumer app** — `CliAdapter.__call__` → `if register_builtins:` →
  `register_builtin_commands` (`app/adapters/cli.py:806-812`). Also name the
  `register_builtins=False` path: the subtree is absent and nothing must crash

Commit first, then sabotage the `_mount(builtin_app, self_app, "self")` call and confirm a
test fails (`.spec/CONSTITUTION.md` → *Commit before sabotaging*).

### Documentation to update at close

`contributor/reference/code-map.md:176-184` and
`contributor/architecture/codemaps/modules.md:102-104` both enumerate `_cli/` modules, and
neither would fail `tests/test_contributor_docs.py` if left stale — that suite only checks
that referenced paths *exist*. Update both by hand.

---

## Scrutiny vs current codebase

Working notes: `.spec/scrutiny-reports/standalone-distribution-2026-09-02.md` (the current
delta re-audit) and `standalone-distribution-2026-08-27.md` (the earlier pass — note it
scrutinized this document's *predecessor*, `contributor/proposals/not-done-standalone-distribution.md`,
which no longer exists).

**Historical — do not cite line numbers from this table.** It records what the 2026-08-27
pass corrected in the 2026-07-18 revision; several of its coordinates were themselves
superseded on 2026-09-02 (see the delta re-audit below, which is authoritative). Kept so the
reasoning chain stays auditable.

| Claim as written | Verdict | Correction |
|---|---|---|
| `func self` / `func plugin` are top-level groups | **falsified, blocking** | `SELF.1` — ADR-004 reserved `builtin` as the one top-level segment |
| PyApp `self` collision is blocking | **premise removed** | Under `func builtin self`, PyApp never sees `self`. The pin is retained for cross-mode uniformity, not collision avoidance |
| Doctor checks core import / config chain / execution / plugin loading | **falsified, load-bearing** | `DOC.1–5` — all four run after a full boot; three can only report OK, and plugin failures are swallowed with no record |
| Embedding ⇒ offline first run, ~3s, 35–50MB | **falsified, load-bearing** | §5.1 — PyApp still fetches uv and every dependency. Figures withdrawn pending **O1** |
| Three audiences | **falsified, load-bearing** | Fourth: consumer apps, which get the whole `builtin` tree **by default** (`register_builtins=True`). Detection gains an owning-distribution axis (`RMO.1–3`) |
| "plugin" = one entry-point group | **falsified, load-bearing** | `PLG.1` — eight groups; `functualize-inline` is in none of the one named |
| `builtins.py` is a 724-line module | **drifted** | 1376 lines as of 2026-08-27; **1801 at `39a0be2`** (`MOD.1`) |
| `builtins.py` converts to a package, commands "move unchanged" | **falsified** | `MOD.1–2` — one 882-line function of 74 closures; follow the `scaffold` mounting idiom instead |
| "the registry-mirror test is extended" | **drifted** | `MOD.5` — it derives from `BUILTIN_COMMANDS` and needs no edit |
| Reuse `_dispatch_group` (`_cli/main.py:774`) | **drifted + wrong route** | Now `:881`; `func builtin …` routes via `Mode.BUILTIN` through the click group |
| `resolve_user_config_dir()` in `app/utils.py` | **confirmed, line drifted twice** | `:797` as of 2026-08-27; **`:861` at `39a0be2`** (`MAN.1`) |
| "if remove-typer lands first, author click-native" | **moot** | ADR-004; zero typer imports in `src/` |
| Links to persistent-process / kernel-persistent-process-api / shell-and-task-runner | **stale** | Files absent from the repo; daemon out of scope; third superseded by ADR-005 |
| `func self daemon *` contingent | **stale** | `.spec/STATUS.md`: the daemon "has no spec … no unblocking event". Removed |
| `_cli/runtime.py` preserves "warm-boot 0-imports" | **mislabelled (repo-wide)** | That test is about job-module imports. `_cli/main.py:1684-1688` uses the same shorthand, so this is the repo's loose usage rather than the document's error — but it matters, because it means nothing currently guards the pre-boot path (`FR.3`) |
| `--json` | **drifted** | `SELF.5` — `--format json` |
| No exit codes specified | **gap** | `RMB.1` — `ExitCode.REFUSED` exists for exactly this case |
| ~200/~180 LOC vs a "250-LOC ceiling" | **no such rule** | `MOD.6` — only a ~500-LOC class ceiling exists |
| `sys.prefix` ladder, uv tools dir | **confirmed by experiment** | uv 0.11.18: `VIRTUAL_ENV: None`, `sys.prefix` under `~/.local/share/uv/tools/<tool>` |
| Receipt merge is required | **confirmed by experiment** | uv 0.11.18 second install printed `- six==1.17.0`; no `uv tool add`/`inject` exists |
| `PYAPP=1`, `PYAPP_COMMAND_NAME`, `PYAPP_SELF_COMMAND` default `self` | **confirmed** | PyApp runtime + CLI config docs |
| Manifest append-only, doctor flags dead `binary_path` | **confirmed** | `MAN.2`, `MAN.4`; gains `owning_distribution` |
| Nothing of this exists yet | **confirmed** | grep across `src/`, `tests/`, `docs/` |
| pipx `sys.prefix` signal | **unverified** | `RMD.4` — no pipx on the scrutiny host |
| Nuitka / PyInstaller drawbacks | **unverified, not re-litigated** | No live evidence against the PyApp choice |

---

## 2026-09-02 delta re-audit

Full report: `.spec/scrutiny-reports/standalone-distribution-2026-09-02.md`.

**Verdicts: 0 changes.** All 50 GAPs remain GAP (the feature is still entirely unbuilt) and
all 7 PASSes re-verify. What moved was provenance, citations, and two rationales.

| What changed | Verdict | Correction |
|---|---|---|
| "audited against HEAD `3503495`" | **falsified (provenance)** | `3503495` is not an ancestor of this branch. `git merge-base 3503495 HEAD` = `f12644c`; PRs #7, #8, #10, #12, #13, #14, #15 merged on the fork it missed (94 files, +6325/−1279 in `src/`). Baseline is now `39a0be2` |
| `install`/`uninstall` "avoid the collision for free" (`PLG.5`) | **falsified, load-bearing** | PR #14's `skills` family has an `install` subcommand. Demonstrated in §4.1. Opened as **O4**, **closed 2026-09-03**: fix the predicate rather than the names — see prerequisite **P1** |
| `builtin info` is a flat command (`SELF.4`) | **drifted, load-bearing for O3** | PR #14 made it a group with `jobs`/`schema`/`all` and its own JSON path (`:1543-1799`). Fold target is now `info all` |
| `CliAdapter` mounts the subtree "into every consumer application" | **partially true (authoring error, not drift)** | The mount is `if register_builtins:`, a parameter defaulting `True` — and it already was at `f12644c`. Default behavior is unchanged; the wording overstated it |
| `resolve_user_config_dir()` "five existing call sites", exported at `:93` | **drifted** | Nine call sites; defined `:861`, exported `:152` |
| `tests/perf/conftest.py` holds the coverage/xdist skip (`FR.3`) | **stale** | File deleted by PR #13; guard moved to `tests/conftest.py:129-148`. The substance of `FR.3` is unaffected |
| `[project.scripts]` is in `templates/*/main.py.j2` (`RMO.2`) | **wrong at authoring time** | It is in `templates/*/pyproject.toml.j2` |
| `_app/boot.py:1231` holds an unrelated `PYAPP` comment | **stale** | Gone. The feature-artifact grep now returns **zero** hits repo-wide |
| `builtins.py` is 1376 lines; `register_builtin_commands` is an 882-line function of 74 closures | **drifted (argument strengthened)** | 1801 lines; `:556-1801` is a 1246-line function of 103 closures |
| Idiom "sibling module + two-line mount" has one precedent (`scaffold`) | **superseded** | PR #14 added `skills` (`:1521`) as a second. The 2026-08-27 "weak standard" flag lifts |
| `ExitCode.REFUSED` is reachable only from a CLI refusal | **superseded** | PR #13 wired `RunStatus.REFUSED → ExitCode.REFUSED` into the status table (`_types/exit_codes.py:63`) |
| Citations into `_plugins/`, `_config/registry.py`, `_primitives/entry_points.py`, `_cli/completions/provenance.py` | **confirmed exact** | Those files are byte-identical since `f12644c`, so `DOC.3`, `PLG.1`, `PLG.2`, `PLG.8` and `PER.*` need no re-derivation |
| **O1, O2, O3 still open** | **confirmed** | No new evidence bears on any of them. **O4 was opened 2026-09-02 and closed 2026-09-03** |
| `skills install` spawns `npx` but declares no `terminal_subcommands` | **new defect, live today** | Found 2026-09-03 while resolving O4. Orthogonal to this feature and **not fixed by P1**; file separately. See the adjacent-defect note in §4.1 |

### Blocked on process, not design

`.spec/features/` does not exist. Per `.claude/rules/spec-workflow.md`, a `PreToolUse` hook
denies `Edit`/`Write` to `src/functualize/**` without a `tasks.md` carrying a parseable
`## Task Dependency Graph`. **Sections 1–4 cannot begin from this document alone** — they
need `/agentic-specify` → `/agentic-plan` first.

### Repo defect noticed in passing (out of scope)

`pyproject.toml:138` describes the `perf_budget` marker as "see tests/perf/conftest.py" — a
dangling reference to the file PR #13 deleted. Worth a one-line fix, unrelated to this
feature.
