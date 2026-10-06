# Persistence Port Status Typing — Tasks

Executor brief. Waves are binding (`spec-workflow.md` → *Execution
discipline*). Every gate below was authored against `master` @ `0502eda` in
its pre-state: green-form gates run green now and must stay green; red-form
gates state the hit count measured at authoring time and close when it is
zero. After each task, update `.spec/STATE.md`.

---

## 1.1 · `RunState` and the re-derived run table

- **After:** nothing (wave 0).
- **Files:** `src/functualize/_types/lifecycle.py`, `tests/types/test_lifecycle_tables.py`.
- **Does:** adds `RunState` (`StrEnum`, nine members — the stored spellings);
  `RUN.states` derives from `RunState`; `RUN.absorbing` derives through
  `RunStatus[s.name].terminal`; adds the total-mapping test
  (`RunState.__members__` names == `RunStatus.__members__` names) and the
  absorbing-set equivalence test. `_RUN_STATES`/`_RUN_TERMINAL` lower-casing
  derivation is deleted with this.
- **Production call path:** `RunStore.open_run` / `RunStore.close_run`
  (`_primitives/run_store.py:237,265`) read `RUN`'s sets on every stored run
  write; the read side reaches it via `_run_view`
  (`_primitives/document_store.py:258`). Breaking the absorbing derivation
  (e.g. dropping `refused` from it) must fail
  `tests/primitives/test_run_transitions.py`.
- **Gate (green form):** `uv run pytest tests/types/test_lifecycle_tables.py
  tests/primitives/test_transitions.py tests/primitives/test_run_transitions.py -q`
  — passes before (measured) and after.

## 1.2 · `StepStatus` promoted to `_types`

- **After:** nothing (wave 0).
- **Files:** `src/functualize/_types/lifecycle.py`, `src/functualize/_engine/frontier.py`, `src/functualize/_engine/workflow_walker.py`.
- **Does:** moves `StepStatus` from `frontier.py:113` to `lifecycle.py` as a
  `StrEnum`, values byte-identical; `frontier.py` imports it from `_types`;
  `workflow_walker.py`'s `StepStatus` import follows (its `_SCOPE_STATUS_FOR`
  dict is otherwise untouched). Deliberately **not** a fifth `Machine`.
- **Production call path:** `WorkflowWalker` writes step markers through
  `ScopeStore.record_step` (`workflow_walker.py:989-995`) and maps step →
  scope status through `_SCOPE_STATUS_FOR` (:998) on every failed/cancelled
  node; `_note_the_step_that_went_silent` writes `StepStatus.TIMED_OUT`.
  Sabotage: change one member's value and
  `tests/engine/test_workflow_walker*.py` must fail.
- **Gate (green form):** `uv run pytest tests/engine/ -q` (wave tier for the
  touched imports) plus `uv run lint-imports`.

## 2.1 · The port's ten annotations

- **After:** 1.1, 1.2.
- **Files:** `src/functualize/_types/persistence.py`,
  `tests/types/fixtures/runtime_store_conformance.py:43` (gate target — no edit
  expected; `plan.md` §3).
- **Does:** the §2 table of `spec.md` — ten fields typed, defaults become
  members; module imports the enums from `_types.lifecycle` (same package);
  field docstrings drop the now-redundant vocabulary spellings where the enum
  carries them. No `__all__` change, no new declarations in this module.
- **Production call path:** the port module is the vocabulary every layer
  imports; reached from all sites in `plan.md` §3.
- **Gate (red form → green):** the AST census (`plan.md` §2) reports zero
  `str`-annotated status fields (pre-state: 10, measured 2026-10-05).
  **Gate (green form):** `uv run mypy src/` and
  `uv run pytest tests/types/ -q` (the conformance fixture runs mypy over
  `tests/types/fixtures/runtime_store_conformance.py` and must report zero
  errors — this task alone makes `document_store.py`'s reader returns
  type-incorrect, which is why 3.2 shares its wave's completion gate with it:
  **2.1 + 3.2 land as one reviewable unit; 2.1 may merge only in the same
  change as 3.1–3.2.** Until then this task stays `[ ]` per *Transitional
  Changes*.)

## 3.1 · Recorders hand over members

- **After:** 2.1.
- **Files:** `src/functualize/_engine/recording/workflow_recorder.py`, `src/functualize/_engine/recording/input_recorder.py`, `src/functualize/_engine/recording/run_recorder.py`.
- **Does:** `step_completed` params → `StepStatus`/`ScopeStatus` with member
  defaults; `opened`/`suspended` `scope_status` → `ScopeStatus`; `finished`
  `status` → `AttemptStatus`. Pass-through bodies otherwise unchanged.
- **Production call path:** `opened` is live — the walk's gate path
  (`frontier.py:523`) and the answer surface (`app/_workflow_answer.py:331`).
  `step_completed`/`finished` have **no production caller** (the FUN-20
  recorded gap, `executor.py:264`): their gates are mypy + direct tests, and
  the reachability claim rides T11's wiring, which is sequenced **after**
  this feature (plan.md §4).
- **Gate (green form):** `uv run mypy src/`; `uv run pytest
  tests/engine/test_walk_claims_through_the_port.py
  tests/workflow/test_gate_drafts.py -q`.

## 3.2 · Document backend: strict parses and the derivation fix

- **After:** 2.1.
- **Files:** `src/functualize/_types/lifecycle.py` (adds `ATTEMPT_TO_RUN`),
  `src/functualize/_primitives/document_store.py`, `src/functualize/_primitives/gate_requests.py`, `src/functualize/_types/errors.py`,
  `src/functualize/app/_workflow_resume.py:55` (reads `request.status` — no edit
  expected; `plan.md` §3).
- **Does:** `_run_view`/`_workflow_view` parse strictly (`RunState(value)`,
  `ScopeStatus(value)`; the refusal message names value and vocabulary);
  `request_for` parses `InputRequestStatus(_status(record))`;
  `_complete_step`/`_suspend` consume typed fields unchanged;
  `_resume`/`_cancel` stamp members instead of `"running"`/`"cancelled"`
  literals; `_finish_attempt` records the attempt with `AttemptStatus`,
  transitions the attempt machine, and derives the run outcome via
  `ATTEMPT_TO_RUN` plus the record's cancellation flag instead of forwarding
  `cmd.status` to `close_run`; `InputRequestNotOpenError.status` becomes
  `InputRequestStatus`.
- **Production call path:** the document backend is the selected store —
  read projections reached via `RuntimeStore` readers (walk resolution
  `frontier.py:572-575`; resume envelope `app/_workflow_resume.py:55`); the
  apply path reached via the walk's claim/suspend/consume transactions.
  `_finish_attempt` itself has no production caller (T11, after this).
- **Gate (red form → green):** `rg -n '"running"\|"cancelled"'
  src/functualize/_primitives/document_store.py` restricted to the
  `_resume`/`_cancel` bodies returns nothing (pre-state: 2 hits, :930 and
  :967, measured). **Gate (green form):** `uv run pytest
  tests/primitives/test_document_runtime_store.py
  tests/primitives/test_gate_requests.py tests/types/ -q`; sabotage proof for
  the conflation fix: feed the old forwarding shape
  (`close_run(cmd.status)`) and `tests/primitives/test_run_transitions.py`
  must fail on `succeeded` not being in the run table.

## 4.1 · The walk and the answer surface pass members

- **After:** 3.1.
- **Files:** `src/functualize/_engine/frontier.py`, `src/functualize/app/_workflow_answer.py`.
- **Does:** `open_request`'s `scope_status` param becomes
  `ScopeStatus = ScopeStatus.BLOCKED` (the `WalkState.BLOCKED` default dies;
  `WalkState` itself stays — declared surviving smell); the answer surface's
  `opened(...)` call needs no edit unless mypy demands it (it passes no
  scope_status).
- **Production call path:** live — every gate a walk suspends on
  (`frontier.py:523` → `tx.workflows.suspend` → `_suspend` →
  `set_scope_status`) and every reopen (`app/_workflow_answer.py:331`).
- **Gate (green form):** `uv run pytest
  tests/engine/test_walk_claims_through_the_port.py
  tests/integration/test_crash_and_resume.py -q`; `uv run mypy src/`.

## 4.2 · Fixtures and typed assertions

- **After:** 3.2.
- **Files:** `tests/types/test_gate_resolution_values.py`, `tests/types/test_runtime_store_port.py`, `tests/primitives/test_document_runtime_store.py`.
- **Does:** `InputRequest(..., status=InputRequestStatus.OPEN)` (the one
  constructor literal, `test_gate_resolution_values.py:87`); typed assertion
  beside `error.status == "accepted"` (`test_runtime_store_port.py:134` —
  by-value, stays green either way; add an `is InputRequestStatus.ACCEPTED`
  form); projection assertions for the strict parses where
  `test_document_runtime_store.py` asserts statuses today.
- **Production call path:** tests only (no production claim).
- **Gate (green form):** `uv run pytest tests/types/ tests/primitives/ -q`.

## 4.3 · Reference doc points at the resolution

- **After:** 3.2.
- **Files:** `contributor/reference/runtime-persistence-data-model.md`.
- **Does:** §1.1's conflation paragraph ("`FinishAttempt.status` speaks the
  run-outcome vocabulary … `_finish_attempt` never transitions the attempt
  machine") gains its resolution pointer — the derivation now lives in
  `_types/lifecycle.py` (`ATTEMPT_TO_RUN`) and the backend transitions the
  attempt machine; "ATTEMPT is enforced where the relational writer lands"
  is updated to say where enforcement landed. §1.2's lower-casing note gains
  the `RunState` pointer.
- **Production call path:** none (reference prose).
- **Gate (green form):** `uv run pytest tests/test_contributor_docs.py -q`.

---

## Deliberately out of scope (recorded, not forgotten)

- `WalkState` retirement and the store-level scope-status writers
  (`workflow_walker.py`, `frontier.py` entry stamps, `executor.py:1068`,
  `app/_workflow_control.py:446`) — no port surface; engine-internal
  vocabulary work (plan.md §3, §6).
- `RunQuery`/`WorkflowQuery` construction sites — none exist (verified); the
  typing rides the annotations alone.
- A run-close command for `blocked`/`timeout`/`refused` — the relational
  writer's wave settles it (ADR-031 records the boundary).

## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["1.1", "1.2"]}, {"id": 1, "tasks": ["2.1"]}, {"id": 2, "tasks": ["3.1", "3.2"]}, {"id": 3, "tasks": ["4.1", "4.2", "4.3"]}]}
```
