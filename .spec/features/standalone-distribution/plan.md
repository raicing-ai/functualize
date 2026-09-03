# Plan: Standalone Distribution & Self-Management

**Feature**: `standalone-distribution`
**Date**: 2026-09-03
**Inputs**: `spec.md` (36 acceptance criteria), `contracts.md`, `research.md`
**Baseline**: HEAD `39a0be2`

---

## Approach

Four new `_cli` modules, three touched, one new CI stage. Nothing below the `_cli` layer
changes — no kernel edit, no new public API, no cache-format bump.

The shape is set by one constraint and one decision:

- **The layer contract** decides how every new module reaches the rest of the system.
- **O1 (pre-baked binary)** makes §5 a *CI* problem, not a Python problem. No `src/` code
  knows the binary was baked.

## The binding layer constraint

`pyproject.toml`, contract *"_cli uses public API only"* — `functualize._cli` may not import
any of:

```
_types  _primitives  _events  _discovery  _config  _engine  _plugins  _app
```

Three consequences that shape the design, each with its permitted route:

| Need | Forbidden route | Permitted route |
|---|---|---|
| `ExitCode.REFUSED` | `_types.exit_codes` | `functualize.app.utils` — already how `builtins.py:19` imports it |
| Manifest location | re-deriving `~/.config` | `resolve_user_config_dir()` from `functualize.app.utils` |
| Entry-point enumeration for `plugin list` | `_primitives.entry_points` | **stdlib `importlib.metadata` directly** |

That third row is load-bearing. `_primitives/entry_points.py` holds a process-wide snapshot
and a `clear_entry_point_cache()`, but `_cli` may not import it. `plugin_cmd.py` therefore
reads `importlib.metadata` itself — which is also why **`plugin install` must not read the
extension list back in the same process** (`spec.md` B5): the snapshot it would consult is
the one taken at start.

For plugin *names*, `app.plugin_loader.loaded_plugins` is reached by **attribute access on
the public app object**, which the contract permits and `_cli/completions/provenance.py:154`
already does.

## Modules

| Module | Status | Role | May import |
|---|---|---|---|
| `_cli/runtime.py` | **new** | Detection. Pure function over supplied inputs | stdlib only — docstring declares it, matching `_cli/data/func_settings.py:31` |
| `_cli/manifest.py` | **new** | Read/write `install.json` | stdlib + `resolve_user_config_dir` |
| `_cli/self_cmd.py` | **new** | `self doctor/update/install/python/uv`. Exports a click group | public API + `subprocess` |
| `_cli/plugin_cmd.py` | **new** | `plugin list/install/uninstall`. Exports a click group | public API + `subprocess` + `importlib.metadata` |
| `_cli/builtins.py` | modify | P1, P2, two registry entries, two mounts, install lines in `info` | — |
| `_cli/info.py` | modify | `full_report` gains the `install` block | — |
| `_cli/main.py` | modify | Pre-boot doctor intercept, first-run hint | — |

**`builtins.py` is not converted to a package.** `register_builtin_commands` spans
`:556-1801` — a 1246-line function of 103 nested closures. `self_cmd`/`plugin_cmd` mount in
two lines each, following `scaffold` (`:1526`) and `skills` (`:1521`).

**`builtins.py` is touched by five separate tasks and is the main serialization pressure in
the wave graph.**

## Per-section approach

### §1 Detection — `_cli/runtime.py`

A pure `detect(prefix, base_prefix, environ, argv0)`. Purity is not stylistic: `sys.prefix`
cannot be set by environment, so an impure function can only ever be tested in the one mode
the suite runs under (`spec.md` AC4).

Ladder, first match wins, **cheap signals before filesystem ones**:

1. `FUNCTUALIZE_RUNTIME` override
2. `PYAPP` / `PYAPP_COMMAND_NAME` → standalone
3. prefix under the uv tools dir → `tool_uv`
4. prefix contains `pipx/venvs` → `tool_pipx`
5. **nearby `pyproject.toml` declaring functualize → `project`** ← the only filesystem rung
6. `prefix == base_prefix` → `tool_pip`
7. otherwise → `unknown`

Rung 5 is a directory walk plus a TOML parse — the shape of `contributor/reference/pitfalls.md`
#16, where a syscall on a hot path cost 63% of boot. It is safe **only** because rungs 1–4
answer first in every non-project case. Bound the walk at the anchor `resolve_cli_config`
already uses; never move a filesystem rung above a pure one.

Axis 2 (owning distribution) reverse-maps `argv0`'s basename through `importlib.metadata`.

### §2 Manifest — `_cli/manifest.py`

Append-only JSON at `resolve_user_config_dir() / "install.json"`.

The warm-path requirement (AC9) is **structural, not timed**: there is no pre-boot wall-clock
budget — the perf budgets cover `FunctualizeApp.__init__` only and are skipped under coverage
and xdist (`tests/conftest.py:129-148`). So the gate is `functualize._cli.manifest` absent
from `sys.modules` after a warm second invocation, which means the first-run check must be a
`stat()` in `main.py` that imports the module only on the miss path.

### §3 `self` — `_cli/self_cmd.py` + pre-boot intercept

**Doctor must run before the app boots.** `cli_app` unconditionally runs
`resolve_cli_config` → `_load_dotenv` → `_apply_import_libs` → `auto_discover` →
`FunctualizeApp(...)` → `app.refresh()` before wiring `ctx.obj` (`_cli/main.py:160-330`), so a
doctor mounted as an ordinary builtin could only ever report success for anything
boot-shaped, and would never be *reached* when boot fails.

Intercept in `_run_cli` beside `--version` (`_cli/main.py:1694-1760`), and run boot-shaped
checks **in a child process** so a boot that dies is a reportable result rather than doctor's
own traceback.

**The plugin-loading check is omitted, not faked.** `_load_file_plugin` catches `Exception`,
logs, returns `None`, and records nothing (`_plugins/loader.py:748,761-773`). Until a failure
record exists, doctor cannot observe it (AC12).

**`self install` / `self python` / `self uv` — reaching the owned environment.** A job runs
under whichever interpreter runs `func`, and in a project the user's `PATH` already selects
that project's functualize (`uv run func`, an activated venv, `mise` putting `.venv/bin`
first). Nothing needs to intervene there. The gap is only a deliberately-invoked binary,
whose bundle holds functualize plus the first-party plugins and nothing else.

`self install` reuses `plugin install`'s mechanism and differs in bookkeeping — recorded
under `packages`, absent from `plugin list`, restored by `self update` in the same pass as
plugins. `self python` / `self uv` print one absolute path each so anything else stays
possible by composition.

**Delegating into a project venv was considered and rejected** (`research.md` §1.8): it would
override a deliberate choice, and it cannot be unconditional, because today's shipped
`BUILTIN_COMMANDS` has no `self` — a binary delegating `self doctor` into a 0.1.2 project
would answer "no such command" for a command the user can see.

`info` gains three fields rather than two new commands (O3). The line is labelled
**`Install mode:`** — `builtin info` already prints `Mode:` for state storage, whose value is
already `standalone` meaning something else entirely (`research.md` §1.6).

### §4 `plugin` — `_cli/plugin_cmd.py`

`plugin list` spans **eight** entry-point groups. `functualize-inline` registers only under
`functualize.interactivity_providers`, so a listing that reads `loaded_plugins` alone would
omit the document's own canonical example.

Receipt-merge is mandatory in `tool_uv` mode: `uv tool install` is declarative and drops
prior `--with` entries, and `uv tool` offers no `add`/`inject` to delegate to. The merge must
reconstruct PEP 508 requirements from **every** key present (`name`, `specifier`, `url`, …),
not just `name`, and round-trip unknown keys.

**Gated on P1** — see below.

### §5 Binary — CI only

Recipe B needs a stage that does not exist: per platform, bake a python-build-standalone
distribution with `functualize[all]` already installed, then embed *that* artifact.

`release.yml` today is `verify-ci → build → publish → github-release`. Two jobs are inserted
after `build`: **bake** (matrix over platform/arch) and **binaries** (runs PyApp over the
baked artifacts, measures size, attaches to the release).

No `src/` change. The wheel continues to publish unchanged.

### P1 — path-aware terminal ownership

`BUILTIN_ROOT_COMMAND.terminal_subcommands` is flattened across families (`:167-170`) and
`needs_terminal` matches any argument against the whole bag (`:47-48`), so a name declared by
one family matches in every family.

Resolve the family before matching. `get_builtin` already answers for both the root and each
family (`:219-229`), so no new state is needed.

**Must not widen the node contract.** `_types/commands.py:52-70` fixes
`CommandNode.needs_terminal` as a plain bool *because* `BuiltinCommand.needs_terminal` is a
predicate over args, with the tree calling `needs_terminal([segment])` per child. P1 changes
how the **root** answers; the per-family predicate and the node contract stay as they are.

### P2 — `skills install`

One registry line. **The `subprocess.call` is correct and is not the defect** — it inherits
fd 0/1/2, which is what makes `npx skills add` interactive from a terminal today.

Declaring `terminal_subcommands=("install",)` routes the inline shell through
`_run_builtin_handoff` → `request_handoff` → `App.exit()` onto the direct stdout surface,
where the existing call already works.

**Ordered after P1.** Under the flat predicate, declaring `install` terminal would match it
in every family.

## Risks

| Risk | Mitigation |
|---|---|
| Rung 5 lands on the hot path | Ladder order is binding; AC9 asserts structurally |
| P1 regresses existing handoff | Four existing assertions pin the contract (`test_builtin_handoff.py:100,109-110`; `test_click_command_provider.py:94,97`). Run them **before** editing |
| P2 "fixed" by changing the subprocess call | AC29 pins terminal behavior unchanged |
| Doctor decorates | AC12 is review-verified; it has no automated form and must not get a fake one |
| `plugin install` tests mutate the developer's real install | In-process tests exercise refusal and print-only paths; real installs run in containers, out of pytest |
| Baking stage has no prior art | Its own wave, last, independent of every `src/` task |
| Skills/docs teach a flag or command that changed | `RAD.4`-style check before close; `evals/` measures the skills |

## Sequencing

Waves are forced more by **file disjointness than by logic** — five tasks touch
`builtins.py`. Logical dependencies are only: P1 → P2, P1 → `plugin` declares terminal,
`runtime.py`+`manifest.py` → `self_cmd`/`plugin_cmd` → their registry entries.

§5 and the docs depend on nothing in `src/` and could run at any point; they are placed last
so a failure there cannot block shippable behavior.
