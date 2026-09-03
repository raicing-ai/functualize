# Tasks: Workflow Launch Validation

Wave ordering is binding: never start a task in wave N+1 while wave N has
unchecked tasks. Each task names its file scope `[F]`, its gate, and what proves
the gate can fail.

Reproduction fixture throughout: `examples/standalone/composition_lab/`, whose
`lab release` walk is
`parse → report → publish → bundle → [approval-gate] → check.signoff`.

---

## Wave 0 — the rule, and the move that makes room for it

### [x] T1.1 — `unexpected_keyword_error` in `_engine/validation.py`

**[F]** `src/functualize/_engine/validation.py`,
`tests/engine/test_launch_validation.py`

Add a module-level function beside `ArgValidator`:

```python
def unexpected_keyword_error(
    function: Callable[..., Any], kwargs: Mapping[str, Any]
) -> TypeError | None:
```

Returns a `TypeError` when `kwargs` names a keyword `function` cannot accept,
`None` otherwise. Delegates the decision to
`inspect.signature(function).bind_partial(**kwargs)` and, on its `TypeError`,
returns `TypeError(f"{function.__name__}() {exc}")` so the wording matches a
real call's (R1). It must import nothing from the engine — the rule is about a
callable and a dict.

**Gate:** the four rows of R1's table, as a parametrised test —
unexpected keyword rejected; `**kwargs` accepts anything; a missing
DI-shaped argument tolerated; an accepted keyword passes. Plus one asserting the
message carries the `fn()` prefix.

**Sabotage:** replace the body with `return None`; the rejection rows must fail.
Commit before sabotaging.

### [x] T1.2 — Construct `ExecutionContext` above the workflow prelude

**[F]** `src/functualize/_engine/executor.py`,
`tests/engine/test_lifecycle_order.py`,
`contributor/reference/execution-lifecycle.md`

> **The gate below was wrong as authored, and its own escape hatch caught it.**
> The original `[F]` was `executor.py` alone and the original gate was
> `-k workflow` + the combination matrix + `tests/workflow/`. Under sabotage
> (a corrupted `job_name` on the moved constructor) that selection stayed
> **70 passed** — it does not observe the moved line at all.
>
> Widening the sabotage to `tests/engine/ tests/config/ tests/execution/`
> turned **7 red**, one of them
> `test_lifecycle_order.py::test_the_method_follows_the_documented_sequence` —
> the test `AGENTS.md` names as failing "if the sequence moves", which is
> precisely this move. Run against the *unsabotaged* move it was **already
> red**: the move reorders steps 2 and 3 of a pinned twenty-step contract.
>
> So the move needs `execution-lifecycle.md` and the test's `_DOCUMENTED_ORDER`
> updated with it — the page states *why* each step sits where it does, and the
> test's failure message asks for that page in the same commit. Both are now in
> the `[F]` above. Recorded rather than silently corrected, per
> *Acceptance Gates*: the file scope must equal the gate's hit set, and deriving
> it from prose is exactly how it came out wrong.

Move the `ExecutionContext(...)` construction (`:808`) to immediately before the
workflow-prelude block (`:789`). **No other change** — no check wired, no
behavior added. Every constructor argument is already in scope (R5).

This lands alone precisely because it is the feature's one risky move (RK1). A
diff that also introduces the check cannot tell a regression from the move apart
from a regression from the check.

**Gate (corrected):** `uv run pytest tests/engine/ tests/config/
tests/execution/ tests/group_options/test_combination_matrix.py tests/workflow/`
green. `tests/engine/test_lifecycle_order.py` is the load-bearing member — it is
the only one that observes a *reorder* rather than merely a behaviour.

**Sabotage:** pass a wrong `job_name` to the moved constructor; the gate must go
red. Against the corrected selection it turns **6 red** (4 in
`test_unified_config_integration.py`, 2 in `test_runcontext_log_sink.py`) — the
moved line feeds the config-view section, the `RunContext` name and the job
logger, and all three are observed. Against the *original* selection it stayed
**70 passed**, which is what exposed the gate rather than the code.

The count was 7 before `_DOCUMENTED_ORDER` was corrected;
`test_lifecycle_order.py` now passes under this sabotage because corrupting a
*value* is not reordering a *step*. Both numbers are recorded because the
difference between them is the point: one test in that selection watches the
order and six watch the value, and only the order test bears on the move
itself.

**If the move is not inert:** stop and take RK1-B (leave construction in place,
refuse without `AFTER_FAILURE`), and record the retreat in `STATUS.md`. Do not
reshape the prelude to accommodate the move.

---

## Wave 1 — the wiring

### [x] T2.1 — Refuse an unbindable launch before the prelude walks

**[F]** `src/functualize/_engine/executor.py`,
`tests/workflow/test_launch_validation.py`,
`tests/engine/test_unexpected_keyword.py` *(rename only)*

> **`[F]` widened, disclosed.** As authored it named `executor.py` alone while
> its gate was A1 and A2 — criteria that cannot be met without a test file. The
> same authoring error as T1.2's: scope derived from prose, gate derived from a
> separate reading.
>
> The rename is incidental and real: `tests/engine/test_launch_validation.py`
> (T1.1) collided on basename with the new `tests/workflow/` file, and neither
> directory carries an `__init__.py`, so pytest refused to collect both. T1.1's
> isolated run could not have seen it. Renamed to `test_unexpected_keyword.py`.
>
> One departure from the plan, deliberate: `_failure_before_execution` was
> **extracted and shared** with the existing `ValidationError` handler rather
> than duplicated. The plan said "return through the established refusal shape";
> copying ~28 lines to do that would have created the second implementation this
> codebase keeps writing ADRs about. The config-integration tests observe that
> handler (they go red under T1.2's sabotage), so the extraction is covered.

Between the moved `ExecutionContext` and the prelude block, when
`getattr(function, "__functualize_workflow__", None)` is not `None`, call
`unexpected_keyword_error(function, kwargs)`. On a returned error, return
through the refusal shape the config-validation handler already establishes
(R4): fire `AFTER_FAILURE` with the error, **do not** fire `PRE_EXECUTE`, emit
`job.execute.end` with `status="failure"`, and return
`JobResult(status=RunStatus.FAILURE, return_value=None, exception=<the
TypeError>, job_name=job_name, duration_ms=...)`.

Gated on the workflow marker deliberately: a plain job's `TypeError` already
arrives correctly and re-checking it here would change its hook sequence.

**Gate (A1, A2):**
- `app.execute('lab.release', scope_id=<fresh>, zzz_nonsense=1)` returns
  `FAILURE`, **and** `StateStore.get_scope(<fresh>)` shows empty `steps`, empty
  `gates`, and `position is None`.
- `lab.parse` and `lab.release` given the same bad kwarg return the same status
  and the same exception type, and both messages name the function and the
  argument. Assert the two against **each other**, never against a hardcoded
  string (RK2).

**Reachability — verified.** The production call path is
`FunctualizeApp.execute` → `JobExecutionEngine.execute` → `_execute_lifecycle` →
the `declaration is not None` branch → `unexpected_keyword_error` →
`_failure_before_execution`.

**Sabotage** (`if False:` on the branch): **3 failed, 9 passed** — A1 and both
A2 cells. The control cell (a clean launch reaching the gate) correctly stayed
green, and so did T1.1's eight rule tests, which do not depend on the wiring.
That split is the evidence the gate observes the *integration* and not just the
component. Restored clean.

---

## Wave 2 — the rest of the acceptance surface

### [x] T3.1 — Live acceptance tests against a gated walk

**[F]** `tests/workflow/test_launch_validation.py`

> **A3 landed early**, in T2.1, as the clean-launch control beside A1 — an A1
> that only asserted "no steps ran" would be satisfied by an implementation
> refusing *every* launch, so the control had to ship with it rather than a
> wave later. Not a scope slip; recorded so the mapping table stays honest.
>
> **Result: 11 cells, all green.** Sabotage (`if False:` on the engine branch):
> **8 failed, 3 passed**. The three survivors are exactly the cells asserting
> normal operation — the clean-launch control, `**kwargs`, and the clean nested
> resume — and every cell asserting a refusal failed. That split is the
> evidence that none of them is vacuous.

- **A3** — `app.execute('lab.release')` with no arguments reaches
  `approval-gate` and returns `BLOCKED`. Proves the launch check did not become
  a completeness check over DI parameters.
- **A4** — against a scope blocked at `approval-gate` whose payload has been
  deposited, a launch carrying a bad kwarg returns `FAILURE` and leaves
  `status`, `steps`, `gates` and `position` identical. Snapshot the scope record
  before and after and compare the whole dict.
- **A5** — a workflow whose function declares `**kwargs` accepts an arbitrary
  argument and walks its graph.
- **RK3** — the same refusal on a **cold** boot, where the job is materialized
  at invoke, so `function.__name__` is exercised on both the lazy and warm
  paths.
- **RK4** — a nested workflow reached as a `Step` still blocks and resumes; the
  check is a no-op for it because `run_step` passes `kwargs={}`.
- **RK5** — record what `FunctualizeApp`'s in-memory `_scope_registry` holds
  after a refused launch. Whatever it is, assert it, so the consequence is
  documented rather than discovered later.

**Gate:** all six pass. A4 is the one that matters most — it is the case where a
human approval has already been spent.

**Sabotage:** revert T2.1's branch; A1 and A4 must both fail.

---

## Wave 3 — the correction the full suite forced

### [x] T4.2 — A config model's field names are legitimate launch arguments

**[F]** `src/functualize/_engine/validation.py`,
`src/functualize/_engine/executor.py`,
`tests/workflow/test_launch_validation.py`

**Not in the original plan.** T4.1's full-suite run failed two cells of
`tests/cli/test_unknown_mode_gate_flags_e2e.py` with

```
TypeError: trip_planner() got an unexpected keyword argument 'city'
```

`--city` is a **config-model field**, not a signature parameter.
`_resolve_config_model` (`executor.py:2317-2322`) pops every name in
`config_class.model_fields` out of `call_kwargs` and replaces them with the
built model — so those names are legitimate at launch and are consumed later.

This refutes `research.md` R2's conclusion that "membership in the signature is
the whole question". It is not: the acceptable set is the signature **plus what
later stages consume**. Today exactly one stage consumes anything, and both
sides now read `model_fields`, so they are one decision rather than two
opinions. `also_accepts` carries it.

Group options are unaffected and were checked rather than assumed:
`_resolve_group_options` reads the dedicated `group_option_values` parameter
(`executor.py:2122`), never `call_kwargs`.

**Why the feature's own tests could not catch it:** every A1–A5 fixture declares
a DI-only workflow (`walk(log: Log)`) with no config model. The one shape that
mattered was the one shape absent. Three cells added — a config field accepted
and reaching the walk, an unknown name still refused, and the plain job beneath
it answering identically.

**Gate:** `tests/workflow/test_launch_validation.py` +
`tests/engine/test_unexpected_keyword.py` +
`tests/cli/test_unknown_mode_gate_flags_e2e.py` → **24 passed**.

---

## Wave 4 — verification and disclosure

### T4.1 — Full regression and STATUS entry

**[F]** `.spec/STATUS.md`

**Gate (A7):**

| Check | Command |
|---|---|
| Full suite | `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto` |
| Examples | `uv run pytest examples/` |
| Plugin suites | all 11 |
| Lint | `uv run ruff check` + `format --check` (src, tests, examples, plugins) |
| Types | `uv run mypy src/` |
| Imports | `uv run lint-imports` |

Then write the outcome into `STATUS.md`: what shipped, the A1/A4 reproductions,
and — if RK1-B was taken — the hook-parity retreat, named as a retreat.

Disclose any transitional state rather than disguising it. If a `[F]` list was
exceeded anywhere, say where; the process note in `STATUS.md` records that
findings fixed outside a task's file scope are exactly what the `[F]` discipline
exists to surface.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.2"] },
    { "id": 4, "tasks": ["4.1"] }
  ]
}
```
