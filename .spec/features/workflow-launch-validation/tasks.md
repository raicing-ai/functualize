# Tasks: Workflow Launch Validation

Wave ordering is binding: never start a task in wave N+1 while wave N has
unchecked tasks. Each task names its file scope `[F]`, its gate, and what proves
the gate can fail.

Reproduction fixture throughout: `examples/standalone/composition_lab/`, whose
`lab release` walk is
`parse → report → publish → bundle → [approval-gate] → check.signoff`.

---

## Wave 0 — the rule, and the move that makes room for it

### T1.1 — `unexpected_keyword_error` in `_engine/validation.py`

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

### T1.2 — Construct `ExecutionContext` above the workflow prelude

**[F]** `src/functualize/_engine/executor.py`

Move the `ExecutionContext(...)` construction (`:808`) to immediately before the
workflow-prelude block (`:789`). **No other change** — no check wired, no
behavior added. Every constructor argument is already in scope (R5).

This lands alone precisely because it is the feature's one risky move (RK1). A
diff that also introduces the check cannot tell a regression from the move apart
from a regression from the check.

**Gate:** `uv run pytest -k workflow` and
`tests/group_options/test_combination_matrix.py` green, and
`tests/workflow/test_gate_resume_surfaces.py` green.

**Sabotage:** pass a wrong `job_name` to the moved constructor; the workflow
suite must go red. If it does not, those tests do not cover the move and the
gate is wrong — say so rather than proceeding.

**If the move is not inert:** stop and take RK1-B (leave construction in place,
refuse without `AFTER_FAILURE`), and record the retreat in `STATUS.md`. Do not
reshape the prelude to accommodate the move.

---

## Wave 1 — the wiring

### T2.1 — Refuse an unbindable launch before the prelude walks

**[F]** `src/functualize/_engine/executor.py`

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

**Reachability:** the production call path is
`FunctualizeApp.execute` → `JobExecutionEngine.execute` → this branch. Verify by
breaking the branch and watching the `StateStore` assertion fail — not by
observing that a test calls the helper.

---

## Wave 2 — the rest of the acceptance surface

### T3.1 — Live acceptance tests against a gated walk

**[F]** `tests/workflow/test_launch_validation.py`

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

## Wave 3 — verification and disclosure

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
    { "id": 3, "tasks": ["4.1"] }
  ]
}
```
