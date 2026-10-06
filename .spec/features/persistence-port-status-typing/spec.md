# Persistence Port Status Typing — Spec

Design pass for the maintainer's 2026-09-26 answer "type the port for the
second one" (declining the *Primitive obsession* acceptance). The decision it
implements is [ADR-031](../../../contributor/adr/031-persistence-port-status-is-typed.md),
which extends [ADR-026](../../../contributor/adr/026-persistence-ports-need-no-new-layer.md).
Census measured on `master` @ `0502eda`, 2026-10-05: **ten** status-bearing
fields on the port, not the nine of the 2026-09-26 snapshot —
`SuspendAtGate.scope_status` landed with the gate-lifecycle wave in between.

## 1. The port's fields carry their lifecycle status types

Every status-bearing field in `src/functualize/_types/persistence.py` is
annotated with the enum whose member is the text the store writes for it:

| # | Field | Becomes |
|---|---|---|
| 1 | `CompleteStep.status` | `StepStatus` (promoted to `_types/lifecycle.py`) |
| 2 | `CompleteStep.scope_status` | `ScopeStatus` |
| 3 | `SuspendAtGate.scope_status` | `ScopeStatus` |
| 4 | `FinishAttempt.status` | `AttemptStatus` |
| 5 | `Attempt.status` | `AttemptStatus` |
| 6 | `InputRequest.status` | `InputRequestStatus` |
| 7 | `RunView.status` | `RunState` (new) |
| 8 | `WorkflowView.status` | `ScopeStatus` |
| 9 | `RunQuery.status` | `RunState \| None` |
| 10 | `WorkflowQuery.status` | `ScopeStatus \| None` |

No field is excepted. Defaults become members (`ScopeStatus.RUNNING`,
`ScopeStatus.BLOCKED`, `StepStatus.SUCCESS`).

**Acceptance.**
- AST walk of the module reports zero `str`-annotated status fields; the
  command that must pass: the census walk in `plan.md` §2, with every row of
  its output naming one of the four lifecycle enums (or `None`-unioned query
  forms of them).
- `uv run mypy src/` passes with the port's implementers and consumers
  converted — any site still handing a foreign vocabulary is a type error, not
  a review finding.
- `tests/types/fixtures/runtime_store_conformance.py` still type-checks with
  zero errors (`tests/types/test_runtime_store_port.py` runs it).

## 2. The two vocabulary moves precede the typing

- **`RunState`** — new `StrEnum` in `_types/lifecycle.py`, nine members, the
  stored spellings (`success`, `failure`, `blocked`, `skipped`, `running`,
  `cancelled`, `timeout`, `unknown`, `refused`). `RUN.states` derives from it;
  `RUN.absorbing` derives through `RunStatus[s.name].terminal`, so terminality
  keeps its one definition. A test asserts the `RunState ↔ RunStatus` name
  mapping is total. `RunStatus` is unchanged and stays the display enum.
- **`StepStatus`** — moves from `_engine/frontier.py:113` to
  `_types/lifecycle.py` as a `StrEnum`, values byte-identical
  (`success`, `failed`, `timed_out`, `cancelled`). It is a marker vocabulary,
  deliberately **not** a fifth `Machine` (a step record is written once, with
  its outcome; there is nothing to transition). `_engine/frontier.py` imports
  it from `_types`; consumers follow the import.

**Acceptance.** `tests/types/test_lifecycle_tables.py` passes with the
re-derived run table and the added mapping assertions;
`tests/primitives/test_transitions.py` passes unchanged (the tables' pairs are
the same set).

## 3. Producers hand over members, not literals

Every production site that writes one of the ten fields hands over an enum
member. From retrieval (full hit set with lines in `plan.md` §3): the three
recorders, the frontier's gate-suspend path, the document backend's apply path
and read projections, and the gate-request read projection. The engine's
*store-level* writers that bypass the port (`workflow_walker.py`,
`frontier.py`'s entry stamps, `executor.py:1068`,
`app/_workflow_control.py:446`) are **out of scope** — they write the same
stored column but never touch a port field; the choke point guards them and
their cleanup is the engine's own vocabulary work, not this feature's.

**Acceptance.** For each in-scope site: the parameter or expression is typed
by the enum; `grep` for the replaced string literals at the converted sites
returns nothing (gate commands are per-task in `tasks.md`, each run at
authoring time of its task).

## 4. The document backend parses at its read projection, strictly

- `_run_view` produces `RunState(value)`; `_workflow_view` produces
  `ScopeStatus(value)`; `gate_requests.request_for` produces
  `InputRequestStatus(value)`.
- The parse is **strict**: a stored value the vocabulary does not name refuses
  the read (the existing malformed-record discipline — never invent). The
  refusal names the value and the vocabulary.
- `_finish_attempt` stops forwarding `cmd.status` to `close_run`. It
  transitions the attempt record with `AttemptStatus` and derives the run
  outcome from the attempt status plus the run record's cancellation flag,
  using an attempt→run projection that is **data** in `_types/lifecycle.py`.
  Run states no attempt implies (`blocked`, `timeout`, `refused`, `unknown`)
  stay the store-level `RunStore.close_run`'s to write; the port does not
  express them yet (ADR-031 records the boundary).
- `_resume` and `_cancel` stamp members (`ScopeStatus.RUNNING`,
  `ScopeStatus.CANCELLED`) instead of literals.
- `InputRequestNotOpenError` carries `InputRequestStatus`.

**Acceptance.** `tests/primitives/test_document_runtime_store.py` and
`tests/primitives/test_gate_requests.py` pass with typed assertions added for
each projection; a sabotage run (feed `close_run` `"succeeded"` through the
old forwarding path) fails, proving the conflation is gone.

## 5. The choke point and the already-dispatched work are untouched

`ScopeStore.set_scope_status`, `RunStore.open_run` and `RunStore.close_run`
keep their `require_transition` calls and their `str` annotations (a `StrEnum`
member *is* a `str`). The runtime-schema work that landed (T1 tables, T4
refusal, T6 writers) is unchanged by this feature; the waves below place the
typing **before** the port's recorder wiring (the FUN-20/T11 gap), so the
recorders are wired typed and no new call site is born passing literals.

**Acceptance.** `uv run lint-imports` reports 7 kept, 0 broken;
`tests/primitives/test_transitions.py` passes without modification; the
diff touches no `_primitives/scope_store.py` or `_primitives/run_store.py`
writer body.

## 6. No behaviour change beyond the recorded conflation fix

Reads, writes, transitions, refusals and stored bytes are identical to today's
for every value both vocabularies can express — `StrEnum` members serialize as
their text, so documents on disk do not change shape. The one behavioural
correction is §4's: `finish_attempt` (no production caller today — the FUN-20
gap) stops speaking run vocabulary through an attempt field. Existing tests
that assert by value (`error.status == "accepted"`) stay green unchanged.

**Acceptance.** Step tier green; `tests/spec` green;
`contributor/reference/runtime-persistence-data-model.md` §1.1's conflation
note updated to point at its resolution.
