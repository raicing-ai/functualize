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
rule has already been applied twice, to the same feature: scope addressing was
a `func`-only flag, so a `@workflow` with a `Gate` on a `FunctualizeApp` blocked
at exit 5 forever and the recorded input was never read — and the fix for that
was itself later replaced, for reasons §"Worked example" records.

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
* `--force`, `--prompt-gates` and `--emit-format` — the three delivery inputs. Listed
  here as *description*, not aspiration: `run-request-entry/T13` put the two
  missing ones on an app's own entry point, and the dual-surface tests
  (`tests/cli/test_app_surface_prompt_gates.py`,
  `tests/cli/test_app_surface_output_format.py`) run one body over both. Until
  then `adapters/cli.py` declared only `--force`, beneath a comment claiming
  parity for both — so a `@workflow` reached from an app blocked at exit 5 with
  no flag on that surface to prompt its gate
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
3. **For anything genuinely pre-command, use the per-invocation channel — never
   the app.** Commands are built before a root callback parses, so a global has
   to reach the callback somehow. There are two honest routes, in order of
   preference:

   * **Pass it to the builder.** `func`'s handlers parse their flags *before*
     constructing the command, so they hand the value to
     `create_job_click_command(..., force=..., output_format=...)` and it rides
     the closure. This is the route to take whenever the parsing happens first.
   * **Put it in `ctx.obj`.** An app's own root callback parses *after* its
     subcommands are built and genuinely cannot pass anything down. `ctx.obj` is
     created per invocation and torn down with it, and `adapters/cli.py` already
     fills it; `_request_builder.build_request` reads it when no door stated a
     value of its own.

   > **This item used to say the opposite.** It prescribed depositing the value
   > on the app (`app._force`, `app._output_format`, `app._prompt_gates`) and
   > reading it back at call time. That was the *deposit protocol*, and
   > `run-request-entry/T12` deleted all eleven writes. The problem was not
   > tidiness: the app is a process-lifetime object, so two concurrent runs
   > shared one answer, and the kernel reached two attributes deep through
   > `engine._app` for a value the app is under no obligation to have. Ambient
   > *scope* is sometimes unavoidable; ambient *lifetime* is what breaks.
   >
   > `app._workflow_scope_id` survives, deliberately: it is the programmatic
   > seam an embedded host sets directly, and it has no CLI spelling.
4. **Test it through `cli_run`**, which is parameterised over both surfaces. If
   it only makes sense on one, say so with `surfaces("func")` and give the
   reason — see `tests/conftest.py`.

### Worked example — addressing a workflow scope

This one is worth following all the way through, because it ends by **deleting**
two of its own three forms.

`--scope-id` existed in three places:

| Form | Where | Why it was there |
|---|---|---|
| `func --scope-id X walk` | pre-command global, `_cli/dispatch.py` | the original |
| `app.py --scope-id X walk` | root callback, `app/adapters/cli.py` | parity, for self-contained apps |
| `<prog> walk --scope-id X` | **command option on workflow jobs**, both surfaces | the one that always works |

The third was the load-bearing one, for exactly the reason this page gives: a
composable adapter has no root callback, so the first two can both be absent —
and addressing a run is "about the program", so it must not depend on how you
reached it.

**Then the rule was applied again, and the first two went.** Per-command
coverage was measured across every dispatch mode, cold cache and warm, and found
complete. That made the two root-callback forms redundant — and the pre-command
one was worse than redundant: it was the only member of
`_GLOBAL_OPTIONS_ALWAYS_VALUE` addressing *persisted state* rather than
discovery, config or performance, so `func --help` listed it among global config
flags where it silently did nothing on a non-workflow job.

The replacement is the `--wf-*` family, post-command only, on jobs that declare
a `@workflow`. Same shape as the surviving form, and the same reasoning:

| Form | Where |
|---|---|
| `<prog> walk --wf-resume X` | command options on workflow jobs, **both surfaces**, and nowhere else |

`app._workflow_scope_id` remains as a **programmatic** seam for embedded hosts —
the hole this whole story began with — documented as API-only with no CLI
spelling.

**The rule that survives all three revisions:** a capability that is "about the
program" belongs where every surface reaches it identically. Which spelling that
is can change; that it must be one spelling does not.

---

## Related

- `contributor/architecture/codemaps/entry-points.md` — the catalog of entry
  points and adapters
- `contributor/reference/execution-lifecycle.md` — what happens *after*
  `engine.execute`, and why in that order
- `contributor/guides/wiring-discipline.md` — proving a path is reached
- `src/functualize/_types/exit_codes.py` — the one `RunStatus → ExitCode` table
- `.spec/STATUS.md` — the recorded divergences that are not yet decided
