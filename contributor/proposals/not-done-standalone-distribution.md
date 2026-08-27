# Standalone Distribution & Self-Management

**Status: proposed**

> Consolidated 2026-07-16 from the former Plan 008 family. Revised 2026-07-18 after
> adversarial scrutiny (PyApp `self` collision, runtime-detection ladder, plugin
> persistence, embedding decision). **Revised 2026-08-27** after a second scrutiny against
> HEAD `3503495` — see [Scrutiny vs current codebase](#scrutiny-vs-current-codebase). The
> 2026-08-27 pass changed, in order of impact: the command namespace (ADR-004 moved every
> first-party command under `func builtin …`), the doctor architecture (it could not
> observe what it claimed to check), the audience count (four, not three), the plugin
> population (eight entry-point groups, not one), and the offline/embedding claim
> (falsified — embedding the distribution does not remove the dependency download).
>
> **Current state: none of this exists.** No runtime detection, no `self`/`plugin`
> commands, no install manifest, no standalone binary. Verified 2026-08-27: `grep -rn
> "FUNCTUALIZE_RUNTIME\|install.json\|PYAPP" src/ tests/ docs/` returns one unrelated
> comment.
>
> **Canonical home.** This document is a *shape intent* in this repository's current
> vocabulary, and `contributor/proposals/` is a directory the repo otherwise does not have
> (`contributor/README.md`'s structure tree omits it; `git log -- contributor/proposals/`
> shows it deleted and re-created for this file alone). It should move to
> `.spec/shape-intents/standalone-distribution.md`, be restructured as numbered PASS/GAP
> assertions in the style of `tui-group-options-panels.md`, and be indexed from
> `.spec/STATUS.md` and `.spec/README.md`. That move is deliberately *not* bundled into
> this revision — it is a maintainer call about where the repo keeps pre-implementation
> design work.
>
> **Out of scope for this document.** `func builtin self daemon *` is **not specified
> here**. `.spec/STATUS.md` records that `persistent-process.md` and
> `kernel-persistent-process-api.md` "no longer exist anywhere in the repo" and that the
> daemon "has no spec … no unblocking event". Daemon subcommands are removed from the
> command group below rather than carried as contingent lines. Do not re-derive them from
> this document.
>
> **Superseded cross-references.** The former `remove-typer.md` and
> `shell-and-task-runner.md` graduated to [ADR-004](../adr/004-cli-shell-convergence.md)
> and [ADR-005](../adr/005-shell-and-task-runner.md) (both accepted 2026-07-24). Typer is
> gone; author everything click-native. PEP 723 script dependencies (formerly cross-linked)
> ship today in `_cli/pep723.py`.

---

## Goal

Make functualize installable and manageable without Python knowledge leaking into the UX.
There are **four** audiences, not three — the fourth was added 2026-08-27 because
`CliAdapter` mounts the whole `builtin` subtree into every consumer application
(`app/adapters/cli.py:627-634`), so these commands exist there whether or not they were
designed for it.

| Mode | Audience | Installation | Python env | Owning distribution |
|------|----------|-------------|------------|---------------------|
| **standalone** | Non-Python dev, ops | binary download, `brew install functualize` | PyApp-managed | `functualize` |
| **tool** | Python dev with uv/pipx | `uv tool install "functualize[cli]"` | uv/pipx isolated env | `functualize` |
| **project** | Framework user | `uv add "functualize[cli]"` | project `.venv/` | `functualize` |
| **embedded** | User of an app *built on* functualize | `uv tool install -e .` in a scaffolded project | that app's env | **the consumer app** (`weather-app`) |

Two degraded modes exist for honesty, not as targets: **tool (pip)** (no venv: bare pip,
system Python, conda) and **unknown** (an unrecognised venv — dev checkout, functualize as
a transitive dependency). In both, mutating commands print guidance and exit
`ExitCode.REFUSED` (`_types/exit_codes.py:42`) instead of executing.

> **Terminology.** "Standalone" already means *single-file scripts run through `func`* in
> this repo (`examples/standalone/`, `tests/standalone/`, developer Mode **D** in
> `contributor/architecture/developer-modes.md`). The enum introduced here is
> `InstallMode`, never `Mode` — `_cli/dispatch.Mode` is a live enum whose members already
> include `UNKNOWN`.

---

## Runtime mode detection

Two axes, resolved together:

**Axis 1 — environment kind.** First match wins:

1. `FUNCTUALIZE_RUNTIME` env var → explicit override (CI/testing). The name is free
   (`FUNCTUALIZE_ENV` is the config-overlay name and is unrelated).
2. `PYAPP=1` or `PYAPP_COMMAND_NAME` set → standalone. PyApp injects `PYAPP=1` into the
   spawned process; `PYAPP_COMMAND_NAME` carries `PYAPP_SELF_COMMAND`'s value when
   management commands are enabled.
3. `sys.prefix` is under the uv tools directory (`uv tool dir`, default
   `$XDG_DATA_HOME/uv/tools` → `~/.local/share/uv/tools`) → tool (uv). **Not**
   `VIRTUAL_ENV`: that is set by shell *activation*, not by executing a venv interpreter
   through a script shebang, which is how a uv-tool binary runs. Re-verified 2026-08-27 on
   uv 0.11.18: a tool's interpreter reports `sys.prefix` under the tools dir and
   `VIRTUAL_ENV: None`.
4. `sys.prefix` contains `pipx/venvs` → tool (pipx). (`PIPX_HOME` is unset for default
   installs — do not rely on it. Unverified on this host; see the scrutiny report.)
5. Nearby `pyproject.toml` declaring functualize → project.
6. `sys.prefix == sys.base_prefix` → tool (pip), degraded.
7. Fallback → **unknown**, degraded. Never assume standalone: a wrong guess makes
   `plugin install` print bundled-uv commands that do not exist and `self update` attempt a
   PyApp update against a non-PyApp binary.

> Rung 5 is a directory walk plus a TOML parse — `contributor/reference/pitfalls.md` #16's
> exact shape ("a syscall on the left of `and`", 17,249 stats per boot). It is safe **only**
> because rungs 1–4 are pure env and string checks that answer first in every non-project
> case. Keep that ordering, bound the upward walk at the same anchor `resolve_cli_config`
> already uses, and never move a filesystem rung above a pure one.

**Axis 2 — owning distribution.** Which distribution provides the running console script.
Derive it from `sys.argv[0]`'s basename reverse-mapped through `importlib.metadata`. In
the first three modes this is `functualize`; in **embedded** mode it is the consumer app.
Every mutating command names *this* distribution, not `functualize`:
`weather-app builtin self update` must offer `uv tool upgrade weather-app`.

Mode drives behaviour (`<dist>` = the owning distribution from axis 2):

| Behaviour | standalone | tool (uv) | tool (pipx) | project | tool (pip) / unknown |
|-----------|-----------|-----------|-------------|---------|----------------------|
| `plugin install X` | bundled `uv pip install X` + record in manifest | receipt-merged `uv tool install <dist> --with <all prior> --with X` | `pipx inject <dist> X` | `uv add X` | print `pip install X`, exit `REFUSED` |
| `self update` | `func pyapp update`, then reconcile manifest plugins | `uv tool upgrade <dist>` | `pipx upgrade <dist>` | `uv lock --upgrade-package <dist> && uv sync` | refuse with guidance, exit `REFUSED` |
| Python ownership | functualize | uv | pipx | project venv | user |

Edge cases: coexisting PyApp + uv-tool installs are both recorded in the manifest (PATH
decides which runs); CI with no venv falls to tool (pip) and doctor reports it.

Alternatives considered: explicit config file (manual burden — rejected), env-var +
`sys.prefix` signals (chosen), `VIRTUAL_ENV` heuristics (falsified). For distribution:
PyApp (chosen — single binary, uv-powered, proven by Hatch) over Nuitka (fragile with
pydantic-core), PyInstaller (slow startup, AV false positives), Docker (poor CLI UX).

---

## PyApp `self` collision (decision retained, rationale replaced)

PyApp's management command group is named **`self`** by default (`PYAPP_SELF_COMMAND`) and
PyApp intercepts `<binary> self …` *before Python starts*.

**The collision this decision was created to solve no longer exists.** Under ADR-004
functualize's group is `func builtin self`, whose first token is `builtin` — PyApp never
sees a `self` it would claim. The 2026-07-18 blocking finding is resolved by a change made
for unrelated reasons.

**Decision (retained, weaker justification): build with `PYAPP_SELF_COMMAND=pyapp`.**
Left at the default, `func self update` would be a working command in standalone mode and
a job-not-found error everywhere else — a phantom that exists on exactly one install path.
Renaming keeps the surface uniform across modes and keeps PyApp's battle-tested updater
reachable at `func pyapp update|remove|restore` (documented as internal). In standalone
mode `func builtin self update` re-execs `func pyapp update` and then reconciles
manifest-recorded plugins. Alternatives: `PYAPP_SELF_COMMAND=none` (loses the updater —
rejected); leaving it at `self` (the phantom above — rejected).

---

## `func builtin self` command group

```
func builtin self doctor        # Health check (extensible by plugins)
func builtin self config-info   # Runtime mode, manifest, Python ownership (--format json)
func builtin self paths         # Quick path reference
func builtin self update        # Mode-aware update with confirmation
```

**Namespace (load-bearing).** These are children of the reserved `builtin` subtree, not
top-level groups. ADR-004 §Phase A.3 reserved `builtin` as the *one* top-level segment so
that no first-party name can shadow a user's job; `register_builtin_commands` states
"There are **no top-level spellings and no deprecation aliases**"
(`_cli/builtins.py:497-514`), `BUILTIN_NAMES == frozenset({"builtin"})` (`:150`), the trie
rejects the name for jobs/groups/plugin namespaces (`_types/naming.py:418-421`), and
`tests/_cli/test_builtin_command_pilot.py:356` asserts the top level holds exactly
`BUILTIN_NAMES`. A top-level `self` group fails that test. The depth is already modelled:
`BuiltinCommand.subcommands` is one level and `builtin_subcommands()` returns the
two-level map (`_cli/builtins.py:167-178`).

### Doctor architecture (rewritten 2026-08-27)

The 2026-07-18 design placed doctor as an ordinary builtin. It cannot work there.
`cli_app`, the click group callback, runs `resolve_cli_config` → `_load_dotenv` →
`_apply_import_libs` → `auto_discover` → `FunctualizeApp(...)` → `app.refresh()` and only
then wires `ctx.obj` (`_cli/main.py:226-305`). Every builtin subcommand runs after a full
boot, so:

- "core import + version", "config resolution chain" and "execution smoke test" had to
  succeed for doctor to be *reached*. They can only ever print OK — `pitfalls.md` #1's
  shape relocated into a health check, which is worse than a dead setting: a health check
  that cannot report ill.
- "plugin loading" fails the other way. `_load_file_plugin` catches `Exception`, logs a
  warning and returns `None` (`_plugins/loader.py:761-773`), and **no failure record is
  kept** — there is no `failed_plugins`/`load_errors` attribute anywhere in `_plugins/` or
  `app/core.py`. Demonstrated: a `.functualize/plugins/` module that raises leaves
  `func builtin version` at exit 0 with only a log line. Post-boot doctor would report
  "plugins: ok". That is `pitfalls.md` #2 reaching the diagnostic layer.

**Required design:**

1. `self doctor` is intercepted **pre-boot** in `_run_cli`, beside `--version` and
   `scan_early_setting_flags` (`_cli/main.py:1700-1737`) — the repo's existing escape
   hatch for commands that must answer before the app exists.
2. Boot-shaped checks run in a **child process** (`func builtin info`, or a
   `-c` probe), so a boot that dies is a reportable *result* rather than doctor's own
   traceback.
3. Plugin-loading health is obtained by installing a log handler around the child probe,
   or — preferably — by adding a load-failure record to `PluginLoader` in a separate
   change. Until one of those exists, **the plugin check is omitted, not faked.**
4. Any check that can only be satisfied by the process doctor is already running in is
   deleted, not kept as decoration.

**Checks that survive:** Python ≥ 3.11 (critical — matches `requires-python`,
`pyproject.toml:10`), CLI extras present (warning), job discovery from CWD (info), boot
probe result from the child process (critical), manifest-vs-installed plugin
reconciliation in standalone mode (warning), stale manifest entries with a dead
`binary_path` (info), terminal capabilities (info), runtime mode + owning distribution
(info).

### `config-info` and `paths` overlap shipped commands

`func builtin config path` already prints the XDG global path, `pyproject.toml
[tool.functualize]` and `.functualize.toml` with used/found/missing status
(`_cli/builtins.py:1150-1206`). `func builtin info` already prints app state, discovered
jobs, resolved config, anchor, `import_libs` and convention dirs (`:1316-1373`). Shipping
`self paths` and `self config-info` as written recreates both — `pitfalls.md` #6, the
same answer computed in two places.

**Decision required before implementation** (flagged, not pre-empted): either fold the
three genuinely new lines — runtime mode, owning distribution, install manifest — into the
two existing commands and drop `self paths` / `self config-info` entirely, or keep them
and state in the help text exactly what they add. The first is recommended.

`--format json`, not `--json`: `builtin workflow list` establishes command-owned
`--format` as deliberately distinct from the global `--output {auto,json,ndjson,raw,none}`
(`_cli/builtins.py:651-660`, `_cli/dispatch.py:100`).

## `func builtin plugin` command group

```
func builtin plugin list
func builtin plugin install <pkg>     # mode-aware; prints the exact command + y/N confirmation
func builtin plugin uninstall <pkg>
```

`install`/`uninstall`, not `add`/`remove` — see *Terminal ownership* below.

### What counts as a plugin (corrected 2026-08-27)

The codebase reads **eight** distinct `functualize.*` entry-point groups, not one:

| Group | Read at |
|---|---|
| `functualize.plugins` | `_plugins/loader.py:326` |
| `functualize.domains` | `_plugins/domain_registry.py:156` |
| `functualize.ai_providers` / `state_providers` / `tasks_providers` | `_plugins/domain_registry.py:246` (per-domain) |
| `functualize.format_providers` | `_config/registry.py:169` |
| `functualize.remote_providers` | `_config/registry.py:193` |
| `functualize.interactivity_providers` | declared by `plugins/functualize-inline/pyproject.toml:24-25` |

The document's own worked example proves the point: **`functualize-inline` does not
register in `functualize.plugins` at all.** A `plugin list` reading only
`app.plugin_loader.loaded_plugins` (today the sole listing surface `_cli` uses —
`_cli/completions/provenance.py:154`) would not show it. `plugin list` must span all eight
groups, and must label which group each entry came from.

Second correction: `loaded_plugins` maps **plugin name → entry-point name**
(`_plugins/loader.py:251-256`), e.g. `inline`. `plugin uninstall` needs the
**distribution** name, `functualize-inline`. That mapping does not exist; build it via
`importlib.metadata` (`packages_distributions()` / `Distribution.entry_points`) and show
both names in `plugin list`.

> If a public listing API is added rather than reusing `app.plugin_loader`, an **ADR is
> mandatory** (`AGENTS.md` → Mandatory reading: "Proposing a new … public API surface").
> Reusing the existing attribute access avoids that and has precedent.

### Plugin persistence (load-bearing, re-verified)

- **Tool (uv)**: `uv tool install` is declarative. Re-demonstrated on **uv 0.11.18**,
  2026-08-27: `uv tool install pycowsay --with six` then `uv tool install pycowsay --with
  idna` printed `- six==1.17.0` and rewrote the receipt to drop it. `plugin
  install`/`uninstall` must read `uv-receipt.toml` in the tool dir and re-emit **all**
  prior requirements plus/minus the change. `uv tool --help` lists no `add`/`inject`
  subcommand, so this cannot be delegated. (`uv tool upgrade` preserves receipt-recorded
  settings, so upgrades are safe once the receipt is right.)
- **Receipt entries are not plain names.** Observed shapes:
  `{ name = "pycowsay" }`, `{ name = "idna", specifier = ">=3.0" }`,
  `{ name = "a0", url = "https://…zip" }`. The merge must reconstruct a PEP 508
  requirement string from *every* key present, and round-trip unknown keys rather than
  dropping them.
- **Standalone**: PyApp update/restore rebuilds the managed venv from the project
  requirement only, wiping `uv pip install`ed plugins. The manifest records added plugins;
  after `self update` (and on doctor runs) missing recorded plugins are reinstalled via
  bundled uv, with confirmation.

### Terminal ownership and the inline TUI (new 2026-08-27)

The `builtin` tree is mounted into the inline TUI too (`_cli/tui/job_execution.py:292-295`),
so a user can type `builtin plugin install functualize-state-sqlite` inside the shell. A
command that spawns a subprocess and asks for y/N confirmation must not run on the Textual
worker thread — that is `pitfalls.md` #7/#10 territory.

The repo already has the mechanism: declare the mutating subcommands in
`BuiltinCommand.terminal_subcommands`, which `_builtin_needs_terminal`
(`app/commands.py:306-316`) collapses to a per-node bool and `job_execution.py:412` routes
to `_run_builtin_handoff` — the same path `builtin config edit` takes.

> **Why `install`/`uninstall` and not `add`/`remove`.**
> `BUILTIN_ROOT_COMMAND.terminal_subcommands` is a **flattened** tuple across all families
> (`_cli/builtins.py:143-145`) and `needs_terminal` is `any(arg in … for arg in args)`
> (`:46-48`). Declaring `add` as terminal would make
> `get_builtin("builtin").needs_terminal(["scaffold", "add"])` return True — and
> `scaffold` has an `add` subcommand (`:96-100`). Production reads the family-scoped
> predicate, so this is latent today and exercised only by
> `tests/_cli/test_builtin_handoff.py:96-100` — but this proposal supplies the first input
> that makes it observable. Non-colliding names avoid it for free; making the root
> predicate path-aware is the alternative fix and is out of scope here.

### Entry-point snapshot invalidation (new 2026-08-27)

`_primitives/entry_points.py` takes one process-wide entry-point snapshot and documents it
as "deliberately never invalidated on its own: … **nothing functualize does installs a
distribution into the running interpreter.**" In standalone mode `plugin install` runs
`uv pip install` into the PyApp-managed venv — which *is* the running interpreter's
environment, making that sentence false.

Constraint: `plugin install` **must not** be followed by an in-process plugin read in the
same invocation. It prints the result and exits; the new plugin is active on the next
invocation. `clear_entry_point_cache()` exists but lives in `_primitives`, which `_cli` may
not import (`pyproject.toml` contract "_cli uses public API only"). Correcting the
docstring and/or exposing a public re-export is a separate change requiring an ADR.

---

## First-run detection

Manifest at `<user-config>/install.json`, resolved via `resolve_user_config_dir()`
(`app/utils.py:797`, exported at `:93`, five existing call sites — respects
`XDG_CONFIG_HOME`; do not hardcode `~/.config`). Append-only — records are never deleted,
but doctor flags entries whose `binary_path` no longer exists rather than trusting them:

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

`owning_distribution` is new (2026-08-27) and carries axis 2, so an embedded-mode record is
distinguishable from a functualize-owned one.

On first run: print a hint (`Run 'func builtin self doctor' for a health check.`), don't
block. The hint fires on the first real invocation after PyApp's bootstrap completes —
PyApp exposes no hook to run app code mid-bootstrap, and its own documentation states that
"all subsequent invocations will only check if the installation directory exists and
nothing else".

**The first-run check must stay off the warm hot path (a single `stat()`), and this needs a
structural defence, not a timing one.** `tests/perf/test_startup_budget.py` budgets only
`FunctualizeApp.__init__` phases, and those assertions are skipped under coverage and xdist
(`tests/perf/conftest.py`) — the pre-boot CLI path has no budget at all. Defend it with an
assertion that `functualize._cli.manifest` is absent from `sys.modules` after a warm second
invocation.

---

## PyApp runtime (standalone mode)

PyApp is the environment manager: bundled version-pinned Python, isolated venv for
functualize + plugins + job deps, and uv (`PYAPP_UV_ENABLED`) for installs and PEP 723
inline-dependency resolution.

### Embedding — the 2026-07-18 claim is falsified; a decision is required

The previous revision stated that building with `PYAPP_DISTRIBUTION_EMBED` and an embedded
project wheel makes "first run offline-capable and the ~3s bootstrap figure holds". **That
is not what PyApp does.** Its runtime documentation lists first-run network requirements as:
retrieving the distribution, **downloading uv or pip if not cached**, and **installing
project dependencies**. `PYAPP_DISTRIBUTION_EMBED` removes only the first.

Concretely, `functualize[cli]` pulls `pydantic`, `python-dotenv`, `jinja2`, `click`,
`rich`, `textual`, `textual[syntax]` and `textual-autocomplete` (`pyproject.toml:22-26,68-75`)
— every one fetched from PyPI at first run. And `PYAPP_UV_ENABLED=1` means uv performs
"virtual environment creation and project installation", i.e. uv is needed *during*
bootstrap, not (as previously written) "on first plugin/PEP 723 use". The two chosen
settings are not jointly offline-capable.

**Two coherent recipes. Pick one before building anything:**

| | A — network first run (PyApp default shape) | B — pre-baked distribution |
|---|---|---|
| Build | `PYAPP_DISTRIBUTION_EMBED=1` + `PYAPP_PROJECT_PATH=<wheel>` | a python-build-standalone distribution with functualize **already installed**, embedded, plus `PYAPP_SKIP_INSTALL=1` |
| First run | needs network for uv + dependencies | fully offline |
| Size | smaller binary, latency is a network lottery | larger binary, ~3s figure plausible |
| Effort | ships today | needs a distribution-baking step in CI that does not exist |

Recipe B is the shape Hatch ships and is what the "offline-capable, ~3s, 35–50MB" numbers
were implicitly describing. **Neither the size target nor the bootstrap figure can be
restated until this is decided** — both are downstream of it, and both should then be
asserted by CI on release builds rather than quoted here.

### Build configuration (was incomplete)

The previous revision named three variables. The minimum viable set is:

| Variable | Value | Why |
|---|---|---|
| `PYAPP_PROJECT_NAME` | `functualize` | required |
| `PYAPP_PROJECT_VERSION` | release version | required |
| `PYAPP_PROJECT_PATH` | path to the built wheel | **the option that actually embeds the project**; previously unnamed |
| `PYAPP_PROJECT_FEATURES` | `cli` — or `all`? | **undecided.** `.spec/ARCHITECTURE.md` documents `functualize[all]` as pulling eleven plugin packages. This single choice dominates binary size and is not made anywhere in this document |
| `PYAPP_EXEC_SPEC` | `functualize._cli.main:main` | matches `[project.scripts]` (`pyproject.toml:34-36`); previously unspecified |
| `PYAPP_SELF_COMMAND` | `pyapp` | see the collision section |
| `PYAPP_UV_ENABLED` | `1` | uv for venv creation, installs, PEP 723 |
| `PYAPP_DISTRIBUTION_EMBED` / `PYAPP_SKIP_INSTALL` | per recipe A or B above | |

### Build & distribution pipeline

- Build standalone binaries on release tag: x86_64/aarch64 × linux/macos.
- Distribution: GitHub Releases + `install.sh` + Homebrew formula.
- CI asserts the actual binary size on release builds (the number is set once recipe A or B
  is chosen, by measurement, not by estimate).

---

## User flows (abbreviated)

1. **Non-Python dev**: `curl … install.sh | sh` → `cd project && func` (PyApp bootstraps,
   manifest written, hint printed, TUI launches) → `func builtin plugin install
   functualize-state-sqlite` (confirms bundled-uv install, records plugin in manifest) →
   later `func builtin self update` delegates to `func pyapp update`, then reinstalls
   recorded plugins.
2. **uv tool user**: `uv tool install "functualize[cli]"` → `func builtin plugin install
   functualize-inline` reads `uv-receipt.toml` and confirms `uv tool install functualize
   --with functualize-inline` plus every previously recorded requirement → `func builtin
   self update` prints `uv tool upgrade functualize`.
3. **Project dev**: `uv add "functualize[cli]"` → `uv run func builtin self config-info`
   reports project mode, paths, config → `func builtin self update` prints
   `uv lock --upgrade-package functualize && uv sync`.
4. **Embedded (new)**: `func builtin scaffold init weather-app` → `uv tool install -e .` →
   `weather-app builtin self config-info` reports mode `tool (uv)`, owning distribution
   `weather-app` → `weather-app builtin self update` offers
   `uv tool upgrade weather-app`, **never** `uv tool upgrade functualize`.

---

## Implementation notes

| Module | LOC est. | Layer / dependencies |
|--------|----------|----------------------|
| `_cli/runtime.py` | ~160 | stdlib only. Exports `InstallMode` + a **pure** `detect(prefix, base_prefix, environ, argv0)` so it is unit-testable — `sys.prefix` cannot be monkeypatched via env. Docstring declares "stdlib + `_cli` siblings only", matching `_cli/data/func_settings.py:31` |
| `_cli/manifest.py` | ~110 | stdlib + `json`; path via `resolve_user_config_dir()` (`functualize.app.utils`, a public import — allowed) |
| `_cli/self_cmd.py` | ~200 | public API only (import-linter enforced). Exports `self_app: click.Group` |
| `_cli/plugin_cmd.py` | ~220 | public API + `subprocess` + `importlib.metadata`. Exports `plugin_app: click.Group`. Raised from 180: eight entry-point groups and the name→distribution mapping were not in the original estimate |

There is **no ~250-LOC module ceiling** in this repo — the only limits are a ~500-LOC
*class* ceiling and two named facades (`.spec/CONSTITUTION.md:90,166-167`). `builtins.py`
is 1376 lines and `main.py` 1935.

**`_cli/builtins.py` is not converted to a package.** The previous revision called it a
"724-line module" whose commands would "move unchanged" into `_cli/builtins/`. It is now
**1376 lines**, and `register_builtin_commands` spans `:495-1376` — one 882-line function
containing 74 nested `def`/decorator sites, all closures over local groups. Moving them is
a refactor, not a move.

It is also unnecessary. `scaffold` already lives outside the module and mounts in two lines:

```python
# _cli/builtins.py:1301-1304
from functualize._cli.scaffold.cli import scaffold_app
_mount(builtin_app, scaffold_app, "scaffold")
```

Follow that. `self_cmd.py` and `plugin_cmd.py` are `_cli` siblings, mounted the same way,
with two new `BuiltinCommand` entries appended to `BUILTIN_COMMANDS`. Consequences: **no
package conversion, no registry-surface change, no cache-format bump.**

`tests/_cli/test_builtin_command_pilot.py::test_registry_matches_the_real_click_commands`
derives its expectations from `BUILTIN_COMMANDS` and walks both levels (`:332-373`), so it
covers the new commands **without being edited** — correcting the previous revision's claim
that it must be extended.

### Routing

`func builtin …` is classified `Mode.BUILTIN` in `detect_mode` and dispatched through the
click group (`_cli/dispatch.py:249-257`) — **not** through `_dispatch_group`
(`_cli/main.py:881`, moved from `:774`), which handles job groups. That branch carries a
live `# TRANSITIONAL(cli-shell-convergence §2.B.1)` marker noting the planned fold of
`builtin` into the trie is "deferred and unscheduled". This work must not depend on that
fold, and must not silently complete it.

`_cli/runtime.py`'s stdlib-only constraint is right, but it does not preserve "the
warm-boot 0-imports invariant" — that test is about `importlib.import_module` on *job*
modules (`tests/discovery/test_warm_boot_zero_imports_property.py`). The guarantee at stake
here is the pre-boot routing budget and the single-module-import guardrail
(`tests/cli/test_lazy_dispatch_single_import.py`). `_cli/main.py:1684-1688` uses the same
loose shorthand, so this is a repo-wide naming slip rather than a defect in this document —
worth knowing because it means no existing test actually guards the pre-boot path (see
`A9`).

### Order

1. `InstallMode` detection (both axes) + manifest + first-run wiring.
2. `builtin self doctor` (pre-boot interception + child-process probe) and the
   `paths`/`config-info` fold-or-justify decision.
3. `builtin plugin` (eight groups, name→distribution mapping, receipt merge) +
   `builtin self update` (mode-aware, manifest reconciliation).
4. PyApp CI pipeline — **blocked on the recipe A/B decision** and the
   `PYAPP_PROJECT_FEATURES` decision — plus `install.sh` and the Homebrew formula.

`_cli/` dogfoods the public API throughout.

---

## Acceptance criteria and test tiers

Tiers per `.spec/TESTING.md`.

| # | Criterion | Tier |
|---|---|---|
| A1 | `detect()` returns the right `InstallMode` for each synthetic `(prefix, base_prefix, environ, argv0)` — asserting the exact mode, never `!= wrong` (`pitfalls.md` #15) | unit |
| A2 | Axis 2 returns the consumer distribution for a scaffolded app's console script | unit |
| A3 | Receipt merge round-trips every observed key shape (`name`, `name+specifier`, `name+url`) and preserves unknown keys | property (`_properties.py`) |
| A4 | `func builtin self doctor` on a project whose `.functualize/plugins/` module raises **reports the failure** | CLI integration (`cli_run` + `project_tree`) |
| A5 | `func builtin self doctor` still produces a report when the app cannot boot | CLI integration |
| A6 | `func builtin plugin install X` in `unknown` mode prints guidance, executes nothing, exits `ExitCode.REFUSED` | CLI integration, `cli_run(env={"FUNCTUALIZE_RUNTIME": "unknown"})` |
| A7 | `func builtin plugin list` shows an `interactivity_providers` entry with both its plugin name and its distribution name | CLI integration |
| A8 | Manifest written under `xdg_dirs.functualize_config`; hint printed on first invocation only | CLI integration |
| A9 | `functualize._cli.manifest` absent from `sys.modules` after a warm second invocation | CLI integration (structural stand-in for the absent pre-boot budget) |
| A10 | `builtin plugin install` requests a terminal handoff from the inline TUI rather than running on the worker | TUI Pilot |
| A11 | Registry mirrors the real click tree | already covered — no new test |

> `tests/conftest.py:126-142` strips `FUNCTUALIZE_*` and `XDG_*` autouse, so every test
> above must pass `FUNCTUALIZE_RUNTIME` explicitly via `cli_run(env=…)`. Per
> `.spec/CONSTITUTION.md` → Acceptance Gates, run each criterion at authoring time and
> make the task's file scope equal its actual hit set.

### Wiring paths to name at close

Per `contributor/guides/wiring-discipline.md` §2 and §5, name every production path — cold
**and** warm — and sabotage the wire:

- **cold** — `_run_cli` → `detect_mode` → `Mode.BUILTIN` → `cli_app` → `builtin` group →
  `self`/`plugin`
- **warm** — the same route over a populated `cache.json`
- **TUI** — `job_execution.run_builtin` → `_node_needs_terminal` → `_run_builtin_handoff`
- **consumer app** — `CliAdapter.__call__` → `register_builtin_commands`
  (`app/adapters/cli.py:627-634`)
- **pre-boot** — `_run_cli`'s `--version`-adjacent interception for `self doctor` and the
  first-run hint

Commit first, then sabotage the `_mount(builtin_app, self_app, "self")` call and confirm a
test fails (`.spec/CONSTITUTION.md` → Commit before sabotaging).

### Documentation to update at close

`contributor/reference/code-map.md:176-184` and
`contributor/architecture/codemaps/modules.md:102-104` both enumerate `_cli/` modules and
neither would fail `tests/test_contributor_docs.py` if left stale — it only checks that
referenced paths *exist*. Update both by hand. README install docs gain the standalone
row only once recipe A/B is decided.

---

## Scrutiny vs current codebase

Full report: `.spec/scrutiny-reports/standalone-distribution-2026-08-27.md` (gitignored
working notes). Every claim that moved, and its correction:

| Claim as written | Verdict | Correction |
|---|---|---|
| `func self` / `func plugin` are top-level groups | **falsified, blocking** | ADR-004 reserved `builtin` as the one top-level segment; commands are `func builtin self …` / `func builtin plugin …` (`_cli/builtins.py:497-514,150`; `tests/_cli/test_builtin_command_pilot.py:356`) |
| PyApp `self` collision is blocking | **premise removed** | Under `func builtin self`, PyApp never sees `self`. `PYAPP_SELF_COMMAND=pyapp` retained for cross-mode uniformity, not collision avoidance |
| Doctor checks core import / config chain / execution / plugin loading | **falsified, load-bearing** | All four run after a full boot (`_cli/main.py:226-305`); three can only report OK, and plugin failures are swallowed with no record (`_plugins/loader.py:761-773`). Doctor re-architected pre-boot + child probe |
| Embedding ⇒ offline first run, ~3s, 35–50MB | **falsified, load-bearing** | PyApp still fetches uv and every project dependency at first run. Two recipes offered; size and latency figures withdrawn pending the choice |
| Three audiences | **falsified, load-bearing** | Fourth: consumer apps built on functualize, which get the whole `builtin` tree (`app/adapters/cli.py:627-634`). Detection gains an owning-distribution axis |
| "plugin" = one entry-point group | **falsified, load-bearing** | Eight groups; `functualize-inline` — the document's own example — is in `interactivity_providers`, not `plugins` |
| `builtins.py` is a 724-line module | **drifted** | 1376 lines |
| `builtins.py` converts to a package, commands "move unchanged" | **falsified** | `register_builtin_commands` is one 882-line function of 74 closures. Follow the `scaffold` mounting idiom instead; no conversion, no cache bump |
| "the registry-mirror test is extended" | **drifted** | It derives from `BUILTIN_COMMANDS` and needs no edit (`tests/_cli/test_builtin_command_pilot.py:332-373`) |
| Reuse `_dispatch_group` (`_cli/main.py:774`) | **drifted + wrong route** | Now `:881`; `func builtin …` routes via `Mode.BUILTIN` through the click group (`_cli/dispatch.py:249-257`), not group dispatch |
| `resolve_user_config_dir()` in `app/utils.py` | **confirmed, line drifted** | `app/utils.py:797` |
| "if remove-typer lands first, author click-native" | **moot** | ADR-004; zero typer imports in `src/` |
| Links to persistent-process / kernel-persistent-process-api / shell-and-task-runner | **stale** | Files absent from the repo; daemon marked out of scope; third superseded by ADR-005 |
| `func self daemon *` contingent | **stale** | `.spec/STATUS.md`: the daemon "has no spec … no unblocking event". Removed |
| `_cli/runtime.py` preserves "warm-boot 0-imports" | **mislabelled (repo-wide)** | Constraint right, invariant misnamed — that test is about job-module imports. `_cli/main.py:1684-1688` uses the same shorthand, so this is the repo's loose usage, not the document's error |
| `--json` | **drifted** | `--format json` (`_cli/builtins.py:651-660`) |
| `sys.prefix` ladder, uv tools dir | **confirmed by experiment** | uv 0.11.18: `VIRTUAL_ENV: None`, `sys.prefix` under `~/.local/share/uv/tools/<tool>` |
| Receipt merge is required | **confirmed by experiment** | uv 0.11.18 second install printed `- six==1.17.0`; no `uv tool add`/`inject` exists |
| `PYAPP=1`, `PYAPP_COMMAND_NAME`, `PYAPP_SELF_COMMAND` default `self` | **confirmed** | PyApp runtime + CLI config docs |
| Manifest append-only, doctor flags dead `binary_path` | **confirmed** | Retained; gains `owning_distribution` |
| Nothing of this exists yet | **confirmed** | grep across `src/`, `tests/`, `docs/` |
| ~200 / ~180 LOC estimates vs a "250-LOC ceiling" | **no such rule** | Only a ~500-LOC class ceiling exists; estimates adjusted for scope, not for a ceiling |
| pipx `sys.prefix` signal | **unverified** | No pipx on the scrutiny host. Settle it the way uv was settled: install a tool with pipx and read `sys.prefix` from its shim |
| Nuitka / PyInstaller drawbacks | **unverified, not re-litigated** | No live evidence against the PyApp choice |
