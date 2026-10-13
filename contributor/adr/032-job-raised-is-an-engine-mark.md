# ADR-032: "The Job Raised It" Is a Mark the Engine Sets, Not a Guess the Boundary Makes

**Status**: accepted
**Date**: 2026-10-12
**Deciders**: the job-error rendering fix (pull request #107) and its review,
which asked for the internal contract to be recorded here once the feature's
working spec was cleared.

## Context

A job whose body raised used to print the whole call stack at the process
boundary: the console script, the CLI dispatcher, click, the adapter and the
executor, with the job author's message as the last of about forty lines.
`deliver_job_result` (`app/adapters/click_params.py`) rendered three exception
types and ended in a bare `raise result.exception` for everything else.

The fix renders the job's **own** exception as one stderr line,
`Error: <Class>: <message>`, at exit 1. The user-visible half is in
`CHANGELOG.md`. This record holds the internal half: how the boundary knows an
exception is the job's own, and what crosses from the engine to the adapter to
say so.

The difficulty is that the boundary cannot tell by looking. The engine's
lifecycle (`JobExecutionEngine._execute_with_lifecycle`) runs execution
middleware and the job body under one `except BaseException`, and the result it
returns carries the exception object and nothing about its origin. Any rule
written at the boundary would have to read the exception's type, message or
frames, and that would be a guess. Only the engine makes the call to the job
function, so only the engine can know.

## Decision

### 1. The engine marks the result, by identity, at the call

- `_call_recording_escape` (`_engine/executor.py`) is the one place
  `function(**call_kwargs)` runs. It appends every exception object that leaves
  that call to a per-run list, `escaped`, and re-raises it. It is a list rather
  than one slot because a middleware may call the job more than once.
- `_mark_raised_by_job` runs on the failure result. It sets
  `metadata["raised_by_job"] = True` only if the caught exception **is**, by
  `is`, one of the objects in `escaped`. Otherwise it **removes** the key.
- Order is what makes the mark trustworthy. The mark is applied **after**
  `result_metadata` is merged from the execution context and from the
  `RunContext` (`set_result_metadata`, and the non-framework keys of its
  `_metadata`). A job, or anything else holding the run's metadata, can write
  the literal `"raised_by_job"`, because `set_result_metadata` reserves no keys.
  That value never survives onto a failure the job did not raise: the
  identity check decides, then writes or deletes.
  `tests/engine/test_raised_by_job_mark.py::test_a_planted_key_cannot_claim_a_failure_the_job_did_not_raise`
  pins this.

Classification, case by case:

| Exception on the result | Marked |
| --- | --- |
| Left the job function call, then re-raised unchanged by any middleware | yes |
| Raised by a capability the job called (`invoke`, `sh`) and not caught by the job | yes: it left the job's own call |
| Raised by execution middleware, before the body or after a body that returned | no |
| A refusal before the body ran (`_failure_before_execution`) | no |
| Synthesised by the engine (`dependencies failed for …`, a workflow walk's error) | no |

The second row is the rule's honest limit. A functualize defect inside a
capability, if the job lets it propagate, reads as the job's. From the call
site it is indistinguishable from a capability failing on purpose, and `invoke`
re-raising a child's error is exactly that. `--log-level DEBUG` is the way back
to the traceback for that case.

A middleware cannot currently *replace* a job's exception, because
`_resume_generators` (`_engine/middleware.py`) keeps the first exception it
sees. If that ever changes, the identity check keeps the substitute unmarked.
An exception of the same class is still a different object.

### 2. The mark is a metadata key, not a typed `JobResult` field

The vocabulary lives once, in `_types/outcome.py`: `RAISED_BY_JOB` (the key)
and `raised_by_job(result)` (the predicate). `_engine` imports it as the
producer and `app/adapters` as the consumer. `_types` is the one layer both may
import, so neither restates the string.

A typed field on `JobResult` (`raised_by: Literal["job", "framework"]`) was
considered and rejected. `JobResult` is public (`functualize.types.JobResult`).
A new public member brings an ADR of its own, a caller in `examples/` under the
public-API coverage rule, and a serialisation decision on every surface that
renders a result. All of that would come in to support one adapter's rendering
choice. The metadata key keeps the change off the public type. The cost is
accepted under its catalogue name: *Primitive Obsession*, a string-keyed bool,
contained by having exactly one definition and one predicate. The key is not
documented for job authors.

### 3. The boundary renders only a marked, ordinary exception

`deliver_job_result` keeps its existing arms first: `BrokenPipeError` (quiet
exit 0), pydantic `ValidationError` (panel, exit 2) and `MissingValueError` (one
line, exit 2). It then prints one line and raises
`SystemExit(exit_code_for_status(result.status))` only when
`_renders_as_job_error` holds:

- the result is marked (`raised_by_job(result)`);
- the exception is an `Exception`, and not `click.ClickException`, `Abort` or
  `Exit`. Those are click signals the job chose. `SystemExit` and
  `KeyboardInterrupt` are not errors to describe;
- the logger is not at DEBUG. `--log-level DEBUG` is the explicit opt-in back to
  the full traceback, on both entry points.

The class is printed as `type(exc).__qualname__` and never with its module, so
the synthetic `_functualize_sync_.*` module name of a cache-loaded job never
reaches the line. Everything else is re-raised exactly as before, so a
framework failure keeps its traceback. There is one `raise result.exception` in
`app/`. Both dispatch paths reach it: the eager command (cold boot) and the lazy
command (warm boot). The `raise result.exception` in
`_engine/capabilities/invoke.py` is `invoke()` handing a child's failure to its
parent's body. It is not a process boundary and is out of scope.

### 4. PANEL, TOOL and WIRE are out of scope, because they never had the defect

The defect was a traceback reaching a person. Only the PROCESS boundary leaked
one. The other three families render the exception's text and never re-raise
it to their caller:

- **PANEL**: the TUI (`_cli/tui/job_execution.py`) writes
  `✗ Failed: {detail}`, where `detail` comes from `_translate_error(exc)`, which
  starts from `str(exc)`.
- **TOOL**: MCP (`functualize-mcp`, `_tools.py`). A failed run returns
  `status` plus `wire_metadata(result)`; an exception escaping the call becomes
  an `execution_error` envelope carrying `str(e)`. Nothing is re-raised to the
  client.
- **WIRE**: HTTP (`functualize-http`) sets `response_body["error"] =
  str(exception)` on a failed result, and its outer handler returns
  `{"error": str(e)}` with status 500. `logger.exception` writes only to the
  server log.

None of them reads the mark, and none needs to.

## Consequences

### Positive

- The question "did the job raise this?" has one answer, decided where the
  answer is known. Every future boundary asks `raised_by_job(result)` and needs
  no rule of its own.
- A framework failure is never dressed up as a job error. Anything the engine
  did not see leave the job call keeps its traceback.
- No public type changed, and no import edge was added between peer layers
  (`lint-imports`: 7 kept, 0 broken).

### Negative

- **The key is visible on one surface.** MCP's `wire_metadata(result)` copies
  `JobResult.metadata` whole, so an MCP tool response for a failure the job
  raised now carries `"raised_by_job": true` in its `metadata`. This was
  confirmed by running a raising job through `FunctualizeApp.execute` and
  `wire_metadata`. It is additive and true, but it is an undocumented key on
  the TOOL wire. If MCP's metadata is ever documented as a contract, this key
  must be documented or filtered there. HTTP does not return metadata; the TUI
  does not render it.
- **A capability defect that the job lets propagate reads as the job's**
  (Decision 1). The traceback is one `--log-level DEBUG` away.
- **DEBUG is a coarse opt-in.** It turns on every DEBUG log line as well. It
  follows the precedent of `_report_blocked`, which shows gate detail at the
  same threshold, and it adds no flag.
- `JobExecutionEngine` grows by wiring only: one list, one changed closure line
  and one call. The logic is in module-level functions. The class's size and
  its decomposition plan are recorded in
  `contributor/architecture/audit-engine-encapsulation.md`.

### Neutral

- A child result from `invoke` carries the child's own mark internally. A
  parent's result is built from the parent's own context, and the parent is
  marked on its own evidence: the child's exception left the parent's job call.

## Relation to ADR-031

[ADR-031](031-persistence-port-status-is-typed.md) declined *Primitive
Obsession* for status fields on the persistence port and typed them. This
decision accepts the same smell for a different kind of boundary, and the two do
not conflict:

- ADR-031's fields are a **stored, multi-backend contract**. Out-of-tree
  implementers write them and read them back, and a mistyped value corrupts
  durable state.
- `raised_by_job` is an **in-process, single-producer and single-consumer
  hint** on a public type that would otherwise have to grow. Its worst failure
  is one rendering choice: the traceback instead of one line.

ADR-031 is scoped to the persistence port and is not binding here. This record
does not reopen it.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| Decide at the boundary from the traceback (find the job function's code object among the frames) | No engine change | A guess about frames: a materialised or wrapped function has a different code object, and the warm path holds only a descriptor | The engine makes the call, so the engine should decide |
| Allow-list of internal error types; render everything else as the job's | Small diff | Type-shaped guessing; fails open for every internal error class not yet listed | Classifies by what an exception *is*, not where it came from |
| Typed `JobResult` field | Typed, no string key | Public API change with its ADR, example coverage and per-surface serialisation, to support one adapter's choice | Disproportionate; see Decision 2 |
| Render every `JobResult` exception as one line | Simplest | Hides the traceback of a functualize bug, which is what whoever reports it needs | The ticket's scope keeps framework tracebacks |

## What would reopen this

A second consumer of the mark that needs it as part of a **documented** wire
contract, such as MCP documenting its `metadata` keys or a run-history view
showing it, would justify promoting the key to a typed, documented field. Or a
capability that needs its own failures kept out of the job's mark would call
for a finer origin than "left the job call".
