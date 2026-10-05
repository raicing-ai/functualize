# Persistence Port Status Typing — Contracts

The port's declared surface, before → after. Nothing is added to or removed
from `__all__`; only annotations, defaults and the two vocabulary moves below
change. Line numbers are `master` @ `0502eda` (2026-10-05).

## 1. New vocabulary in `_types/lifecycle.py`

```python
class RunState(StrEnum):
    """What a run row's `status` holds — the stored spelling of RunStatus."""

    RUNNING = "running"
    BLOCKED = "blocked"
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    REFUSED = "refused"

RUN: states/absorbing now derive from RunState;
     absorbing passes through RunStatus[s.name].terminal  # one terminal definition

class StepStatus(StrEnum):   # promoted from _engine/frontier.py, values identical
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

ATTEMPT_TO_RUN: Final[Mapping[AttemptStatus, str]]
    # succeeded->success, failed->failure, skipped->skipped, cancelled->cancelled
    # (the derived part of §1.2's "last attempt + cancellation flag";
    #  cancellation is resolved by the store from the run record)
```

## 2. `_types/persistence.py` field annotations

| Field | Line | Before | After |
|---|---|---|---|
| `CompleteStep.status` | 186 | `str = "success"` | `StepStatus = StepStatus.SUCCESS` |
| `CompleteStep.scope_status` | 197 | `str = "running"` | `ScopeStatus = ScopeStatus.RUNNING` |
| `SuspendAtGate.scope_status` | 230 | `str = "blocked"` | `ScopeStatus = ScopeStatus.BLOCKED` |
| `FinishAttempt.status` | 350 | `str` | `AttemptStatus` |
| `Attempt.status` | 416 | `str` | `AttemptStatus` |
| `InputRequest.status` | 443 | `str` | `InputRequestStatus` |
| `RunView.status` | 467 | `str` | `RunState` |
| `WorkflowView.status` | 487 | `str` | `ScopeStatus` |
| `RunQuery.status` | 526 | `str \| None = None` | `RunState \| None = None` |
| `WorkflowQuery.status` | 537 | `str \| None = None` | `ScopeStatus \| None = None` |

`_types/persistence.py` imports the enums from `_types.lifecycle` — same
package, stdlib-only rule intact.

## 3. Signatures whose parameters become typed (callers converted in the same wave)

```python
# _engine/recording/workflow_recorder.py
step_completed(*, status: StepStatus = StepStatus.SUCCESS,
               scope_status: ScopeStatus = ScopeStatus.RUNNING, ...) -> CompleteStep
suspended(...) -> SuspendAtGate                                  # passes through

# _engine/recording/input_recorder.py
opened(*, scope_status: ScopeStatus = ScopeStatus.BLOCKED, ...) -> SuspendAtGate

# _engine/recording/run_recorder.py
finished(*, status: AttemptStatus, ...) -> FinishAttempt

# _engine/frontier.py
open_request(*, scope_status: ScopeStatus = ScopeStatus.BLOCKED, ...) -> str
```

## 4. Read projections (parse sites) and error surface

```python
# _primitives/document_store.py
_run_view:        status=RunState(record["status"])          # was str(record.get(...))
_workflow_view:   status=ScopeStatus(record["status"])       # strict; refuses unknown
_finish_attempt:  attempt row carries AttemptStatus; run outcome =
                  ATTEMPT_TO_RUN[cmd.status] unless the record's cancellation flag
                  resolves it — no longer forwarded to close_run verbatim
_resume/_cancel:  stamp ScopeStatus.RUNNING / ScopeStatus.CANCELLED members

# _primitives/gate_requests.py
request_for:      status=InputRequestStatus(_status(record))

# _types/errors.py
InputRequestNotOpenError.status: InputRequestStatus
```

`IllegalTransition` keeps `str` fields — it reports the *pair*, which may be
any text the store held, including a value no vocabulary names.

## 5. Unchanged on purpose

- `ScopeStore.set_scope_status(scope_id: str, status: str)` — annotation stays;
  `require_transition` membership is by value. Guarded, not re-typed.
- `RunStore.open_run` / `close_run` — same.
- `RunStatus` (`_types/enums.py`) — untouched; display vocabulary, public.
- `WalkState` (`_engine/frontier.py`) — untouched; engine-internal walk
  markers, out of this feature's scope.
- Protocol members of `RunWriter`/`WorkflowWriter`/`InputWriter`/`RunReader`/
  `WorkflowReader`/`InputReader` — signatures unchanged; only the types the
  commands and views carry are narrowed. The conformance fixture
  (`tests/types/fixtures/runtime_store_conformance.py`) therefore needs no
  edit — it keeps pinning the store-to-port assignment with the narrowed
  types.
