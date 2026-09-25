# FUN-4 — Contracts

Every interface this ticket changes at a boundary. An interface that changes without
appearing here is a defect.

## 1. New values — `src/functualize/_types/gate_resolution.py` (internal, stdlib only)

```python
class EvaluationOutcome(StrEnum):
    ACCEPTED = "accepted"
    INVALID = "invalid"          # a surface submission failed model validation
    FAILED = "failed"            # a strategy rung raised
    UNAVAILABLE = "unavailable"  # a strategy rung is not registered
    NOT_REACHED = "not_reached"  # a rung after the accepted one

@dataclass(frozen=True)
class CandidateEvaluation:
    outcome: EvaluationOutcome
    detail: str = ""                                   # rung error text / install hint
    errors: tuple[tuple[str, str], ...] = ()           # (field, message) for INVALID

@dataclass(frozen=True)
class GateCandidate:
    candidate_id: str            # minted by the recorder: "cand_" + uuid4().hex
    request_id: str
    ordinal: int                 # 0-based, monotonic per request, never restarts
    source: str                  # "strategy:<name>" | "cli" | "mcp" | "api" | "<surface>:<actor>"
    submitted_at: datetime
    evaluation: CandidateEvaluation
    payload: Any = None          # model_dump() when ACCEPTED/INVALID; None otherwise

@dataclass(frozen=True)
class LadderOutcome:            # what GateRegistry.evaluate returns — see §3
    rungs: tuple[tuple[str, CandidateEvaluation, Any], ...]
    model: Any = None            # the accepted pydantic model, or None
    blocked_reason: str = ""

@dataclass(frozen=True)
class GateResolution:
    request: InputRequest        # imported from _types.persistence
    candidates: tuple[GateCandidate, ...]
    accepted_id: str | None      # the candidate whose outcome is ACCEPTED, if any
```

These are values with zero logic. `_types.gate_resolution` may import
`_types.persistence`. The reverse import goes through `TYPE_CHECKING` only, or through
`persistence.py` importing `gate_resolution` one way. **Pick one direction and assert it
in T1's test.**

## 2. Port changes — `src/functualize/_types/persistence.py` (FUN-17's frozen contract, amended)

| Symbol | Before | After | Why |
|---|---|---|---|
| `InputRequest` | no id | **`request_id: str`** added as the first field | AC-1 |
| `SuspendAtGate` | `scope_id, generation, gate_name, position, now, schema, prompt` | adds **`request_id: str`**, **`model: str = ""`**, **`tools: tuple[Mapping[str, Any], ...] = ()`** | The request is opened in the same unit that records its candidates. `model`/`tools` are what `frontier.block` persists today; MCP needs both |
| `ConsumeInput` | — | **new** command: `scope_id, generation, request_id, now` | R5, the single consumption writer |
| `InputWriter.append` | `(request_id, source, payload=None)` | **`(candidate: GateCandidate)`** | The evaluation is recorded with the candidate (R8) |
| `InputWriter.consume` | — | **new** `(cmd: ConsumeInput) -> None` | R5 |
| `InputReader.request` | — | **new** `(request_id: str) -> InputRequest \| None` | Stage-3 resolvers answer by id |
| `InputReader.candidates_for` | — | **new** `(request_id: str) -> Sequence[GateCandidate]`, ordered by `ordinal` | R8 |
| `InputReader.open_for` | returns `open` or `accepted` | **unchanged** | — |
| `ResumeWorkflow` apply (document backend) | writes `consumed_at` | **does not** | One owner of consumption (R5) |

Store behaviour the port docstrings must state:

- `append` applies the **R6 guard inside the unit**. Appending to a request that is not
  `open` raises `InputRequestNotOpenError(request_id, status)` and applies nothing from
  that unit.
- Appending an `ACCEPTED` candidate moves the request to `accepted`.
- `consume` on a request that is already `consumed` is a no-op.
- `consume` on a request that is `open`, `cancelled` or `expired` raises
  `InputRequestNotOpenError`.

**Identity is minted by the engine-side recorder, not the store.** This deliberately
departs from `StartAttempt`'s "the store mints the run and attempt identity". A unit that
opens a request and records its first candidates must name that request **before**
`__exit__`. On an accumulating port (a D1 `batch`), an id the store mints cannot be
referenced from the same batch.

New error in `src/functualize/_types/errors.py`:
`InputRequestNotOpenError(Exception)` with `request_id: str` and `status: str`.
`GateResolutionError` gains `evaluations: tuple[CandidateEvaluation, ...] = ()` as a
keyword argument with a default. The constructor stays source-compatible.

## 3. `_gate` surface (internal)

- `GateRegistry.evaluate(model_class, *, gate_strategy, gate_name, resolved_fields=None,
  workflow_context=None) -> LadderOutcome`. `LadderOutcome` is a frozen dataclass in
  `_types/gate_resolution.py` (the fifth value there, so `_engine` can name it without
  importing `_gate`): `rungs: tuple[tuple[str, CandidateEvaluation, Any], ...]` (strategy name,
  evaluation, payload), `model: BaseModel | None` and `blocked_reason: str` (empty when
  a rung was accepted). This method is pure: no store, no
  ids, no clock.
- `GateRegistry.resolve_gate(...)` has an **unchanged signature and behaviour**. It is
  rebuilt on `evaluate`, and raises `GateResolutionError(..., evaluations=...)` with the
  same `last_error` text.
- `_gate/_evaluation.py`: `evaluate_submission(model_class, payload) ->
  tuple[CandidateEvaluation, dict | None]`. This is the one place a surface submission
  is validated. It returns the validated `model_dump()` on success.
- `blocked_reason_from(evaluations) -> str` lives in `_gate/_evaluation.py` and is the
  only producer of the `blocked_reason` text (R8). `evaluate` calls it and stores the
  result on `LadderOutcome.blocked_reason: str`. `_engine` may **not** import `_gate`
  (peer independence), so the walker reads that field from the value the injected
  registry returned. It never formats the text and never imports `_gate`.

## 4. App-level result envelopes (public `functualize.app.utils` functions; signatures additive)

| Function | Change |
|---|---|
| `answer_gate(app, store, scope_id, gate, values=None, *, …, source: str = "api")` | New keyword `source`. Result gains `resolution` (spec §6) |
| `gate_draft(app, store, scope_id, gate)` | Result gains `resolution` |
| `deposit_gate_input(app, store, scope_id, gate, payload, *, source: str = "api")` | New keyword `source`. New error `gate_already_answered`. Success gains `request_id`. An invalid payload is recorded as an `invalid` candidate, and the error envelope is unchanged |

`resume_scope(..., source: str = "api")` (`app/_workflow_control.py`) threads `source`
to its `answer_gate` call.

Explicit `source` at the production call sites. There are 5, counted with `rg -n
"answer_gate\(|resume_scope\(" src plugins`:
- `_cli/builtins.py:1455` and `:1554` pass `"cli"`;
- `app/adapters/workflow_flags.py:428` passes `"cli"`;
- `functualize_mcp/_workflow_tools.py:287` and `:345` pass `"mcp"`.

## 5. Public API surface

**No change.** `tests/test_public_api_surface.py` is untouched. New types are internal.
Exporting `GateCandidate` and friends from `functualize.plugin` for the Slack resolver
is deferred until that resolver exists (spec §8, Q-2). A public symbol needs an
`examples/` caller (`contributor/reference/public-api-example-coverage.md`).

## 6. Import-linter contracts

No edit. New modules sit in existing layers: `_types` (values), `_primitives`
(`gate_requests.py`), `_gate` (`_evaluation.py`), `_engine` (`gate_service.py`,
`recording/input_recorder.py`). `uv run lint-imports` must report every contract kept,
at every wave.

## 7. Handed to other tickets

- **FUN-18 (schema).**
  - `input_requests` needs `request_id` as its PK. The walker mints it, so the table
    must accept a supplied id.
  - `input_candidates` needs `candidate_id` PK, `request_id` FK, `ordinal`
    (unique with `request_id`), `source`, `payload` JSON, `submitted_at`, `outcome`
    (column: it is filtered on), and `detail`/`errors` JSON.
  - The `InputRequest` transition table must admit `accepted → cancelled` (reopen), and
    must refuse `accepted → open`.
- **FUN-21 (durable slice).**
  - Implement §2 on the durable store.
  - Move `app/_workflow_answer.py` and `app/_workflow_resume.py` onto the selected
    `RuntimeStore`, then delete `_primitives/gate_requests.py` together with the
    document backend's input writer and reader.
  - Its scaffold tasks 1.1 ("InputRequest state machine wiring and the input recorder")
    and the deposit half of 2.1 are **delivered here**. FUN-21 adds
    `tx.effects.append(...)` inside the units this ticket creates
    (`_engine/gate_service.py`).

## 8. Backward compatibility

Breaking changes are free before 1.0 (`.spec/CONSTITUTION.md` → *Pre-Release Stance*).
What changes, and for whom:

- A second call to the public `deposit_gate_input` on an answered gate now returns
  `gate_already_answered`; it used to overwrite. Production callers: 0. Test callers:
  `tests/workflow/test_gate_payload_shape.py` and
  `tests/integration/test_cli_workflow_parity.py`.
- An existing `scopes.json` stays readable and resumable (R9). No migration runs.
- Callers of `InputWriter.append(request_id, source, payload)`: **none**.
  `rg -n "\.inputs\.append\(" src plugins tests` returns 0 hits, so the port is
  unreached today and changing its signature breaks no caller.
