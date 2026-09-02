# Plan: Workflow Launch Validation

**Spec:** [`spec.md`](spec.md) · **Contracts:** [`contracts.md`](contracts.md) ·
**Findings:** [`research.md`](research.md)

---

## Approach

Three moves, in order. The whole feature is roughly 40 lines of source.

1. **Put the rule in one function.** `unexpected_keyword_error(function,
   kwargs) -> TypeError | None` in `_engine/validation.py`, beside
   `ArgValidator`. It delegates to `inspect.Signature.bind_partial` (R1) and
   re-raises with the function name prefixed so the message is byte-identical to
   a real call's. It knows nothing about DI, workflows, or the engine.

2. **Construct `ExecutionContext` above the workflow prelude** rather than
   below it (R5). Every argument is already in scope; the prelude does not read
   the context. This is the enabling move, and the one with risk.

3. **Wire the check between them.** If the function carries
   `__functualize_workflow__` and the rule returns an error, return through the
   established refusal shape (R4): fire `AFTER_FAILURE`, skip `PRE_EXECUTE`,
   emit `job.execute.end` with `status="failure"`, return a `FAILURE`
   `JobResult` carrying the `TypeError`. The prelude is never reached, so no
   scope record is written (R6).

### Why the check is gated on `__functualize_workflow__`

A plain job needs no launch check — its `TypeError` already arrives at the right
moment, from the real call, with hooks fired. Running the check for every job
would add a second place that decides the same thing and would change the hook
sequence for plain jobs (`PRE_EXECUTE` currently fires before the failure).
**The defect is the workflow prelude's ordering, so the fix belongs at the
workflow prelude.**

### What is deliberately not built

No `Param` marker, no `RunParamSource`, no `scope["params"]`, no change to
`step_key`'s empty `args_hash`. The follow-on work
([`workflow-run-parameters.md`](../../shape-intents/workflow-run-parameters.md))
inherits a launch-time binding point and nothing else. Per R2 this feature grows
no parameter classifier for that work to have to unpick.

---

## Files to change

| File | Change | Size |
|---|---|---|
| `src/functualize/_engine/validation.py` | Add `unexpected_keyword_error`. Pure, no engine imports | ~20 lines |
| `src/functualize/_engine/executor.py` | Move `ExecutionContext` construction above the prelude; insert the guarded check and its refusal branch | ~25 lines, plus a move |
| `tests/engine/test_launch_validation.py` | New. The rule's own table (R1's four rows) | new |
| `tests/workflow/test_launch_validation.py` | New. A1–A5 against a real gated walk | new |

`.spec/STATUS.md` gets the outcome at Verify, not here.

**Not touched:** `_engine/resolution.py`, `_engine/workflow_walker.py`,
`_primitives/state_store.py`, every plugin, every CLI module. If a diff reaches
any of those, the scope slipped.

---

## Dependencies

None external. No new package, no config key, no cache-format change — so
`CACHE_VERSION` stays where it is. The discovery cache is not consulted by this
path.

---

## Risks

### RK1 — Moving `ExecutionContext` construction (the real one)

Everything else is additive; this is the only existing line that moves.

*Why it should be safe:* the constructor is a plain dataclass call whose nine
arguments are all in scope at the earlier point, and the prelude's `run_step`
closure does not reference `context`.

*Why that is not enough:* "does not reference it" is a reading, and readings
are what this repository keeps catching. **Mitigation:** T2 lands the move
alone, with the workflow suite and the group-options combination matrix as its
gate, and a sabotage check proving those tests can actually fail. If the move
turns out not to be inert, fall back to RK1-B below rather than reshaping the
prelude to accommodate it.

*RK1-B (fallback):* leave construction where it is and refuse without firing
`AFTER_FAILURE`. Cheaper and lower-risk, but it breaks the hook parity R3
establishes, so it is a retreat to be **disclosed in `STATUS.md`**, not a
silent simplification.

### RK2 — The message must match exactly

A2 compares a plain job's exception to a workflow job's. `bind_partial`'s text
omits the `fn()` prefix (R1), so the wrapper supplies it. If CPython ever
rewords the message, the two sides still agree — both derive from the same
place — but the *literal* in any test asserting the string would drift.
**Mitigation:** assert parity between the two jobs, never against a hardcoded
string.

### RK3 — `function.__name__` on a wrapped callable

The message needs the name the user would see. `@workflow` is
identity-preserving (`decorated is original`, `workflow/_decorator.py`), and by
line 789 a lazy job has been materialized to its real function, so `__name__` is
correct on both paths. **Mitigation:** T4 covers a workflow reached cold
(materialized at invoke) as well as warm.

### RK4 — Nested workflows

A workflow reached as a `Step` is invoked with `kwargs={}` (`run_step`, executor
`:1113`), so the check is a no-op for it. **Mitigation:** an assertion in T4
that a nested gated walk still blocks and resumes, so "no-op" is proven rather
than reasoned.

### RK5 — Scope creation happens in `app.execute` before the engine is called

`FunctualizeApp.execute` creates an in-memory `WorkflowScope`
(`app/core.py:606-618`) before delegating. That is a registry entry, not a state
record — the persisted scope is written by the prelude's `WorkflowRunner`. The
contract's "the state store is not written" therefore holds, but the in-memory
registry will hold an entry for a refused launch. **Mitigation:** A1 asserts on
`StateStore`, which is the durable and externally observable half; T4 records
the in-memory registry's behavior explicitly so it is a documented consequence
rather than a surprise.

---

## Acceptance mapping

| Criterion | Task | Gate |
|---|---|---|
| A1 graph does not run | T3, T4 | `StateStore.get_scope` shows no steps, gates or position |
| A2 parity with a plain job | T3 | same status and exception type from `lab.parse` and `lab.release` |
| A3 DI-only workflows still run | T4 | `execute('lab.release')` reaches the gate |
| A4 refused resume disturbs nothing | T4 | scope record identical before and after |
| A5 `**kwargs` honoured | T1, T4 | rule table row; live walk |
| A6 reachability by sabotage | T5 | breaking the check makes A1 fail |
| A7 no regression | T5 | full suite, examples, plugins, ruff, mypy, lint-imports |
