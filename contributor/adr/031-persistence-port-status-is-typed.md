# ADR-031: The Persistence Port's Status Fields Carry the Lifecycle Status Types

**Status**: accepted
**Date**: 2026-10-05
**Deciders**: maintainer, by the 2026-09-26T13:06:21Z answer "type the port for
the second one", declining the *Primitive obsession* acceptance the
`runtime-schema-migrations` plan had carried; design pass recorded here.

## Context

ADR-026 fixed where the persistence ports live and shaped their surface. It
said nothing about the *types* the surface's status-bearing fields carry, and
they landed as bare `str`. The 2026-09-26 snapshot of
`src/functualize/_types/persistence.py` held nine of them; the tree at the time
of this decision holds **ten** — `SuspendAtGate.scope_status` arrived with the
gate-lifecycle wave after the snapshot was taken. The full census, by AST walk
(`python -c` over `ast.parse`, not a regex, per the constitution's rule that a
count about syntax is an AST question):

| Field | Line | Today | Vocabulary it actually carries |
|---|---|---|---|
| `CompleteStep.status` | 186 | `str = "success"` | step marker (`success` / `failed` / `timed_out` / `cancelled`) |
| `CompleteStep.scope_status` | 197 | `str = "running"` | the scope machine |
| `SuspendAtGate.scope_status` | 230 | `str = "blocked"` | the scope machine |
| `FinishAttempt.status` | 350 | `str` | the attempt machine — though the document backend forwards it to `close_run`, which speaks the run vocabulary (recorded in the data-model reference §1.1) |
| `Attempt.status` | 416 | `str` | the attempt machine |
| `InputRequest.status` | 443 | `str` | the input-request machine |
| `RunView.status` | 467 | `str` | the run machine's **stored** vocabulary (lower-cased `RunStatus` values) |
| `WorkflowView.status` | 487 | `str` | the scope machine |
| `RunQuery.status` | 526 | `str \| None = None` | the run machine's stored vocabulary, as a filter |
| `WorkflowQuery.status` | 537 | `str \| None = None` | the scope machine, as a filter |

Four stored vocabularies already exist as types in `_types/lifecycle.py`:
`ScopeStatus`, `AttemptStatus` and `InputRequestStatus` are `StrEnum`s whose
member **is** the text on disk, and the run machine deliberately got no enum of
its own — it *adopts* `RunStatus` from `_types/enums.py`, lower-cased. A fifth
vocabulary, the step marker, lives as plain string constants on
`StepStatus` (`_engine/frontier.py:113`) — in the engine, which `_types` cannot
import from.

The maintainer reviewed the *Primitive obsession* row of the
runtime-schema-migrations plan's *Surviving smells* and declined to accept it.
The alternative that plan carried — keep `str` on the port and parse
`str → ScopeStatus` at the `ScopeStore` choke point — is therefore no longer
the authorized design. The port is where the types belong.

## Decision

**Every status-bearing field on the port carries its lifecycle status type. No
field stays `str`.** ADR-026 is extended, not superseded: where the ports live
is unchanged, and this decision only narrows what the port's existing fields
are allowed to hold.

### The typing, field by field

| Field | Carries | Notes |
|---|---|---|
| `CompleteStep.scope_status`, `SuspendAtGate.scope_status`, `WorkflowView.status`, `WorkflowQuery.status` | `ScopeStatus` (query fields: `ScopeStatus \| None`) | the scope machine's own enum; defaults become `ScopeStatus.RUNNING` / `ScopeStatus.BLOCKED` |
| `FinishAttempt.status`, `Attempt.status` | `AttemptStatus` | the command finishes an *attempt*; it speaks the attempt machine's vocabulary |
| `InputRequest.status` | `InputRequestStatus` | |
| `RunView.status`, `RunQuery.status` | `RunState` (new; `RunState \| None` for the query) | see below |
| `CompleteStep.status` | `StepStatus` (promoted to `_types/lifecycle.py` as a `StrEnum`) | see below |

### `RunState` — the one new enum, and a recorded revision

The run machine's stored vocabulary is the lower-cased text `RunStore` writes;
`RunStatus`'s members are the *display* spellings (`"Success"`, not
`"success"`). Typing a stored field with the display enum would make every
comparison against the stored text silently false, and a case translation at
every boundary is the lookup-table dance the `StrEnum` choice exists to prevent.
So `runtime-schema-migrations`' "the run machine gets no enum of its own" is
revised **for the port**: `_types/lifecycle.py` gains `RunState`, a `StrEnum`
whose nine members are the stored spellings, and `RUN`'s `states` and
`absorbing` sets derive from it instead of from lower-casing `RunStatus`.
Terminality keeps its one definition: `absorbing` is derived through
`RunStatus[s.name].terminal`, and a table test asserts the name mapping
`RunState ↔ RunStatus` is total. `RunStatus` itself is untouched and remains
the public, display-side enum.

### `StepStatus` — promoted, not redefined

The step marker is stored text too (inside the scope document's step records),
and it is currently engine-resident, which would force the port to type a field
with a name it cannot import. `StepStatus` moves to `_types/lifecycle.py` as a
`StrEnum` with byte-identical values; `_engine/frontier.py` imports it from
`_types` (the legal direction), and its consumers follow the import. A step
record is written once with its outcome and has no transition table — a marker
vocabulary, deliberately not a fifth `Machine`.

### The attempt/run boundary the typing forces honest

The data-model reference §1.1 already records the defect: the document
backend's `_finish_attempt` forwards `cmd.status` to `close_run`, so the nested
attempt value "records what the run ended as" in run vocabulary
(`success`, not `succeeded`) and the attempt machine is never transitioned.
Typing the field `AttemptStatus` makes that forwarding type-incorrect, which is
the point: the implementation derives the run outcome from the attempt status
plus the run record's cancellation flag — the rule §1.2 already records — and
the attempt→run projection is **data** in `_types/lifecycle.py`, not logic a
backend improvises. Run states that no attempt implies (`blocked`, `timeout`,
`refused`, `unknown`) are not expressible through `FinishAttempt` today; that
boundary is recorded, not papered over — it is the relational writer's wave
that settles how those closes reach the port, and until then the store-level
`RunStore.close_run` remains their writer.

### The JSON boundary

Every one of these enums is a `StrEnum`, so **serialization is identity**: the
member *is* the text on disk, and `json.dumps` writes the value with no
translator. The parse lives at each backend's **read projection** —
`_run_view`, `_workflow_view`, `gate_requests.request_for` for the document
backend — as `EnumType(value)`, and it is **strict**: a stored value the
vocabulary does not name is refused, never coerced to a default. That matches
the transitions contract's promise for rows written before a vocabulary
narrowed (not rewritten, but never silently moved on from either), and the
document backend already treats a malformed lease as absent rather than
inventing one — refusing is the same discipline applied to status. Writers are
**not** given a parallel string API: `require_transition`'s membership is by
value, so a caller holding a plain string still works, but every producer this
decision touches hands over enum members.

### The choke point is unchanged

`ScopeStore.set_scope_status` keeps `require_transition(SCOPE, current,
target)`, and `RunStore.open_run`/`close_run` keep theirs. Legality is decided
where it is decided today — at the write, inside the batch, reading the current
value from the record the batch is already holding. What changes is upstream of
it: the port's commands and views carry typed values, the read projections
parse once per read, and the parse does **not** move into the stores. `ScopeStore.set_scope_status`'s parameter stays honestly annotated `str` — a
`StrEnum` member *is* a `str`, so the annotation remains true while accepting
typed callers, and the store layer is not re-typed as a side effect. The parse
does not disappear either: JSON on disk is text, so every backend pays exactly
one parse per read, at its own boundary.

### What it means for implementers of the protocols

Today exactly one implementer exists — the document backend in
`_primitives/document_store.py`; no plugin implements `RuntimeStore`
(verified by search across `plugins/`; the future relational substrate is the
planned second). An implementer binds:

- reader methods return **typed** views, parsing at the implementer's own read
  boundary — a backend that hands a caller a bare `str` where the port declares
  `ScopeStatus` fails `mypy src/` and the conformance fixture;
- writer methods may receive enum members or plain text (by-value membership),
  and must store the member's *value* — never a display spelling;
- the conformance fixture `tests/types/fixtures/runtime_store_conformance.py`
  (mypy, zero errors required) is what pins the signatures for out-of-tree
  implementers, since `mypy src/` only sees in-tree modules.

### Plugin note

`functualize-mcp` and `functualize-flow-viz` do not touch these fields today;
the earlier belief that they did predates the ports' landing and does not
survive a search of the current tree. When a surface plugin starts rendering
statuses, it consumes the typed views and renders from the enum — a display
vocabulary (derived `stalled`, `abandoned`, or `RunStatus` spellings) is a
renderer's concern and stays out of the port.

## Consequences

### Positive

- **The vocabulary is spelled once and enforced twice** — by the tables the
  machines already publish, and now by the type checker at every construction
  and read.
- **The five-vocabulary confusion the runtime-schema census measured cannot
  regrow at the port.** A `WalkState`-style parallel vocabulary has no port
  surface to occupy.
- **The attempt/run conflation is fixed by the type system**, not by a comment:
  the forwarding that spoke run vocabulary through an attempt field stops
  compiling.
- **Producers convert with the compiler.** Every site still handing a raw
  literal is findable by `mypy`, which makes the implementation's ripple
  mechanical rather than investigative.

### Negative

- **One more enum beside `RunStatus`**, with a name-mapping that must stay
  total. Accepted: the mapping is asserted by a test, and the alternative —
  typing stored fields with display spellings — is a case-translation tax at
  every boundary, forever.
- **A strict parse raises on hand-edited documents.** The document backend
  treats documents as hand-editable elsewhere; a status the vocabulary does not
  name now refuses the read instead of degrading. Accepted deliberately: a
  silently invented status is the drift this decision exists to end. The
  refusal message names the value and the vocabulary, so recovery is a
  one-line edit.
- **`FinishAttempt` cannot close a run as `blocked`/`timeout`/`refused`.**
  Recorded as a boundary above; the store-level writer remains the path until
  the relational writer's wave settles the question.

### Neutral

- No field moves, no protocol gains or loses a member, and nothing in
  `src/` changes in *this* decision — it authorizes the implementation, whose
  tasks carry the file scopes and gates.
- ADR-026's module-growth watch: `_types/persistence.py` measured 777 lines at
  this decision (698 at its ADR), the growth being the gate-lifecycle field
  and its documentation. The module stays one file, zero logic, read as a
  unit; this decision adds annotations to existing fields and no new
  declarations to it.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| Keep `str` on the port; parse `str → ScopeStatus` at the `ScopeStore` choke point | No type churn; one parse, one place | The parse validates only scope status; the other machines get nothing; producers keep inventing spellings; the maintainer declined it | This is the design the maintainer's answer removed |
| Type the run fields with `RunStatus` | No new enum | Members are display spellings (`"Success"`); every comparison against stored text is silently false, or every boundary pays a case translation | Re-introduces the lookup-table drift the `StrEnum` decision ended |
| Type `FinishAttempt.status` with the run vocabulary (keep the forwarding) | Zero behaviour change in the backend | The command named *finish attempt* would carry the run's vocabulary; the attempt machine stays unenforceable; the §1.1 defect becomes permanent | The field describes the attempt; the run outcome is derived, per §1.2 |
| Lenient parse (unknown value → a default member) | Hand-edited documents never raise | A coerced status is a lie the record did not tell; the transitions refusal philosophy refuses, it never invents | Strictness is the contract's existing promise |

## What would reopen this

A stored vocabulary that cannot be a `StrEnum` — statuses carrying structure
(a reason, a timestamp) rather than a word — would need data-carrying types and
a real serializer, and this decision's serialization-is-identity claim would
not survive that. Or a run close that the attempt derivation cannot express
becoming a live producer before the relational writer lands: at that point the
`FinishAttempt` boundary above is a defect, not a note, and the port needs a
run-close command of its own.
