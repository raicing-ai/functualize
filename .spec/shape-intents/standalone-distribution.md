# Shape Intent: Standalone Distribution & Self-Management

**Status: specified, not yet implemented**
**Date: 2026-08-27** (consolidated 2026-07-16 from the Plan 008 family; revised 2026-07-18
after adversarial scrutiny; re-scrutinized and restructured 2026-08-27 against HEAD `3503495`)
**Scope: `_cli/` delivery plus a release-time PyApp build pipeline. No kernel changes, no
new layer, no new public API. The daemon is explicitly out of scope.**

Make functualize installable and manageable without Python knowledge leaking into the UX:
detect how the running `func` was installed, expose that through `func builtin self`, and
let `func builtin plugin` install and remove plugin packages using the right tool for that
installation — plus a PyApp-built single binary for users who have no Python at all.

**Current state: none of this exists.** Verified 2026-08-27:
`grep -rn "FUNCTUALIZE_RUNTIME\|install.json\|PYAPP" src/ tests/ docs/` returns one
unrelated comment (`_app/boot.py:1231`), and
`git log --all -i --grep='pyapp' --grep='func self' --grep='standalone'` returns only this
document's own commits.

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
the whole `builtin` subtree into every consumer application
(`src/functualize/app/adapters/cli.py:627-634`), so a scaffolded app gets these commands.

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

## Decisions still open — these block section 5

| # | Open question | What it blocks | Why it cannot be defaulted here |
|---|---|---|---|
| **O1** | PyApp build recipe **A** (network first run) or **B** (pre-baked distribution + `PYAPP_SKIP_INSTALL`) | all of §5 | Binary size and first-run latency are downstream of it. The previous revision's "offline-capable, ~3s, 35–50MB" assumed B while specifying A |
| **O2** | `PYAPP_PROJECT_FEATURES = cli` or `all` | §5, binary size | `.spec/ARCHITECTURE.md` documents `functualize[all]` as pulling eleven plugin packages. This single choice dominates binary size and is made nowhere |
| **O3** | Fold `self paths` / `self config-info` into the existing `builtin config path` / `builtin info`, or keep them separate | `SELF.3`, `SELF.4` | Recommended: fold. See §3 |

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

**57 assertions, audited 2026-08-27 against HEAD `3503495`: 7 PASS, 50 GAP.** Every
assertion below carries its verdict inline, with the `file:line` the verdict rests on. The
7 PASSes are pre-existing compliance — mechanisms that already exist and must be *used*,
not built (`SELF.2`, `PLG.3`, `PER.4`, `MOD.2`, `MOD.4`, `MOD.5`, `MOD.6`). Four of them
remove work the previous revision had scoped in.

**DO NOT immediately edit files.** Instead:

1. Read the current code for each assertion below.
2. Confirm each `PASS`/`GAP` verdict in the tables — they were audited on 2026-08-27 and
   the codebase has moved before.
3. Present every GAP as a work item with the exact file, line range, and what would change.
4. Resolve **O1–O3** with a maintainer before starting §5.
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
| `RMO.2` | For `func`/`functualize` the owner is `functualize`; for a scaffolded app's script it is that app's distribution | **GAP** — the scaffold template declares `[project.scripts] weather-app = "weather_app.main:run"` (`_cli/scaffold/templates/*/main.py.j2`), so the two are genuinely distinct |
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
| `RMB.1` | Every degraded-mode refusal exits `ExitCode.REFUSED` (3), printing guidance and executing nothing | **GAP** — `ExitCode` exists with exactly this member (`_types/exit_codes.py:42`), re-exported at `app/utils.py:58`; the previous revision specified no exit codes at all |
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
| `MAN.1` | The manifest lives at `resolve_user_config_dir() / "install.json"` — never a hardcoded `~/.config` | **GAP** — no manifest exists. The helper it must use does: `resolve_user_config_dir()` at `app/utils.py:797`, exported at `:93`, respecting `XDG_CONFIG_HOME`, with five existing call sites |
| `MAN.2` | The manifest is append-only; installation records are never deleted | **GAP** |
| `MAN.3` | Records carry `owning_distribution` (axis 2), so an embedded-mode install is distinguishable from a functualize-owned one | **GAP** — new in the 2026-08-27 revision |
| `MAN.4` | Doctor flags entries whose `binary_path` no longer exists rather than trusting them | **GAP** |
| `FR.1` | On first run a hint is printed (`Run 'func builtin self doctor' for a health check.`) and nothing is blocked | **GAP** |
| `FR.2` | The hint fires on the first real invocation after PyApp's bootstrap completes | **GAP** — PyApp exposes no mid-bootstrap hook; its docs state "all subsequent invocations will only check if the installation directory exists and nothing else" |
| `FR.3` | The warm path costs one `stat()`; `functualize._cli.manifest` is **absent from `sys.modules`** after a warm second invocation | **GAP, and undefended by any existing gate** — `tests/perf/test_startup_budget.py` budgets only `FunctualizeApp.__init__` phases, and those are skipped under coverage and xdist (`tests/perf/conftest.py`). The pre-boot CLI path has no wall-clock budget at all, so this must be a *structural* assertion, not a timing one |

---

## 3. `func builtin self`

```
func builtin self doctor        # Health check (extensible by plugins)
func builtin self config-info   # Runtime mode, owning distribution, manifest (--format json)
func builtin self paths         # Quick path reference
func builtin self update        # Mode-aware update with confirmation
```

### 3.1 Namespace — load-bearing

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `SELF.1` | The group is mounted as a child of `builtin`, spelled `func builtin self …`. There is **no** top-level `func self` | **GAP (and the single biggest correction in this revision)** — ADR-004 §Phase A.3 reserved `builtin` as the *one* top-level segment. `register_builtin_commands` states "There are **no top-level spellings and no deprecation aliases**" (`_cli/builtins.py:497-514`); `BUILTIN_NAMES == frozenset({"builtin"})` (`:150`); the trie rejects the name for jobs, groups and plugin namespaces (`_types/naming.py:418-421`, `_app/boot.py:1165-1173`, `_app/impl.py:255-262`); and `tests/_cli/test_builtin_command_pilot.py:356` asserts the top level holds exactly `BUILTIN_NAMES`. **A top-level `self` group fails that test.** |
| `SELF.2` | The depth `builtin` → `self` → subcommand is representable without registry changes | **PASS** — `BuiltinCommand.subcommands` is one level and `builtin_subcommands()` returns the two-level map (`_cli/builtins.py:167-178`) |
| `SELF.3` | `self paths` does not duplicate `builtin config path` | **GAP → resolve O3** — `builtin config path` already prints the XDG global path, `pyproject.toml [tool.functualize]` and `.functualize.toml` with used/found/missing status (`_cli/builtins.py:1150-1206`). Shipping both is `pitfalls.md` #6 |
| `SELF.4` | `self config-info` does not duplicate `builtin info` | **GAP → resolve O3** — `builtin info` already prints app state, discovered jobs, resolved config, anchor, `import_libs` and convention dirs (`:1316-1373`). The only genuinely new lines are runtime mode, owning distribution and the manifest — three lines. **Recommendation: fold them in and drop `self paths` / `self config-info` entirely.** |
| `SELF.5` | Structured output uses a command-owned `--format json`, not `--json` and not the global `--output` | **GAP** — `builtin workflow list` establishes command-owned `--format` as deliberately distinct from the global `--output {auto,json,ndjson,raw,none}` (`_cli/builtins.py:651-660`, `_cli/dispatch.py:100`) |
| `SELF.6` | In standalone mode `self update` re-execs `func pyapp update`, then reconciles manifest-recorded plugins | **GAP** |

### 3.2 Doctor architecture — rewritten 2026-08-27

The 2026-07-18 design placed doctor as an ordinary builtin. **It cannot work there.**
`cli_app`, the click group callback, runs `resolve_cli_config` → `_load_dotenv` →
`_apply_import_libs` → `auto_discover` → `FunctualizeApp(...)` → `app.refresh()` and only
then wires `ctx.obj` (`_cli/main.py:226-305`). Every builtin subcommand runs after a full
boot, so:

- **"core import + version", "config resolution chain", "execution smoke test"** had to
  succeed for doctor to be *reached*. They can only ever print OK — `pitfalls.md` #1's
  shape relocated into a health check, which is worse than a dead setting: a health check
  that cannot report ill.
- **"plugin loading" fails the other way.** `_load_file_plugin` catches `Exception`, logs a
  warning and returns `None` (`_plugins/loader.py:761-773`), and **no failure record is
  kept** — no `failed_plugins`/`load_errors` attribute exists anywhere in `_plugins/` or
  `app/core.py`. Demonstrated 2026-08-27: a `.functualize/plugins/` module containing
  `raise RuntimeError(...)` leaves `func builtin version` at exit 0 with only a log line.
  A post-boot doctor would report "plugins: ok". That is `pitfalls.md` #2 reaching the
  diagnostic layer.

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `DOC.1` | `self doctor` is intercepted **pre-boot** in `_run_cli`, beside `--version` and `scan_early_setting_flags` | **GAP** — the escape hatch exists and is the repo's own idiom for commands that must answer before the app exists (`_cli/main.py:1700-1737`) |
| `DOC.2` | Boot-shaped checks run in a **child process**, so a boot that dies is a reportable result rather than doctor's own traceback | **GAP** |
| `DOC.3` | Doctor reports a plugin that failed to load | **GAP, and currently unobtainable** — needs either a log handler around the child probe or a load-failure record added to `PluginLoader` in a separate change. Until one exists, **the plugin check is omitted, not faked** |
| `DOC.4` | Every check that can only be satisfied by the process doctor is already running in is **deleted**, not kept as decoration | **GAP** |
| `DOC.5` | Surviving checks: Python ≥ 3.11 (critical), CLI extras (warning), job discovery from CWD (info), child boot probe (critical), manifest-vs-installed plugin reconciliation in standalone mode (warning), stale `binary_path` entries (info), terminal capabilities (info), runtime mode + owning distribution (info) | **GAP** — the Python floor matches `requires-python = ">=3.11"` (`pyproject.toml:10`) |

---

## 4. `func builtin plugin`

```
func builtin plugin list
func builtin plugin install <pkg>     # mode-aware; prints the exact command + y/N confirmation
func builtin plugin uninstall <pkg>
```

`install`/`uninstall`, not `add`/`remove` — see `PLG.5`.

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
| `PLG.5` | The mutating subcommands are named `install`/`uninstall`, not `add`/`remove` | **GAP, with a concrete reason** — see the terminal-ownership note below |
| `PLG.6` | `plugin install` is not followed by an in-process plugin read in the same invocation | **GAP** — see `PLG.8` |
| `PLG.7` | Mutating subcommands are declared in `BuiltinCommand.terminal_subcommands` so the inline TUI hands off instead of capturing | **GAP** — the mechanism exists and is the repo idiom: `_builtin_needs_terminal` (`app/commands.py:306-316`) collapses the family predicate per node and `_cli/tui/job_execution.py:412` routes to `_run_builtin_handoff`, the same path `builtin config edit` takes |
| `PLG.8` | The entry-point snapshot invariant is honored or corrected | **GAP** — `_primitives/entry_points.py` documents its process-wide snapshot as "deliberately never invalidated on its own: … **nothing functualize does installs a distribution into the running interpreter.**" In standalone mode `plugin install` runs `uv pip install` into the PyApp-managed venv, which *is* the running interpreter's environment, making that sentence false. `clear_entry_point_cache()` exists but lives in `_primitives`, which `_cli` may not import — so either the command exits after printing (recommended) or the docstring is corrected and a public re-export added under an ADR |

> **Why `install`/`uninstall` and not `add`/`remove`.**
> `BUILTIN_ROOT_COMMAND.terminal_subcommands` is a **flattened** tuple across all families
> (`_cli/builtins.py:143-145`) and `needs_terminal` is `any(arg in … for arg in args)`
> (`:46-48`). Declaring `add` as terminal would make
> `get_builtin("builtin").needs_terminal(["scaffold", "add"])` return True — and `scaffold`
> has an `add` subcommand (`:96-100`). Production reads the family-scoped predicate, so
> this is latent today and exercised only by `tests/_cli/test_builtin_handoff.py:96-100`
> ("`config edit` is the one true case in the registry") — but this feature supplies the
> first input that would make it observable. Non-colliding names avoid it for free; making
> the root predicate path-aware is the alternative fix and is out of scope here.

### 4.2 Plugin persistence — load-bearing

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `PER.1` | In tool (uv) mode, `plugin install`/`uninstall` read `uv-receipt.toml` from the tool dir and re-emit **all** prior requirements plus/minus the change | **GAP, requirement re-confirmed** — on uv 0.11.18, `uv tool install pycowsay --with six` then `uv tool install pycowsay --with idna` printed `- six==1.17.0` and rewrote the receipt to drop it. `uv tool --help` lists no `add`/`inject`, so this cannot be delegated |
| `PER.2` | The merge reconstructs a PEP 508 requirement from **every** key present, not just `name`, and round-trips unknown keys rather than dropping them | **GAP** — observed shapes: `{ name = "pycowsay" }`, `{ name = "idna", specifier = ">=3.0" }`, `{ name = "a0", url = "https://…zip" }`. The previous revision spoke of "`--with` entries" as if they were plain names |
| `PER.3` | In standalone mode the manifest records added plugins, and `self update` (plus doctor runs) reinstalls missing recorded ones via bundled uv, with confirmation | **GAP** — PyApp update/restore rebuilds the managed venv from the project requirement only, wiping `uv pip install`ed plugins |
| `PER.4` | `uv tool upgrade` is left to preserve receipt-recorded settings — no special handling once the receipt is correct | **PASS (upstream behavior)** |

---

## 5. PyApp build and distribution

**Blocked on O1 and O2.** Do not start this section until both are answered.

### 5.1 The embedding claim was falsified

The 2026-07-18 revision stated that building with `PYAPP_DISTRIBUTION_EMBED` and an
embedded project wheel makes "first run offline-capable and the ~3s bootstrap figure hold".
**PyApp does not work that way.** Its runtime documentation lists first-run network
requirements as: retrieving the distribution, **downloading uv or pip if not cached**, and
**installing project dependencies**. `PYAPP_DISTRIBUTION_EMBED` removes only the first.

Concretely, `functualize[cli]` pulls `pydantic`, `python-dotenv`, `jinja2`, `click`,
`rich`, `textual`, `textual[syntax]` and `textual-autocomplete`
(`pyproject.toml:22-26,68-75`) — every one fetched from PyPI at first run. And
`PYAPP_UV_ENABLED=1` means uv performs "virtual environment creation and project
installation", i.e. uv is needed *during* bootstrap, not (as previously written) "on first
plugin/PEP 723 use". The two chosen settings are not jointly offline-capable.

| | **A** — network first run | **B** — pre-baked distribution |
|---|---|---|
| Build | `PYAPP_DISTRIBUTION_EMBED=1` + `PYAPP_PROJECT_PATH=<wheel>` | a python-build-standalone distribution with functualize **already installed**, embedded, plus `PYAPP_SKIP_INSTALL=1` |
| First run | needs network for uv + dependencies | fully offline |
| Size | smaller binary; latency is a network lottery | larger binary; ~3s figure plausible |
| Effort | ships today | needs a distribution-baking CI step that does not exist |

Recipe B is the shape Hatch ships and is what the withdrawn "offline-capable, ~3s, 35–50MB"
numbers were implicitly describing.

### 5.2 Build configuration

The previous revision named three variables. The minimum viable set:

| Variable | Value | Note |
|---|---|---|
| `PYAPP_PROJECT_NAME` | `functualize` | required |
| `PYAPP_PROJECT_VERSION` | release version | required |
| `PYAPP_PROJECT_PATH` | path to the built wheel | **the option that actually embeds the project** — previously unnamed |
| `PYAPP_PROJECT_FEATURES` | `cli` or `all` | **O2** |
| `PYAPP_EXEC_SPEC` | `functualize._cli.main:main` | matches `[project.scripts]` (`pyproject.toml:34-36`) — previously unspecified |
| `PYAPP_SELF_COMMAND` | `pyapp` | see the collision section |
| `PYAPP_UV_ENABLED` | `1` | uv for venv creation, installs, PEP 723 |
| `PYAPP_DISTRIBUTION_EMBED` / `PYAPP_SKIP_INSTALL` | per **O1** | |

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `PY.1` | Release-tag CI builds x86_64/aarch64 × linux/macos binaries | **GAP** |
| `PY.2` | The build sets every variable in the table above, none defaulted implicitly | **GAP** |
| `PY.3` | CI asserts the actual binary size on release builds — a **measured** number, not an estimate quoted here | **GAP** |
| `PY.4` | Distribution: GitHub Releases + `install.sh` + Homebrew formula | **GAP** |
| `PY.5` | The README install section gains a standalone row | **GAP** — deferred until O1 is answered, since the instructions differ per recipe |

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
| `MOD.1` | `_cli/builtins.py` is **not** converted to a package | **GAP (scope reduction)** — the previous revision called it a "724-line module" whose commands would "move unchanged" into `_cli/builtins/`. It is now **1376 lines**, and `register_builtin_commands` spans `:495-1376` — one 882-line function containing 74 nested `def`/decorator sites, all closures over local groups. Moving them is a refactor, not a move |
| `MOD.2` | `self_app`/`plugin_app` are defined in sibling `_cli` modules and mounted in two lines each | **PASS (idiom exists)** — `scaffold` already does exactly this: `from functualize._cli.scaffold.cli import scaffold_app; _mount(builtin_app, scaffold_app, "scaffold")` (`_cli/builtins.py:1301-1304`) |
| `MOD.3` | Two `BuiltinCommand` entries are appended to `BUILTIN_COMMANDS`; no other registry surface changes | **GAP** |
| `MOD.4` | No cache-format bump is required | **PASS** — follows from MOD.1/MOD.2; nothing serialized changes |
| `MOD.5` | The registry-mirror test covers the new commands without being edited | **PASS** — `test_registry_matches_the_real_click_commands` derives its expectations from `BUILTIN_COMMANDS` and walks both levels (`tests/_cli/test_builtin_command_pilot.py:332-373`). This corrects the previous revision's claim that the test "is extended to cover them" |
| `MOD.6` | No module-size rule is violated | **PASS** — there is **no ~250-LOC module ceiling** in this repo; the only limits are a ~500-LOC *class* ceiling and two named facades (`.spec/CONSTITUTION.md:90,166-167`). `builtins.py` is 1376 lines and `main.py` 1935 |
| `MOD.7` | New modules import public folders only | **GAP (contract already enforces it)** — `pyproject.toml` contract "_cli uses public API only"; `_cli/__init__.py` docstring |

### Routing

`func builtin …` is classified `Mode.BUILTIN` in `detect_mode` and dispatched through the
click group (`_cli/dispatch.py:249-257`) — **not** through `_dispatch_group`
(`_cli/main.py:881`, moved from `:774`), which handles job groups. That branch carries a
live `# TRANSITIONAL(cli-shell-convergence §2.B.1)` marker noting that the planned fold of
`builtin` into the trie is "deferred and unscheduled".

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `RT.1` | This work does not depend on the `builtin`-into-trie fold, and does not silently complete it | **GAP** — if any transitional state is introduced, it carries its own `# TRANSITIONAL(<step>): …` marker per `.spec/CONSTITUTION.md` |

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
  `src/functualize/app/utils.py:797` (`resolve_user_config_dir`);
  `src/functualize/_cli/main.py:1671-1740` (`_run_cli` pre-boot region)
- `SELF.1–6`: `src/functualize/_cli/builtins.py:22-208` (registry), `:1150-1206`
  (`config path`), `:1316-1373` (`info`), `:651-660` (`--format` precedent);
  `src/functualize/_types/naming.py:175,418-421`
- `DOC.1–5`: `src/functualize/_cli/main.py:226-305` (the boot-before-builtin problem) and
  `:1700-1737` (the pre-boot escape hatch); `src/functualize/_plugins/loader.py:761-773`
- `PLG.1–8`: `src/functualize/_plugins/loader.py:249-256,326`;
  `src/functualize/_plugins/domain_registry.py:156,246`;
  `src/functualize/_config/registry.py:169,193`;
  `src/functualize/_cli/completions/provenance.py:151-154`;
  `src/functualize/_primitives/entry_points.py`;
  `src/functualize/app/commands.py:306-316`;
  `src/functualize/_cli/tui/job_execution.py:412-443`
- `PER.1–4`: no repo code — verify against a real `uv-receipt.toml` under `uv tool dir`
- `PY.1–5`: `.github/workflows/`, `README.md`
- `MOD.1–7`, `RT.1`: `src/functualize/_cli/builtins.py:495-1376`;
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
| T11 | Registry mirrors the real click tree | already covered — no new test (`MOD.5`) |

> `tests/conftest.py:126-142` strips `FUNCTUALIZE_*` and `XDG_*` autouse, so every test
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
- **consumer app** — `CliAdapter.__call__` → `register_builtin_commands`
  (`app/adapters/cli.py:627-634`)

Commit first, then sabotage the `_mount(builtin_app, self_app, "self")` call and confirm a
test fails (`.spec/CONSTITUTION.md` → *Commit before sabotaging*).

### Documentation to update at close

`contributor/reference/code-map.md:176-184` and
`contributor/architecture/codemaps/modules.md:102-104` both enumerate `_cli/` modules, and
neither would fail `tests/test_contributor_docs.py` if left stale — that suite only checks
that referenced paths *exist*. Update both by hand.

---

## Scrutiny vs current codebase

Working notes: `.spec/scrutiny-reports/standalone-distribution-2026-08-27.md` (gitignored).
Every claim from the 2026-07-18 revision that moved, and its correction:

| Claim as written | Verdict | Correction |
|---|---|---|
| `func self` / `func plugin` are top-level groups | **falsified, blocking** | `SELF.1` — ADR-004 reserved `builtin` as the one top-level segment |
| PyApp `self` collision is blocking | **premise removed** | Under `func builtin self`, PyApp never sees `self`. The pin is retained for cross-mode uniformity, not collision avoidance |
| Doctor checks core import / config chain / execution / plugin loading | **falsified, load-bearing** | `DOC.1–5` — all four run after a full boot; three can only report OK, and plugin failures are swallowed with no record |
| Embedding ⇒ offline first run, ~3s, 35–50MB | **falsified, load-bearing** | §5.1 — PyApp still fetches uv and every dependency. Figures withdrawn pending **O1** |
| Three audiences | **falsified, load-bearing** | Fourth: consumer apps, which get the whole `builtin` tree. Detection gains an owning-distribution axis (`RMO.1–3`) |
| "plugin" = one entry-point group | **falsified, load-bearing** | `PLG.1` — eight groups; `functualize-inline` is in none of the one named |
| `builtins.py` is a 724-line module | **drifted** | 1376 lines (`MOD.1`) |
| `builtins.py` converts to a package, commands "move unchanged" | **falsified** | `MOD.1–2` — one 882-line function of 74 closures; follow the `scaffold` mounting idiom instead |
| "the registry-mirror test is extended" | **drifted** | `MOD.5` — it derives from `BUILTIN_COMMANDS` and needs no edit |
| Reuse `_dispatch_group` (`_cli/main.py:774`) | **drifted + wrong route** | Now `:881`; `func builtin …` routes via `Mode.BUILTIN` through the click group |
| `resolve_user_config_dir()` in `app/utils.py` | **confirmed, line drifted** | `app/utils.py:797` (`MAN.1`) |
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
