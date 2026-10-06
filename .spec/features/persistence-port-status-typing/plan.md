# Persistence Port Status Typing — Plan

Implements [ADR-031](../../../contributor/adr/031-persistence-port-status-is-typed.md)
(extends [ADR-026](../../../contributor/adr/026-persistence-ports-need-no-new-layer.md)).
Retrieved from `master` @ `0502eda`, 2026-10-05, 17:45–18:40 CEST.

**Skills consulted** (per the architecture gate's rule to record what was
actually loaded): the in-repo `.claude/skills/python-design-patterns` (KISS,
separation of concerns, single responsibility — the principles half) and the
user-level `design-patterns-refactoring` skill, which carries the
Refactoring.Guru catalogue the smell names below come from (*Primitive
Obsession* → ch32; *Shotgun Surgery* → ch34; *Middle Man* → ch36; definitions
verified in the chapters, not taken from the listing).

## 1. Architecture gate — BEFORE and AFTER

The region is the persistence port's status surface: one `_types` module
declaring it, the `_engine` recorders and walk producing it, the `_primitives`
backend storing and projecting it. Layer positions and dependency directions
are the constitution's; the import-linter contracts decide the AFTER's
legality, and no arrow below reverses.

```
BEFORE (today, master @ 0502eda)

  _types/lifecycle.py        ScopeStatus/AttemptStatus/InputRequestStatus StrEnums,
        ▲                    machines SCOPE/RUN/ATTEMPT/INPUT_REQUEST, no RunState,
        │                    no StepStatus (it lives in _engine)
        │ imports
  _types/persistence.py      port: 10 status fields, all bare str
        ▲
        │ imports (legal: every layer may import _types)
  _engine/frontier.py        WalkState (own str class) + StepStatus (own str class)
  _engine/recording/*        recorders pass str through → port commands
  _engine/workflow_walker.py _SCOPE_STATUS_FOR: dict[str, str]
        │
        ▼ imports
  _primitives/document_store.py   applies commands → ScopeStore.set_scope_status
  _primitives/gate_requests.py    derives InputRequest.status as str
  _primitives/{scope_store,run_store}.py   require_transition — the choke point

  Cross-boundary facts: status TEXT crosses every boundary as an untyped str;
  the enum vocabulary exists but stops at the port's door. The engine keeps
  two private str vocabularies (WalkState, StepStatus) for values the
  lifecycle module already names.

AFTER (this feature)

  _types/lifecycle.py        + RunState (stored run vocabulary; RUN derives
        ▲                      states/absorbing from it, terminal via RunStatus)
        │                      + StepStatus (promoted from _engine)
        │                      + ATTEMPT_TO_RUN mapping (data, §1.2's derivation)
        │ imports
  _types/persistence.py      port: the same 10 fields, typed with the four
        ▲                      lifecycle enums; defaults are members
        │ imports
  _engine/frontier.py        imports StepStatus from _types; open_request hands
  _engine/recording/*        ScopeStatus members; recorders typed, pass members
  _engine/workflow_walker.py (unchanged — store-level writer, out of scope)
        │
        ▼ imports
  _primitives/document_store.py   read projections parse (RunState(value),
  _primitives/gate_requests.py    ScopeStatus(value), InputRequestStatus(value));
                                  _finish_attempt derives the run outcome
  _primitives/{scope_store,run_store}.py   UNCHANGED — require_transition stays
                                  the one refusal; params stay honestly `str`

  What crosses a boundary now: typed values downstream (engine → port →
  backend), and text exactly twice — into the JSON documents (StrEnum
  serializes as its value) and back out at the read projection's strict parse.
  No contract in pyproject.toml moves: every arrow keeps its direction.
```

The AFTER introduces no new layer, no peer import, and no public-surface
change — it narrows types on an internal port. Checked against the forbidden
list: no god-object growth (the port module gains annotations only), no ABC,
no global state, no `_cli` involvement.

## 2. The count, by the command that would falsify it

Constitution rule: a count is an AST question. The census command, run at
authoring time (output: the ten rows in `spec.md` §1):

```bash
uv run python - <<'EOF'
import ast, pathlib
tree = ast.parse(pathlib.Path("src/functualize/_types/persistence.py").read_text())
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                if "status" in stmt.target.id:
                    print(f"{stmt.lineno:4d} {node.name}.{stmt.target.id}: {ast.unparse(stmt.annotation)}")
EOF
```

Negative claims verified the same way: `rg -n 'RunQuery\(|WorkflowQuery\(' src/
plugins/ tests/ examples/` → only the reader signatures in
`document_store.py` (zero constructors — the queries are port vocabulary with
no caller yet); `rg -ln 'WorkflowView|InputRequest|RunView|RuntimeStore'
plugins/` → zero hits (no plugin implements the protocols or reads these
fields — the earlier belief that functualize-mcp did does not survive the
search).

## 3. The ripple, from retrieval — every site that writes or reads a port status field

Writers and pass-throughs (port fields constructed or forwarded):

| Site | Field(s) | Production caller today? |
|---|---|---|
| `_engine/recording/workflow_recorder.py:81-115` (`step_completed`, `status`/`scope_status` params) → `CompleteStep` :103 | 1, 2 | **no** — the FUN-20 recorded gap (`executor.py:264` names it) |
| `_engine/recording/input_recorder.py:54-86` (`opened`, `scope_status` param :62) → `SuspendAtGate` :74 | 3 | **yes** — the walk's gate path and the answer surface |
| `_engine/recording/workflow_recorder.py:117-148` (`suspended`) → `InputRecorder().opened` :137 | 3 | no (pass-through to the gap above) |
| `_engine/recording/run_recorder.py:64-95` (`finished`, `status` param :69) → `FinishAttempt` :82 | 4 | **no** — T11's wiring |
| `_engine/frontier.py:505-537` (`open_request`, `scope_status` param :509, default `WalkState.BLOCKED`) → `tx.workflows.suspend` :536 | 3 | **yes** — the gate suspend path |
| `app/_workflow_answer.py:331-342` (`InputRecorder().opened`, default scope_status) | 3 | **yes** — the reopen path |

Read projections and parse sites:

| Site | Field | Note |
|---|---|---|
| `_primitives/document_store.py:257-268` (`_run_view`, `status=str(record.get("status", "running"))` :262) | 7 | also `:225` (`recent`), `:234` (`tree`/`_tree`) call it |
| `_primitives/document_store.py:330-352` (`_workflow_view`, :335) | 8 | also `:282` (`resumable` — filter compares `query.status` :303), `:275` (`workflow`) |
| `_primitives/document_store.py:202` (`recent` — `query.status` filter) | 9 | zero external constructors |
| `_primitives/gate_requests.py:332-345` (`request_for`, `status=_status(record)` :337; derivation `_status` :92, `_legacy_status` :79) | 6 | the document backend **derives** this status — the parse lands here |
| `app/_workflow_resume.py:55` (`request.status` into the result envelope) | 6 | the one production reader of a port field outside the backend; in task 3.2's file scope, whose `request_for` parse narrows the value it reads — no edit expected (it lands in a `dict[str, Any]` envelope, and a `StrEnum` member is a `str`) |

Apply path (backend consumes the fields):

| Site | Field | Note |
|---|---|---|
| `_primitives/document_store.py:871-889` (`_complete_step`: `cmd.status` :876 → `record_step`; `cmd.scope_status` :883 → `set_scope_status`) | 1, 2 | |
| `_primitives/document_store.py:891-911` (`_suspend`: `cmd.scope_status` :907) | 3 | |
| `_primitives/document_store.py:913-932` (`_resume`: literal `"running"` :930) | — (backend stamp) | literal → member, same task |
| `_primitives/document_store.py:951-970` (`_cancel`: literal `"cancelled"` :967) | — (backend stamp) | literal → member, same task |
| `_primitives/document_store.py:1022-1063` (`_finish_attempt`: `cmd.status` → attempts :1039/:1047 **and** `close_run` :1060) | 4 | the recorded §1.1 conflation; the typing forces the derivation fix |
| `_types/errors.py:172-190` (`InputRequestNotOpenError.status`) | 6 | annotation widens to `InputRequestStatus` |

Out of scope, declared (store-level writers of the same *column*, never of a
port field; the choke point guards them): `workflow_walker.py:451,567,757,998`
(`WalkState`/`_SCOPE_STATUS_FOR` :1083), `frontier.py:373,375,439`,
`executor.py:1065`, `app/_workflow_control.py:446` (literal `"cancelled"`).
Their vocabulary cleanup is engine-internal work with no port surface; this
feature does not pay for it.

Test fixtures handing status values to port fields (from
`rg -n 'status=' tests/` over the port-constructor files):

| Site | Note |
|---|---|
| `tests/types/test_gate_resolution_values.py:82-90` (`InputRequest(..., status="open")`) | the one literal into a constructor |
| `tests/primitives/test_document_runtime_store.py:344-357` (`SuspendAtGate(...)`, default scope_status) | exercises `_suspend` |
| `tests/types/test_runtime_store_port.py:134` (`error.status == "accepted"`) | by-value; stays green |
| `tests/types/fixtures/runtime_store_conformance.py:43` (`takes_the_port(store)`, the store-to-port assignment) | mypy signature conformance — the file that pins the typing for implementers; in task 2.1's file scope, whose gate runs mypy over it — no edit expected (`contracts.md` §5: protocol signatures unchanged) |
| `tests/engine/test_walk_claims_through_the_port.py`, `tests/primitives/test_transitions.py`, `tests/types/test_lifecycle_tables.py`, `tests/primitives/test_gate_requests.py`, `tests/integration/test_crash_and_resume.py`, `tests/integration/test_notify_exactly_once.py`, `tests/engine/test_run_record.py`, `tests/workflow/test_gate_drafts.py`, `tests/_support/engine_storage.py`, `tests/core/test_store_capability_refusal.py`, `tests/primitives/test_one_substrate_choice.py` | reference the port types; each lands in a task's file scope only if its imports change |

## 4. The choke point and the already-dispatched work

`ScopeStore.set_scope_status` (`_primitives/scope_store.py:416`) is where
legality is decided for scope status; `RunStore.open_run`/`close_run`
(`_primitives/run_store.py:237,265`) for run status. **The parse stays at the
port's read boundary and the check stays at the store's write** — they were
never the same decision. Concretely:

- The `str → enum` parse moves to the read projections (`_run_view`,
  `_workflow_view`, `request_for`). It does not move into `ScopeStore` and it
  does not disappear: the documents are JSON text, so every backend parses
  once per read, at its own boundary.
- The legality check does not move and does not disappear: `require_transition`
  keeps auditing every stored write inside the batch that writes it. Its
  by-value membership (`ScopeStatus.BLOCKED == "blocked"`) is what makes the
  typing invisible to it — no store change is required or made.
- The alternative the plan once carried — parse at the choke point — is the
  design the maintainer's answer removed, and it only ever covered scope
  status anyway.

**Wave implication for the dispatched runtime-schema work.** T1 (tables), T4
(refusal) and T6 (store writers) are landed and untouched by this feature —
the machines keep their pairs, the refusal keeps its single home. The typing
must land **before** the port's recorder wiring (FUN-20/T11, the recorded gap
that `step_completed`/`suspended`/`finished` have no caller): wiring the
recorders first would mint production call sites passing literals, which this
feature would then have to re-educate. FUN-19's relational writer lands after
either — it inherits typed reads for free and settles the run-close boundary
ADR-031 records. Ordered: **this feature → T11 wiring → FUN-19 tables.**

## 5. Risks

- **Strict parse turns hand-edited documents into refusals.** Deliberate
  (ADR-031, Negative): a coerced status is the drift being ended. The refusal
  names value and vocabulary. Migration risk is nil — every value both
  vocabularies express serializes byte-identically.
- **`_finish_attempt`'s derivation is new code on a port with no production
  caller.** The behaviour change is real but reaches nothing until T11 wires
  the recorders; the attempt→run mapping is data with a table test, and the
  run-close boundary (blocked/timeout/refused) is recorded, not invented.
- **The `RunState ↔ RunStatus` name mapping could drift.** Guarded by the
  total-mapping assertion in the table tests; the derivation through
  `RunStatus[s.name].terminal` keeps terminality single-sourced.
- **`StepStatus` promotion touches `_engine/frontier.py` imports.** Values are
  byte-identical, so behaviour risk is nil; the import direction
  (`_engine → _types`) is the legal one.

## 6. Surviving smells

Catalogue names from the Refactoring.Guru catalogue (see §Skills). One
**before** smell is the feature's reason to exist; the AFTER is checked for
what it introduces; what survives is declared.

- **Before — *Primitive obsession*** (`_types/persistence.py`, all ten status
  fields; "bare primitives for domain concepts", ch32): the smell the
  maintainer declined to accept. This feature is *Replace Type Code with
  Class/Enum* applied to the port.
- **Before — *Divergent change* (adjacent, recorded, not paid here)**: the
  engine keeps `WalkState` and, until wave 0, `StepStatus` as private str
  vocabularies for values `_types/lifecycle.py` names — two files change when
  one vocabulary changes. The AFTER removes the `StepStatus` half; the
  `WalkState` half survives, declared below.
- **Introduced by the AFTER and accepted — *Shotgun surgery* (mild)**: adding
  a status value now touches the enum in `_types/lifecycle.py` and, if the
  machine changes, its transition table — two places in one module, plus the
  compiler finds every affected site. Before, one place existed and found
  nothing. The compiler-visible version is the cheaper one.
- **Introduced by the AFTER and accepted — a second run enum** (`RunState`
  beside `RunStatus`): a name-mapped pair that must stay total. The mapping
  test is the guard; the alternative (case translation at every boundary) is
  the worse tax. Recorded in ADR-031.
- **Surviving, needs no maintainer review**: `WalkState` (engine-internal walk
  markers, guarded by the choke point, no port surface);
  `ScopeStore.set_scope_status`/`RunStore.*` staying `str`-annotated (a
  `StrEnum` member *is* a `str` — the annotation is true and the store layer
  is not the port); `IllegalTransition` keeping `str` fields (it reports pairs
  the vocabulary may not name, which is its job).
- **None flagged for maintainer review.** Every accepted compromise above is
  either ADR-031's own recorded decision or a no-port-surface leftover whose
  cleanup is engine-internal work.
