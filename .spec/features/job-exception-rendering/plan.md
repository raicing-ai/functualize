# job-exception-rendering — plan

## Alignment

`Shape state = not-required` on the tracking issue (set by the maintainer).
There is no shape page, so there is nothing to cite. The user-visible surface is
named in `spec.md` in the accepted ticket's own words: "a one-line error at the
failure exit code, with the framework traceback behind an explicit opt-in".

## Architecture gate

### Retrieval

- **Prose (zvec-grep):** index built for this worktree (13 644 entities,
  1 m 27 s). Query *"a job that raised renders a one-line error instead of a
  traceback at the process boundary"* hit `contributor/reference/pitfalls.md`
  §25, `deliver_job_result`, `prelude_refusal` and `_failure_before_execution`.
  No ADR decides against rendering a job's exception. §25 prescribes the test
  shape: "assert in a subprocess that `stderr` contains no `File "` and that the
  exit code is the one the table names".
- **Counts and negatives (rg):** `raise result.exception` appears twice in
  `src/` — `app/adapters/click_params.py:1255` (the boundary) and
  `_engine/capabilities/invoke.py:532` (in-process `invoke()`, not a boundary).
  `deliver_job_result` has two callers: `click_params.py:1126` (eager wrapper)
  and `lazy_command.py:181` (warm path). The engine builds a `JobResult` with
  an exception in four places: `executor.py` `_execute_with_lifecycle`
  (job/middleware), `_failure_before_execution` (pre-body refusal),
  `dependency_runner.py:204` and `workflow_orchestrator.py:250` (synthesised
  `RuntimeError`s).
- **Symbols and dependency direction:** serena and graphify were **not** run.
  Their questions — who references `deliver_job_result`, and may `_engine` and
  `app/adapters` both import `_types` — were answered with the `rg` reference
  query above and the import-linter table in `.spec/CONSTITUTION.md` (both
  layers may import `_types`; `lint-imports` confirms it below). That is a
  deviation from the three-tool rule, and it is disclosed rather than hidden.
- **Codemaps:** `contributor/architecture/codemaps/entry-points.md` and
  `data-flow.md` show the CLI → adapter → `engine.run()` → `JobResult` →
  adapter flow the diagrams below draw. No contradiction.

### BEFORE

```
 layer        module                                        crosses
 ───────────  ────────────────────────────────────────────  ─────────────────────
 _cli         _cli/main.py ── invoke_command_capturing ──┐
 app (public) app/adapters/click_params.py               │
                wrapper (eager) ─┐                       ▼
              app/adapters/lazy_command.py (warm) ─┐   click.Command.main
                                                  ▼   ▼
                               deliver_job_result(result)
                                 BrokenPipe  → exit 0
                                 ValidationError → panel, exit 2
                                 MissingValueError → line, exit 2
                                 else → raise result.exception ──► interpreter
                                                  ▲                 traceback, exit 1
                                                  │ JobResult(exception=…)
 _engine      _engine/executor.py                 │
                _execute_with_lifecycle:          │
                  try: middleware(_execute_job) ──┘   job body OR middleware —
                  except BaseException as exc        indistinguishable here
 _types       _types/descriptors.py JobResult · _types/outcome.py · exit_codes.py
```

Smells the BEFORE already carries, by catalogue name:

- **Large Class** — `JobExecutionEngine` (`_engine/executor.py:164-2763`,
  2 600 lines) — already far past the constitution's ~500 LOC threshold.
- **Long Method** — `_execute_with_lifecycle` (137 lines) and
  `deliver_job_result` (98 lines).
- **Lost information at a boundary** (described plainly — not a catalogue name):
  the one place that knows whether the job body raised (`_execute_job`) throws
  that knowledge away. Every consumer is left to guess from the exception
  object, which is the message-shaped guess the ticket rules out.

### AFTER

```
 _engine      _engine/executor.py
                _execute_with_lifecycle:
                  _execute_job records every exception that escapes
                    function(**call_kwargs)            (identity, not type)
                  except BaseException as exc
                  failure result → _mark_raised_by_job(metadata, exc, escaped)
                       sets metadata[RAISED_BY_JOB]=True iff exc is recorded,
                       else removes the key
                        │ JobResult(exception=…, metadata={raised_by_job: True})
                        ▼
 app (public) app/adapters/click_params.py
                deliver_job_result(result)   ◄── wrapper (eager) · lazy_command (warm)
                  BrokenPipe / ValidationError / MissingValueError — unchanged
                  _renders_as_job_error(result)?
                     yes → "Error: <Class>: <msg>" on stderr, SystemExit(1)
                     no  → raise result.exception   (traceback, as today)
 _types       _types/outcome.py   RAISED_BY_JOB, raised_by_job(result)
                 ▲ imported by _engine (producer) and app (consumer)
```

What crosses a boundary: one string-keyed metadata entry on the existing
`JobResult`, from `_engine` up to `app`. Both import the key from `_types`,
which every layer may import. No new import edge between peer layers, no
`click` in a kernel layer, no new public symbol.

Candidate AFTERs considered and rejected:

1. **Traceback inspection at the boundary** — walk `exc.__traceback__` for the
   job function's code object. No engine change, but it is a guess about frames
   (a wrapped or materialised function has a different code object), and the
   lazy path has only a descriptor. Rejected: the ticket asks for a decision
   "from what is known about the call", and the call is in the engine.
2. **A new `JobResult` field** (`raised_by: Literal["job", "framework"]`). Typed,
   so no *primitive obsession*, but `JobResult` is public
   (`functualize.types.JobResult`): an ADR, a public-API example, and every
   surface's serialisation would come with it. Rejected as disproportionate for
   a CLI rendering fix; recorded below as the accepted compromise.
3. **Type allow-list** ("render everything except these internal error
   classes"). Rejected outright — a message/type-shaped guess, and it fails open
   for every internal error class not yet on the list.

Smells the settled AFTER introduces, checked: no **shotgun surgery** — the rule
has one producer, one consumer and one shared key, and nothing else changes when
it changes. No **divergent change** added to `deliver_job_result`: the new arm
is the same kind of decision as the three arms above it (how to render a typed
failure).

### Skills consulted

- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue) —
  ch32 *Bloaters* (Large Class, Long Method, Primitive Obsession) and ch34
  *Change Preventers* (Shotgun Surgery, Divergent Change) for the smell
  vocabulary above.
- The in-repo `python-design-patterns` skill was not loaded; its principles
  (KISS, SRP) are covered by the catalogue entries above.

## Surviving smells

| Smell (catalogue) | Where | Why accepted | Maintainer review? |
| --- | --- | --- | --- |
| **Large Class** (pre-existing; this change adds wiring only) | `JobExecutionEngine`, `_engine/executor.py` | The mark has to be set where the job is called, and that call is inside `_execute_with_lifecycle`. The logic is module-level (`_call_recording_escape`, `_mark_raised_by_job`); inside the class the change is one list, one changed closure line and one call. The class's size is already recorded, with its decomposition plan, in `contributor/architecture/audit-engine-encapsulation.md` row 7 (Extract Class per axis of change). Decomposing it is that plan's job, not this fix's. | No — the size is already recorded and owned elsewhere, and this adds no responsibility to the class. Reported to the maintainer in the hand-off anyway, so the call can be overridden. |
| **Primitive Obsession** | `JobResult.metadata["raised_by_job"]` | A string-keyed bool instead of a typed field, to keep the change off the public `JobResult` type (rejected AFTER 2). The key has one definition (`_types/outcome.py`), and both sides import it rather than spelling it out. | No |
| **Long Method** (pre-existing) | `deliver_job_result` | Grows by one arm; the rendering decision is extracted into `_renders_as_job_error`, so the method itself grows by four lines. | No |

## Technical approach

1. `_types/outcome.py` — add `RAISED_BY_JOB` and `raised_by_job(result)`.
2. `_engine/executor.py` — `_execute_job` calls the job through module-level
   `_call_recording_escape(function, call_kwargs, escaped)`, which appends any
   exception that leaves the call and re-raises it; module-level
   `_mark_raised_by_job(metadata, exception, escaped)` sets or removes the key
   on the failure result. It is applied after the
   `RunContext`-metadata merge, so a job cannot plant the key.
3. `app/adapters/click_params.py` — `_renders_as_job_error(result)` (marked,
   an `Exception`, not a click signal, DEBUG not enabled) and
   `_job_error_line(exc)`; `deliver_job_result` uses both before the final
   `raise result.exception`.
4. `CHANGELOG.md` — `[Unreleased]` entry.

## Files to change

`src/functualize/_types/outcome.py`, `src/functualize/_engine/executor.py`,
`src/functualize/app/adapters/click_params.py`, `CHANGELOG.md`; tests
`tests/engine/test_raised_by_job_mark.py`,
`tests/pipeline/test_exit_code_routing.py`,
`tests/pipeline/test_job_exception_rendering.py`.

## Risks

- **Executor merge contention.** `executor.py` is shared with other in-flight
  fixes. The edit is confined to `_execute_with_lifecycle` (`:2627-2763`) plus a
  module-level helper, and none of the other fixes cite lines in that range.
- **DEBUG as the opt-in** is coarse: it also turns on every DEBUG log line.
  It is the existing precedent in the same module, and it adds no surface.
- **Capability defects read as the job's** (spec B3's stated limit).
- **Synthesised failures** (`dependencies failed for …`, a workflow walk's
  error) still print a framework traceback. Not the job's own exception and
  out of scope here; a candidate follow-up.
