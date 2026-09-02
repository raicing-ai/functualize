# Spec: A Workflow Job Rejects Bad Arguments At Launch

**Status: specified**
**Date: 2026-09-02**
**Base: `feat/workflow-run-params` @ `42d6bc5`**
**Source: [`.spec/shape-intents/workflow-run-parameters.md`](../../shape-intents/workflow-run-parameters.md),
Assertions 3 and 4. This feature closes those two and nothing else.**

Every claim about current behavior below carries the command that produced it,
run against this base from `examples/standalone/composition_lab/`.

---

## Problem

`app.execute()` treats a `@workflow` job's arguments as something to bind *after*
the graph has run. A plain job binds them before it does anything.

```
>>> app.execute('lab.parse', zzz_nonsense=1)
RunStatus.FAILURE
    TypeError: parse() got an unexpected keyword argument 'zzz_nonsense'

>>> app.execute('lab.release', scope_id='spec-probe-1', zzz_nonsense=1)
RunStatus.BLOCKED          # no exception, no warning
```

The second call did not ignore the argument cheaply. It **ran the graph**:

```
>>> store.get_scope('spec-probe-1')
status:   blocked
steps:    ['lab.bundle::', 'lab.parse::', 'lab.publish::', 'lab.report::']
gates:    ['approval-gate']
position: approval-gate
```

Four steps recorded, a gate published, a run now waiting on a human. When that
human approves, the walk resumes, reaches the epilogue, binds the kwarg to the
decorated function for the first time, and *then* raises. **The approval is
spent on a run that was never going to succeed.**

The mechanism is ordering. `_run_workflow_prelude` walks the graph before DI
resolution and before the function is ever called, so an argument the function
cannot accept has no opportunity to be refused until the walk is over.

### Why the same argument is refused for a plain job

Nothing validates it. Python's own call binding raises `TypeError` when the
function is finally invoked, and the engine returns that as a `FAILURE`
result rather than letting it escape. For a plain job the call happens
immediately; for a workflow job it happens last. **One rule, two moments** —
and the moment is what makes it a defect.

### Which surfaces are affected

| Surface | Reaches the defect? | Why |
|---|---|---|
| `func <workflow>` (CLI) | **No** | click refuses unknown flags at parse time: `Error: No such option '--zzz-nonsense'` |
| `app.execute(...)` | **Yes** | kwargs pass straight through |
| `rc.invoke(...)` / `Invoke.__call__` | **Yes** | same engine path |
| `functualize-http`, `functualize-lambda` | **Yes** | turn a request body / event payload directly into `execute()` kwargs |
| `functualize-mcp` | **Yes** | schema-validates the tool's own arguments, then passes them on |

The CLI being safe is why this survived to now: the surface everybody develops
against is the one surface that cannot reach it. The surfaces that *can* are the
three whose entire purpose is turning an untrusted external event into a run.

---

## User stories

**An agent starting a gated release over MCP.** It sends `{"verison": "1.4"}`.
Today the walk runs, blocks, and a person is asked to approve a release that
will fail the moment they do. The agent should be told it got the name wrong,
before anything runs.

**A developer calling `app.execute` from a test or a script.** The same typo
behaves one way for `lab.parse` and another for `lab.release`, and nothing at
the call site says which kind of job is being held. The two should agree.

**An operator resuming a blocked run.** `func builtin workflow resume` has
already been paid for with a human decision. A bad argument on the resuming
call must not consume it, and must not advance the run.

---

## Behavior

### B1 — Unknown keyword arguments are refused before the graph walks

When `execute()` is given a keyword argument that the `@workflow`-decorated
function does not declare, and the function declares no `**kwargs`, the call
fails immediately. The graph does not walk, no step runs, no gate is published,
and the runtime state store is not written to.

### B2 — The failure is shaped exactly like a plain job's

A `JobResult` with `status == RunStatus.FAILURE` carrying a `TypeError` whose
message names the function and the offending argument, in Python's own wording.
The exception is **returned on the result, not raised** — the invariant the
engine's existing validation handler exists to preserve, so the CLI can render
a failure panel rather than a traceback.

### B3 — Completeness is *not* checked at launch

Only "is this argument acceptable?" is answered at launch. "Is every required
argument present?" is not, and must not be: a workflow function's parameters are
predominantly DI capabilities (`Log`, `Stdout`) and `FromJob` results, none of
which exist yet when the launch check runs. A workflow declaring `log: Log` and
called with no arguments at all is valid and must stay valid.

### B4 — A resume is checked the same way

`execute(..., scope_id=<existing>, <bad kwarg>)` fails at launch identically. The
existing scope's status, step records, gates and position are unchanged — a
refused launch must not advance, fail, or otherwise disturb a run that is
legitimately waiting.

### B5 — A function accepting `**kwargs` accepts anything

If the decorated function declares `**kwargs`, no argument is unexpected and
nothing is refused. Python's own binding rule is the rule; this feature changes
*when* it is applied, never *what* it decides.

### B6 — Valid calls are unchanged

A workflow job called with arguments it accepts behaves exactly as it does
today, including the values the epilogue receives. Steps still do not see those
arguments — routing launch values into steps is
[`workflow-run-parameters.md`](../../shape-intents/workflow-run-parameters.md)
and is explicitly **out of scope here**.

### B7 — Nested and step-invoked workflows are unaffected

A workflow reached as a `Step` of another workflow is invoked with no arguments,
so the check is a no-op for it. Nothing about nested scope derivation changes.

---

## Out of scope

Named because the shape intent covers them and a reviewer will look for them:

- **Any run-scoped parameter layer.** No `Param` marker, no `RunParamSource`, no
  `scope["params"]`, no ladder change. This feature makes bad arguments fail
  early; it does not make good arguments go anywhere new.
- **`step_key`'s empty `args_hash`.** Untouched. It becomes a question only when
  parameters can vary per run, which is the follow-on work.
- **The `os.environ` recipe in `docs/guides/group-options.md:198`.** Its
  unsoundness across a resume is Assertion 2, a separate defect.
- **Plain-job behavior.** Already correct; this feature must not perturb it.

---

## Acceptance criteria

Gates, run at authoring time. Each is a command whose output decides it.

- [ ] **A1 — The graph does not run.** `app.execute('lab.release',
      scope_id=<fresh>, zzz_nonsense=1)` returns `FAILURE`, **and**
      `StateStore.get_scope(<fresh>)` shows no step records, no gates, and no
      position. Asserting on status alone passes vacuously — the pre-fix
      behavior already writes four step records and a gate, and that is the
      observation that separates the two.

- [ ] **A2 — Parity with a plain job.** For the same offending kwarg,
      `lab.parse` and `lab.release` return the same `status` and the same
      exception type, and both messages name the function and the argument.

- [ ] **A3 — DI-only workflows still run.** `app.execute('lab.release')` with no
      arguments reaches the gate and blocks, exactly as it does today. Proves
      B3: the launch check did not become a completeness check.

- [ ] **A4 — A refused resume disturbs nothing.** Against a scope blocked at
      `approval-gate` whose gate payload has been deposited, a launch carrying a
      bad kwarg returns `FAILURE`, and the scope's `status`, `steps`, `gates` and
      `position` are byte-identical before and after.

- [ ] **A5 — `**kwargs` is honoured.** A workflow function declaring `**kwargs`
      accepts an arbitrary argument and walks its graph.

- [ ] **A6 — Reachability.** The production call path is named and verified by
      sabotage: breaking the launch check makes A1 fail. "A test calls it" is not
      a call path.

- [ ] **A7 — No regression.** Full suite under `HYPOTHESIS_PROFILE=ci
      --run-slow -n auto`, `pytest examples/`, all plugin suites, `ruff`, `mypy
      src/`, `lint-imports`. The workflow suite (`-k workflow`) and the
      combination matrix are the two that would notice this change.

---

## Notes for the plan phase

Two things the implementation has to decide, recorded here as questions rather
than answers because they are technical rather than behavioral:

1. **Where the check goes.** It must run before `_run_workflow_prelude`
   (`_engine/executor.py:797`) and must not duplicate the binding rule that
   already exists — one rule, one implementation, or the two will drift.

2. **How DI parameters are excluded.** The check needs to distinguish "a
   parameter the caller may supply" from "a parameter DI will fill". Whatever
   answers that should be shaped so the `Param` targeting design in the shape
   intent can reuse it rather than grow a second classifier. Any site reading
   annotations must go through `resolved_hints` (`_types/annotations.py:44`) —
   under PEP 563 a raw annotation is a string and matches nothing, silently.
