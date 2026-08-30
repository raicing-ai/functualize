# The surface boundary — what `func` owns, and where the common path starts

There are two entry points into this framework, and they are **not** two views of
one program:

```
func deploy --env prod              ./main.py deploy --env prod
```

The first has a whole layer the second does not. That layer is legitimate — it
is what makes `func` usable over loose scripts anywhere on the filesystem — but
it means "the CLI" is an ambiguous phrase, and a feature added to one surface is
not thereby added to the other.

**This page exists so that the question "does this need to work on both?" is
answered by design rather than by a bug report.** It has a rule (§4), and the
rule has already been applied once: `--scope-id` was a `func`-only flag, so a
`@workflow` with a `Gate` on a `FunctualizeApp` blocked at exit 5 forever and
the deposited input was never read.

---

## 1. The map

```
  ┌───────────────────────────── func ──────────────────────────────┐
  │  PRE-BOOT — exists only here. No app, no DI, no job module.     │
  │                                                                  │
  │  _cli/main.py::main → _run_cli                                   │
  │    · --version fast path      reads distribution metadata; does  │
  │                               not import functualize             │
  │    · _extract_global_options  pre-command globals (dispatch.py)  │
  │    · auto_discover(cwd)       anchor, merged_config, job dirs    │
  │    · routing names            cache-first, else AST scan         │
  │    · _extract_aliases         alias map from merged_config       │
  │    · detect_mode              SINGLE_FILE│BUILTIN│JOB│GROUP│     │
  │                               BARE│UNKNOWN                       │
  │    · _handle_* / _dispatch_group                                 │
  │        renders listings, unknown-command errors, group help      │
  └────────────────────────────────┬─────────────────────────────────┘
                                   │  constructs
   ./main.py ─────────────────┐    │
   (a user's own script)      │    │
                              ▼    ▼
              ╔═══════════════════════════════════════════╗
              ║  FunctualizeApp(...)   ← THE COMMON PATH   ║
              ║  starts here, and everything below is      ║
              ║  shared by every surface                   ║
              ╚═══════════════════════╤═══════════════════╝
                                      │
                    boot_static  ◄─────┴─────►  boot_standard
                    (fully explicit)            (discovery, plugins,
                                                 ResolutionChain)
                                      │
                                      ▼
                        adapter(app)   — CliAdapter, TuiAdapter,
                                         HTTP, Lambda, MCP
                                      │
                                      ▼
                    JobExecutionEngine.execute(...)
                                      │
                                      ▼
                                 JobResult
                                      │
        ┌───────────┬─────────────┬───┴────┬────────────┬───────────┐
        ▼           ▼             ▼        ▼            ▼           ▼
  deliver_job_   TUI           MCP      HTTP        Lambda      Invoke
  result         job_execution _tools   plugin      plugin      (in-process)
  exit codes     exit codes    status   own         own         JobResult
                               string
```

**The boundary is `FunctualizeApp(...)`.** Everything above it on the left is
`func`'s own; everything from it down is common.

---

## 2. Branching **in** — the ways a run can start

Each of these is a distinct starting point, and each can produce different
behaviour for the same job. When you change something, ask which of these
reach it.

| # | Entry | Constructs the app | Notes |
|---|---|---|---|
| 1 | `func <job>` | `_cli/main.py::_handle_job` | full pre-boot layer first |
| 2 | `func <group> <job>` | `_handle_group` → `_dispatch_group` | group listing is rendered **here**, not by click |
| 3 | `func <file>.py` | `_handle_single_file` | `Mode.SINGLE_FILE`; no counterpart on an app |
| 4 | bare `func` | `_handle_bare` | listing, or the inline TUI on a TTY |
| 5 | `func builtin …` | click group | the reserved subtree |
| 6 | a user's `main.py` | the user, directly | **no pre-boot layer at all** |
| 7 | `app.execute(...)` | the user, directly | library use; no CLI in the picture |
| 8 | HTTP / Lambda / MCP plugin | the plugin | adapter owns delivery |
| 9 | `Invoke` / `rc.invoke()` | already booted | in-process, `invoke_depth > 0` |

Two second-order splits sit underneath:

* **`boot_static` vs `boot_standard`** (`app/core.py:184`, predicate
  `_app/impl.py::is_fully_explicit`). Static skips filesystem discovery, plugin
  loading and the `ResolutionChain` entirely. A behaviour that lives in
  `boot_standard` does not exist for a statically-wired app.
* **`CliAdapter` self-contained vs composable** (`app/adapters/cli.py:755`).
  When the caller supplies its own `cli_group`, `register_callback` defaults to
  **False** — so that app has **no pre-command global flags at all**. This is
  why a pre-command-only feature is never sufficient on the app side.

---

## 3. Branching **out** — the ways a run ends

`JobResult` is produced once and translated six ways. `deliver_job_result` is
**not** the universal boundary; it is the boundary for the two *click* surfaces.

| Terminator | Location | Translates to |
|---|---|---|
| `deliver_job_result` | `app/adapters/click_params.py` | process exit code, via `exit_code_for_status` |
| TUI | `_cli/tui/job_execution.py:285` | exit code, via `exit_code_for_status` |
| MCP | `plugins/functualize-mcp/_tools.py:256` | `result.status.value` as a **string** in a tool response |
| HTTP | `plugins/functualize-http` | its own response mapping |
| Lambda | `plugins/functualize-lambda` | its own return payload |
| `Invoke` | `_engine/capabilities/invoke.py` | the `JobResult` itself, to the calling job |

**Consequence to keep in mind:** a new `RunStatus` member, or a change in what
one means, has to be considered at six sites, only two of which share a table.
The single `RunStatus → ExitCode` table in `_types/exit_codes.py` governs the
process-exit family; the others necessarily re-derive, because there is no
process to exit.

---

## 4. The rule: which features must align

Ask one question about a feature: **is it about the program, or about how you
reach the program?**

### Must work on both surfaces — "about the program"

Anything a *job author* declares, or that a job's own behaviour depends on:

* everything in `@job(...)` — `Deps`, `Fingerprint`, `Guards`, `Exec`
* capability injection and DI
* config resolution and its precedence ladder
* `FromJob`, `Sources`, `GroupOptions`
* `@workflow`, `Gate`, and **resuming a gate** ← the case that proved the rule
* freshness, refusal, and the exit-code contract
* anything that makes a declared feature usable at all

> If a job author can write it in their jobs file, every surface that runs jobs
> must be able to honour it. A declaration that only works from `func` is a
> declaration that does not work.

### May be `func`-only — "about reaching the program"

Deliberately, and these are **not** gaps:

| Feature | Why it is `func`-only |
|---|---|
| `--version` | pre-boot fast path over distribution metadata; an app has its own identity |
| `func <file>.py` | `Mode.SINGLE_FILE` reads a path as the thing to run; an app **is** the program |
| aliases | resolved pre-boot, from `merged_config`, before an app exists |
| `--exclude`, `--discovery-depth`, `--require-*` | discovery filters applied *before* the app is constructed — an app declares its `JobSources` in code |
| `--perf-report` with no value | optional-value lookahead in `dispatch.py`; click has no equivalent |
| listing / unknown-command rendering and their exit codes | `_dispatch_group` owns the tree on `func`; click owns it on an app |

### How to add a feature that must align

1. **Put the behaviour in the engine or the app**, not in `_cli/`. If
   `_cli/main.py` is the only caller, it is `func`-only by construction.
2. **Give the command the parameter**, not just the callback. A pre-command
   global reaches a command only if something threads it; a `click.Option` on
   the command travels with it — including through composable mode, where the
   root callback does not exist.
3. **Deposit-and-read for anything genuinely pre-command.** Commands are built
   before the root callback parses, so a global must land on the app
   (`app._force`, `app._workflow_scope_id`) and be read at call time. Both
   surfaces use the same attribute names for this reason.
4. **Test it through `cli_run`**, which is parameterised over both surfaces. If
   it only makes sense on one, say so with `surfaces("func")` and give the
   reason — see `tests/conftest.py`.

### Worked example — `--scope-id`

The flag exists in **three** places, and each is there for a reason:

| Form | Where | Why |
|---|---|---|
| `func --scope-id X walk` | pre-command global, `_cli/dispatch.py` | the original; kept for compatibility |
| `app.py --scope-id X walk` | root callback, `app/adapters/cli.py` | parity, for self-contained apps |
| `<prog> walk --scope-id X` | **command option on workflow jobs**, both surfaces | the one that always works |

The third is the load-bearing one. A composable adapter has no root callback, so
forms one and two can both be absent — and resuming a gate is "about the
program", so it may not depend on how you reached it.

---

## Related

- `contributor/architecture/codemaps/entry-points.md` — the catalog of entry
  points and adapters
- `contributor/reference/execution-lifecycle.md` — what happens *after*
  `engine.execute`, and why in that order
- `contributor/guides/wiring-discipline.md` — proving a path is reached
- `src/functualize/_types/exit_codes.py` — the one `RunStatus → ExitCode` table
- `.spec/STATUS.md` — the recorded divergences that are not yet decided
