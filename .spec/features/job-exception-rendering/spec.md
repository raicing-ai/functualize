# job-exception-rendering — a job's own exception is a job error, not a crash

## Problem

A job whose body raises prints the framework's call stack. Measured on
`4e816a0f` with a job `def boom(): raise RuntimeError("boom")`:

```
$ func boom
Traceback (most recent call last):
  File ".../.venv/bin/func", line 10, in <module>
  File ".../functualize/_cli/main.py", line 1834, in main
  File ".../functualize/_cli/main.py", line 2157, in _run_cli
  File ".../functualize/_cli/main.py", line 1504, in _handle_job
  File ".../functualize/app/adapters/click_params.py", line 1557, in invoke_command_capturing
  File ".../click/core.py", line 1445, in main
  File ".../click/core.py", line 1308, in invoke
  File ".../click/core.py", line 877, in invoke
  File ".../functualize/app/adapters/click_params.py", line 1126, in wrapper
  File ".../functualize/app/adapters/click_params.py", line 1255, in deliver_job_result
  File ".../functualize/_engine/executor.py", line 2701, in _execute_with_lifecycle
  File ".../functualize/_engine/executor.py", line 2690, in _execute_job
  File "/tmp/foss4-repro/boom.py", line 2, in boom
RuntimeError: boom
exit=1
```

The exit code is already right (1, `ExitCode.JOB_RAISED`); the output is not.
The job author's message is the last of ~40 lines, under twelve frames that
belong to the CLI entry point, click, the adapter and the engine.

The cause is one line. `deliver_job_result`
(`src/functualize/app/adapters/click_params.py:1200`) renders three exception
types — `BrokenPipeError` (quiet exit 0), pydantic `ValidationError` (panel,
exit 2), `MissingValueError` (one line, exit 2) — and then does a bare
`raise result.exception` (`:1255`). Everything else escapes to the
interpreter's traceback printer.

The two adjacent cases already meet the standard this one misses: a missing
config value renders a panel with zero frames and exit 2, and a job that raises
`click.ClickException("msg")` prints `Error: msg` and exits 1. A job raising an
ordinary exception gets neither.

## The accepted outcome

Quoted from the accepted field report's acceptance note (2026-10-05):

> a job's own exception is rendered as a one-line error at the failure exit
> code, with the framework traceback behind an explicit opt-in.

and from the work ticket's scope line:

> render the boundary failure; do not change the exit-code table, and keep the
> traceback available behind an opt-in.

The ticket's fix direction asks for "one line with the class and message, at
the job-failure exit code". No accepted text promises any further wording
(no "next command" suggestion), so none is added.

## Behaviour

### B1 — the job's own exception renders as one line

When the exception on a `FAILURE` result is **the job's own** (defined in B3)
and it is an ordinary `Exception`, the process boundary:

- writes exactly one line to **stderr**:
  `Error: <ExceptionClass>: <message>`, or `Error: <ExceptionClass>` when
  `str(exc)` is empty;
- writes nothing to stdout beyond what the job itself emitted before raising;
- exits with `exit_code_for_status(RunStatus.FAILURE)` — **1**,
  `ExitCode.JOB_RAISED`, the documented "the job raised" code. The exit-code
  table is unchanged.

`<ExceptionClass>` is the class's `__qualname__`, never its module path. That is a
deliberate choice, and it has a side effect worth naming: the synthetic
`_functualize_sync_.<stem>_<id>` module prefix the field report saw (a job
module loaded through the deferred provider) cannot reach this line, because
no module is printed at all.

The line carries **no stack frame** — no `File "` line, no `Traceback`
header, and in particular no frame from `click`, `functualize/app/adapters/`,
`functualize/_cli/` or `functualize/_engine/`.

### B2 — the traceback stays one flag away

With `--log-level DEBUG` — the existing global flag, on both entry points (`func`
and a project's own `FunctualizeApp` + `CliAdapter` script) — the boundary
behaves exactly as it does today: the exception is re-raised and Python prints
the full traceback, exit 1. That is the explicit opt-in. No new flag, setting
or environment variable is introduced.

DEBUG is the precedent the same module already sets: `_report_blocked` prints a
gate's input schema only when `logger.isEnabledFor(logging.DEBUG)`.

### B3 — how "the job's own exception" is told apart from a framework failure

The classification is decided **where the call happens**, by object identity,
not from the exception's type, message or traceback text.

1. `JobExecutionEngine._execute_with_lifecycle` calls the job through one
   closure, `_execute_job`, which is the only place `function(**call_kwargs)`
   runs. That closure records every exception object that escapes the job
   function call.
2. When the lifecycle's `try` catches an exception, the engine compares it, by
   `is`, against the recorded objects. Only if it is one of them is the
   result marked: `JobResult.metadata["raised_by_job"] = True`. In every
   other case the key is removed from the result's metadata, so neither a
   stale value nor one written by the job's own `RunContext` metadata can
   survive onto a failure the job did not raise.
3. The boundary renders B1 **only** when that mark is `True`. Every other
   exception on a `JobResult` is re-raised exactly as today.

What that means, case by case:

| Exception on the result | Marked? | At the boundary |
| --- | --- | --- |
| Raised by the job body, re-raised unchanged by any execution middleware | yes | one line (B1) |
| Raised by a capability *called from* the job body and not caught by it (`invoke` re-raising a child's error, a `Shell` failure) | yes — it escaped the job call | one line (B1) |
| Raised by execution middleware itself — before the body runs, or after a body that returned | no | traceback, as today |
| A refusal before the body ran (`_failure_before_execution`: config/argument validation, launch refusal) | no | unchanged — panel / `MissingValueError` line / traceback, as today |
| Synthesised by the engine (`dependencies failed for …`, a workflow walk's `run.error`) | no | traceback, as today |
| Raised outside any `JobResult` (DI, boot, hooks before the body) | n/a — never a `JobResult` | traceback, as today |

A bug inside functualize that raises from the engine, the adapter, a hook or a
middleware is therefore **not** marked and keeps its traceback.

A middleware cannot today *replace* a job's exception with its own:
`_resume_generators` (`_engine/middleware.py`) keeps the first exception and
throws it through every generator. If that ever changes, the identity check
keeps a substituted exception unmarked — a same-class exception is not the
same object.

The honest limit of the rule: a functualize defect inside a capability that the
job calls, and which the job does not catch, escapes through the job's own call
and is marked as the job's. From the call site it cannot be told apart from a
capability failing on purpose (`invoke` re-raising a child's error is exactly
that), and any rule that tried would have to read types or frames — the
message-shaped guess this spec rules out. For that case B2's opt-in is the way
to the traceback.

### B4 — what is not rendered, and stays as it is

These keep their current behaviour, checked before B1 or excluded from it:

- `BrokenPipeError` — quiet exit 0 (T39).
- pydantic `ValidationError` — validation panel, exit 2.
- `MissingValueError` — `Error: <message>`, exit 2.
- `click.ClickException`, `click.exceptions.Abort`, `click.exceptions.Exit`
  raised by the job — re-raised so click renders them the way it does today
  (`Error: msg` exit 1; `Aborted!` exit 1; the requested exit code). They are
  CLI signals the author chose, and B1 would change their wording.
- A `BaseException` that is not an `Exception` (`SystemExit`,
  `KeyboardInterrupt`) — re-raised as today.

### B5 — both dispatch paths, one rule

`deliver_job_result` is reached from exactly two places: the eager command's
`wrapper` (`click_params.py:1126`, cold boot) and the lazy command
(`lazy_command.py:181`, warm boot). B1–B4 live in `deliver_job_result` and
nowhere else, so the cold and the warm run of the same job render the same
line and the same exit code. (The other `raise result.exception` in `src/`,
`_engine/capabilities/invoke.py:532`, is `invoke()` re-raising a child's
failure into its parent's body — not a process boundary — and is untouched.)

### B6 — `--emit-format` on a failed job

Unchanged, and now stated: `--emit-format` (`auto|json|ndjson|raw|none`)
governs only what `out.emit()` writes to **stdout**. Neither the B1 line nor
the B2 traceback is ever written to stdout, and no JSON error document is
emitted on failure — there was none before, and the ticket does not ask for
one. The stderr line is byte-identical whatever `--emit-format` says, so the
JSON path and the text path carry the same information: the exit code, plus
the same one stderr line.

## Acceptance criteria

- **AC1.** `func boom` where `boom` raises `RuntimeError("boom")` exits **1**
  and its stderr is exactly `Error: RuntimeError: boom` plus a newline, ignoring
  unrelated log lines. Holds on both entry points (`func`, app script) and on
  the cold **and** the warm run.
- **AC2.** A subprocess test pins the absence of framework frames: stderr
  contains no `Traceback`, no `File "`, and none of `click/`,
  `functualize/app/adapters/`, `functualize/_cli/`, `functualize/_engine/`.
  It also pins exit code 1. (`pitfalls.md` §25: "assert in a subprocess that
  `stderr` contains no `File "` and that the exit code is the one the table
  names".)
- **AC3.** A failure that is not the job's own keeps its traceback: an
  execution middleware that raises its own exception produces a result with no
  `raised_by_job` mark, and the boundary re-raises it. A job that raises and a
  middleware that re-raises the same object produces a marked result. A job
  writing `raised_by_job` into its own result metadata does not mark a failure
  the job did not raise.
- **AC4.** `func --log-level DEBUG boom` prints the full traceback (it contains
  `Traceback` and the job's own frame) and exits 1.
- **AC5.** `func --emit-format json boom` prints the same stderr line as AC1,
  nothing on stdout, exit 1.
- **AC6.** `click.ClickException`, `BrokenPipeError`, pydantic `ValidationError`
  and `MissingValueError` keep their current rendering and exit codes (existing
  tests stay green; one new unit test pins `ClickException` passing through).
- **AC7.** One classification site: `rg -n "raise result.exception"
  src/functualize/app` returns exactly one hit, inside `deliver_job_result`.

## Out of scope

- Suggesting a next command or any wording beyond the class and the message.
- Changing the exit-code vocabulary.
- Suppressing tracebacks for anything other than the job's own exception.
- A documented user-facing error type for expected failures, and documenting
  `click.ClickException` as one (the field report's F19, a separate finding).
- Naming the class by its real module when the deferred provider loaded it.
  B1 prints no module at all, so the prefix cannot reach the one-line form;
  under B2's opt-in the traceback may still show it.
- Rendering of failures on non-process surfaces (TUI, MCP, HTTP).
