# Shape Intent: Builtins as Jobs — closing the last job/builtin split

**Status: specified, not yet implemented — and deliberately not yet *decided*.**
**Date: 2026-09-03** (opened from a side-question during the standalone-distribution
re-audit; verified against HEAD `39a0be2`)
**Scope: `_cli/builtins.py` and the discovery pipeline seam. No new layer, no new public
API, no kernel change. A subset conversion, not a rewrite.**

Ask whether first-party commands should be implemented as functualize **jobs** rather than
click callbacks — and if so, which ones. ADR-004 unified how jobs and builtins are
*consumed*; it left how they are *implemented* split in two. This document asks whether that
remainder is load-bearing or residual.

**This intent does not recommend converting everything.** Its position is that the split is
right for boot-critical commands and wrong for leaf ones, and that nobody has ever written
down which is which.

---

## Why this exists

Two independent problems in the same week both traced back to the same root:

1. **`skills install` corrupts the inline TUI** — it spawns `npx skills add` (interactive)
   but the `skills` family declares no `terminal_subcommands`, so the TUI runs it on a
   worker instead of handing over the terminal.
2. **`plugin install` cannot safely declare itself terminal** — the root
   `needs_terminal` predicate matches a bare name across *every* family, so declaring
   `install` would also match `skills install`. See
   [standalone-distribution.md](standalone-distribution.md) §4.1, prerequisite **P1**.

Both exist because terminal ownership for a builtin is declared **on a registry entry, by
family, as a string** — and can therefore be forgotten (problem 1) or collide (problem 2).
For a job the same fact is declared **on the function, by signature**, and can do neither.

That is the argument in one line: *builtins re-implement, less safely, a declaration jobs
already get for free.*

---

## The decision that was never made

**There is no ADR, no rejected-alternatives note, and no comment anywhere in `.spec/` or
`contributor/` addressing why builtins are not jobs.** Verified 2026-09-03 by grep across
both trees. The split is an artifact of ordering — builtins predate the job-namespace work —
not a ruling.

What ADR-004 *did* decide is narrower than it appears. It converged the **consumption**
layer only:

> The shell composes **providers** into one tree, which is what finally removes the
> "builtins are a separate hidden namespace" special-casing: a job subtree and the reserved
> `builtin` subtree arrive as the same node type, from `JobCommandProvider` and
> `ClickCommandProvider` respectively.
> — `_types/commands.py:14-17`

> Nothing here distinguishes a job from a builtin; that is the point.
> — `_types/commands.py:39-41`

So everything downstream of `CommandNode` already treats them identically. Two providers
paper over two mechanisms. This intent asks whether the second mechanism earns its keep.

---

## 1. The seams already exist

The striking finding of the 2026-09-03 verification pass: **almost nothing would need
building.** Every mechanism a builtin-as-job needs is already in production for other
reasons.

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `SEAM.1` | The consumption layer already erases the distinction, so converting a command changes no consumer | **PASS** — `CommandNode` is a `Protocol` with two implementations (`_types/commands.py:35-100`); `build_command_tree` composes both providers (`app/commands.py:368`) |
| `SEAM.2` | The `JobProvider` protocol anticipates non-filesystem job sources | **PASS** — its docstring names the sources: "filesystem scan, entry points, **static definitions**" (`_types/protocols.py:41-55`) |
| `SEAM.3` | A zero-I/O provider over pre-imported callables exists and is wired at boot | **PASS** — `StaticProvider`, "Wraps pre-imported callables as JobDescriptors with zero I/O" (`_discovery/providers.py:651-662`), wired at `_app/boot.py:243-244` when `app._job_sources.functions` is non-empty |
| `SEAM.4` | Registering an extra provider is a **public** operation, needing no new API (so no ADR under `AGENTS.md`'s mandatory-reading rule) | **PASS** — `FunctualizeApp.add_job_provider(provider, transforms=None)` (`app/core.py:911-918`) |
| `SEAM.5` | Terminal ownership for a job is declared per-function by signature, not per-family by string | **PASS** — a bare `tty: TTY` parameter sets `requires_tty`; matched by type *name* so no capability import is needed (`_discovery/providers.py:255-290`) |
| `SEAM.6` | `requires_tty` is a HARD requirement that forces the exclusive surface and cannot be overridden by a preference | **PASS** — `resolve_surface` returns `RenderSurface.EXCLUSIVE` before consulting hint, setting or default (`_cli/orchestrator.py:33-58`) |
| `SEAM.7` | Jobs can be registered on the engine programmatically | **PASS** — `JobExecutionEngine.register_job(entry)` (`_engine/executor.py:224`), already called from three boot paths (`_app/boot.py:1023,1117`; `_app/impl.py:718`) |
| `SEAM.8` | A converted command keeps its `func builtin …` spelling, because the reserved subtree is a *namespace* fact, not an implementation fact | **GAP** — `BUILTIN_SEGMENT` is reserved against jobs, groups and plugin namespaces (`_types/naming.py:172-175,417-421`). A first-party job mounting *into* it is not contemplated by that code and would need an explicit, first-party-only path |

> **`SEAM.8` is the one real piece of new mechanism**, and it is also the one place this
> could go wrong quietly. The reservation exists so a *user* job cannot claim `builtin`. A
> first-party job mounting there must not widen that hole — the check must stay "rejects
> everything except this one internal provider", never "rejects everything except jobs that
> ask nicely".

## 2. Which builtins could convert — the taxonomy nobody wrote down

Classification by what the command needs in order to answer. Verified 2026-09-03 by
scanning each command body for `ctx.obj` / app access.

| Class | Families | Why it cannot convert (or can) |
|---|---|---|
| **Pre-boot** | `version` | Answered before an app exists (`_cli/main.py:1707-1751`). A job cannot answer pre-boot by definition. **Never converts.** |
| **Bootstrap-circular** | `cache`, `config` | `cache clear` would need the discovery cache working in order to find the command that clears it; `config path` must diagnose config resolution that job loading depends on. **Should not convert.** |
| **App-introspective** | `info`, `why`, `env`, `parallel`, `history` | These read app state as their *subject*. Converting is possible but pointless — they would be jobs that exist to describe jobs. **No benefit.** |
| **State-backed** | `state`, `workflow`, `domains` | Need a booted app but are not circular. **Convertible, low value.** |
| **Leaf** | **`skills`, `scaffold`** | Need **no app at all** — verified: `_cli/scaffold/cli.py` contains zero `ctx.obj` reads, and `skills path/list/materialize/install` read only `resolve_skills_dir()` and the filesystem. **The candidates.** |

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `TAX.1` | The boot-critical set is named and justified, not assumed | **GAP** — no document classifies builtins this way |
| `TAX.2` | `skills` and `scaffold` are app-independent | **PASS (verified 2026-09-03)** — `grep -c "ctx.obj" _cli/scaffold/cli.py` → 0; `skills_install` reads no `ctx.obj` |
| `TAX.3` | "Builtins must work when the app cannot boot" is **not** a current property, so it cannot be cited as the reason for the split | **PASS, and it falsifies the intuitive defence** — every builtin except `--version` runs *after* a full boot through the `cli_app` callback (`_cli/main.py:160-330`). This is the same finding that forced the pre-boot doctor design in [standalone-distribution.md](standalone-distribution.md) `DOC.1` |

## 3. What conversion would dissolve

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `DISS.1` | A converted `skills install` declares `tty: TTY` and needs no registry entry, so the defect cannot recur by omission | **GAP** — today the fact lives in `terminal_subcommands` on a registry row, and `skills` declares none: `get_builtin('skills').needs_terminal(['install'])` is `False` while the body runs `subprocess.call(["npx", "skills", "add", …])` |
| `DISS.2` | Prerequisite **P1** becomes unnecessary *for converted commands*, because per-function declaration has no cross-family aggregate to collide in | **GAP** — P1 is still required for the commands that stay click, so this dissolves the class of bug, not the specific fix |
| `DISS.3` | Converted commands gain DI — `Shell` (including `pty=True` and `Responder` watchers), `Stdout`, `State` — which a click callback cannot reach | **GAP** — `_make_shell(ctx)` needs `ctx.engine` and `ctx.context` (`_engine/capabilities/shell.py:1102-1120`), and `_cli` may import the public `functualize.job.Shell` protocol but not that wiring |

## 4. What it would cost — the honest side

| Assertion | Expected behavior | Verdict |
|---|---|---|
| `COST.1` | Converted commands appear in `app.get_jobs()`, therefore in `builtin info jobs`, therefore in a **consumer app's** job listing | **GAP, and this is the strongest objection** — a scaffolded weather-app would list framework internals among its own jobs unless the provider is filtered out of listings, which re-introduces a distinction the conversion was meant to remove |
| `COST.2` | Converted commands become MCP tools | **GAP, double-edged** — the MCP plugin enumerates `app.get_jobs()` in six places (`plugins/functualize-mcp/src/functualize_mcp/_tools.py:124,452`; `_plugin.py:337,378`; `_server.py:99`). `skills install` as an agent-callable tool may be desirable; `cache clear` is not |
| `COST.3` | Conversion adds no measurable boot cost | **GAP, plausible but unmeasured** — `StaticProvider` is documented "zero I/O" and the pipeline already runs, but the 500ms total-boot budget (`tests/perf/test_startup_budget.py`) must be re-run, not assumed |
| `COST.4` | The layer direction stays legal — `_cli` may import public API only | **GAP** — jobs are a user-space construct (`functualize.job`); a builtin-as-job defined in `_cli` and consumed by the engine needs its import arrows checked against the `pyproject.toml` import-linter contracts before anything is written |
| `COST.5` | No cache-format bump — a static provider's descriptors are not written to `cache.json` | **GAP, needs verification** — directory discovery owns the cache projection (`_types/protocols.py:47-54`: a hand-built descriptor "leaves it `None` and has no public way to set it"), which suggests no bump, but the fingerprint path was not traced |

## 5. Open decisions

| # | Question | Blocks |
|---|---|---|
| **B1** | Convert anything at all, or record the split as deliberate and close this? | everything |
| **B2** | If yes: leaf-only (`skills`, `scaffold`), or leaf + state-backed? | scope |
| **B3** | How are converted commands kept out of a consumer app's job listing and out of MCP — a provider flag, a descriptor marker, or an explicit allowlist? | `COST.1`, `COST.2` |
| **B4** | Does `builtin` stay the mount point (`SEAM.8`), and how is first-party-only enforced without weakening the user-facing reservation? | `SEAM.8` |

**B3 is the one that decides the whole thing.** If keeping framework jobs out of user
listings requires a "this is really a builtin" marker on the descriptor, the conversion has
recreated the distinction one layer down and bought only the `requires_tty` win — which
prerequisite **P1** already delivers for a fraction of the cost.

---

## Relationship to standalone-distribution

**These are independent and must not be merged.**

- [standalone-distribution.md](standalone-distribution.md) needs **P1** (path-aware
  `needs_terminal`) regardless of this intent's outcome, because `version`, `config` and
  `cache` are never converting and will always need a correct family predicate.
- The `skills install` defect is fixed today by one line
  (`terminal_subcommands=("install",)`), and that fix should land on its own schedule. If
  `skills` later converts, the line is deleted along with the registry entry.
- If B1 resolves to "convert", `plugin install`/`uninstall` from
  standalone-distribution §4 would be a **natural first customer** — it is a leaf command
  that shells out and wants the terminal. But standalone-distribution must not wait for it.

---

## Test tiers

Per `.spec/TESTING.md`. Only meaningful if B1 resolves to "convert".

| # | Criterion | Tier |
|---|---|---|
| U1 | A converted command declaring `tty: TTY` resolves to `RenderSurface.EXCLUSIVE` through `resolve_surface` | unit |
| U2 | The static builtin provider yields descriptors with zero filesystem access — assert the call count, not a timing | unit |
| I1 | `func builtin skills install` behaves identically before and after conversion from a real terminal — the `subprocess.call` path is unchanged | CLI integration |
| I2 | A converted command does **not** appear in a consumer app's `builtin info jobs` output | CLI integration (`project_tree` + `cli_run`) |
| I3 | A converted command is not exposed as an MCP tool unless explicitly opted in | CLI integration |
| P1t | Boot budget unchanged: `tests/perf/test_startup_budget.py` passes with the provider wired | existing suite, re-run |
| T1 | `builtin skills install` from the inline TUI requests handoff rather than running on the worker — **valid before and after conversion**, so write it now | TUI Pilot |
| R1 | The `builtin` reservation still rejects a *user* job claiming the segment (`_types/naming.py:417-421`) | unit, existing behavior |

> `T1` and `R1` are worth writing **regardless of B1**: `T1` pins the `skills install` bug
> fix, and `R1` guards the reservation `SEAM.8` would touch.

### Wiring paths to name at close

Per `contributor/guides/wiring-discipline.md` §2 and §5:

- **cold** — `_run_cli` → `detect_mode` → `Mode.BUILTIN` → the converted command's node
- **provider** — `FunctualizeApp.__init__` → `add_job_provider(BuiltinJobProvider)` →
  `ResolutionPipeline` → `get_jobs()`
- **TUI** — `job_execution.run_builtin` → `_node_needs_terminal` → `_run_builtin_handoff`
- **consumer app** — `CliAdapter.__call__` → `register_builtins=True` → the same tree

Sabotage the `add_job_provider` call and confirm `U2` fails.

---

## Verification checklist for the implementing agent

Audit before writing anything — this document's PASSes are the load-bearing half:

- `SEAM.1–8`: `src/functualize/_types/commands.py:14-17,35-100`;
  `src/functualize/_types/protocols.py:41-55`;
  `src/functualize/_discovery/providers.py:255-290,651-662`;
  `src/functualize/app/core.py:911-918`; `src/functualize/_engine/executor.py:224`;
  `src/functualize/_app/boot.py:243-244`; `src/functualize/_cli/orchestrator.py:33-58`;
  `src/functualize/_types/naming.py:172-175,417-421`
- `TAX.1–3`: `src/functualize/_cli/builtins.py:55-146` (the registry);
  `src/functualize/_cli/main.py:160-330,1707-1751`;
  `src/functualize/_cli/scaffold/cli.py`
- `COST.1–5`: `plugins/functualize-mcp/src/functualize_mcp/`;
  `tests/perf/test_startup_budget.py`; `pyproject.toml` import-linter contracts
- Cross-check `P1` and the `skills install` note in
  [standalone-distribution.md](standalone-distribution.md) §4.1 before touching
  `terminal_subcommands` anywhere

**Report format**: `PASS` (code already satisfies) or `GAP` (exact `file:line` + proposed
change). **Resolve B1 before any other work** — a "no" closes this document with an ADR
recording *why*, which is itself the valuable outcome.
