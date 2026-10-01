# hermetic-router — contracts

Declared surfaces only. Python 3.11, `from __future__ import annotations`
assumed. Every new public name is **provisional**, like Phase 1's (design-review
decision D2: everything outside the stable list is provisional).

| public module | change |
|---|---|
| `functualize.workflow` | `ChoiceDecision` gains `fallback` (C-1) |
| `functualize.app.utils` | new `decision_record` (C-5) |
| `functualize.app.utils.gate_draft` | each candidate in `["resolution"]["candidates"]` may carry `"evidence"` (C-4) |

## C-1. `ChoiceDecision.fallback` — `functualize._types.decision`

```python
@dataclass(frozen=True)
class ChoiceDecision:
    field: str
    instructions: str
    options: Mapping[str, str]
    state: FromStep
    accept_at: float
    min_margin: float = 0.0
    model: str | None = None
    fallback: str | None = None      # NEW — one of `options`; the route taken when no proposal is accepted
```

- `__post_init__` (in addition to Phase 1's checks): `fallback`, when not
  `None`, must be a key of `options` → else `ValueError` naming both.
- `Gate._check_decision` (`functualize._types.workflow`), in addition to
  Phase 1's checks:
  - the decided field must be **required** (`awaits.model_fields[field].is_required()`)
    → else `ValueError` whose message contains `fallback=`
    (e.g. `Gate 'route' decides Route.route, which has a default; a default
    would bypass the decision — declare it as ChoiceDecision(fallback=...)`);
  - when `fallback` is set, every other field of `awaits` must have a default
    → else `ValueError` naming the required fields.

### Projection and digest

`_decision_shape` moves from `functualize._types.workflow` to
`functualize._types.decision` as `decision_shape(decide) -> dict[str, Any]`
(same keys and values as today), and gains `"fallback": <str>` **only when
`fallback` is not `None`** — so every Phase 1 projection, and therefore every
Phase 1 graph digest, is unchanged.

```python
def decision_shape(decide: ChoiceDecision) -> dict[str, Any]: ...
def decision_digest(decide: ChoiceDecision) -> str:
    """'sha256:' + hexdigest of json.dumps(decision_shape(decide), sort_keys=True, separators=(",", ":"))."""
```

Both are added to `functualize._types.decision.__all__`; neither is exported
from a public package.

## C-2. Rung evidence — `functualize._types.gate_resolution` and `functualize._gate._context`

```python
@dataclass(frozen=True)
class CandidateEvaluation:
    outcome: EvaluationOutcome
    detail: str = ""
    errors: tuple[tuple[str, str], ...] = ()
    evidence: Mapping[str, Any] | None = None   # NEW — JSON-safe; written by the rung, never by an answerer
```

```python
class RungEvidence:                      # functualize._gate._context
    """Write-once collector a resolver fills while it runs (collecting parameter)."""
    def record(self, evidence: Mapping[str, Any]) -> None: ...   # second call → RuntimeError
    @property
    def value(self) -> Mapping[str, Any] | None: ...

@dataclass(frozen=True)
class GateContext:
    ...                                  # Phase 1 fields unchanged, in order
    evidence: RungEvidence | None = None # NEW — last field
```

`GateRegistry.evaluate` gives each rung its own context,
`dataclasses.replace(ctx, evidence=RungEvidence())`, and after the rung puts
`sink.value` on that rung's `CandidateEvaluation(evidence=...)` — for
`accepted` and `failed` rungs alike. `unavailable` and `not_reached` rungs
never carry evidence.

`GateRegistry.evaluate`, when `decision is not None and decision.fallback is
not None`: the decided field counts as resolved to `decision.fallback`, and
dispatch is forced (the Step-2 short-circuit does not apply). Signature
unchanged.

## C-3. The decision evidence — the JSON a `decision` rung records

Built by `functualize._gate.decision_evidence` (new module) and recorded by
`DecisionGateResolver.resolve` through `ctx.evidence` whenever the provider was
called. `decision_strategy.py` never names `confidence`.

```json
{
  "schema": "decision-evidence/1",
  "field": "route",
  "state": {"step": "intake", "sha256": "<64 hex>", "chars": 57},
  "rule": {"digest": "sha256:<64 hex>", "accept_at": 0.7, "min_margin": 0.1,
           "fallback": "human_review"},
  "provider": "jev",
  "model": "jev-1.13-free",
  "requested_model": "jev-1.13-free",
  "proposal": "cheap_model",
  "distribution": {"cheap_model": 0.82, "deterministic": 0.1,
                   "frontier_agent": 0.05, "human_review": 0.03},
  "confidence": 0.74,
  "probability": 0.82,
  "margin": 0.72,
  "verdict": "accepted",
  "failure": null,
  "latency_seconds": 0.61,
  "input_tokens": 416,
  "output_tokens": 73
}
```

| key | value |
|---|---|
| `schema` | always `"decision-evidence/1"` |
| `field` | `decide.field` — the decided field, so a reader can find the route in the accepted payload |
| `state.step` | `decide.state.name` |
| `state.sha256` | `hashlib.sha256(state.encode("utf-8")).hexdigest()` of the exact string sent to the provider |
| `state.chars` | `len(state)` |
| `rule` | `decision_digest(decide)`, `float(accept_at)`, `float(min_margin)`, `fallback` (or `null`) |
| `provider` | `result.provider`; on failure `error.provider` |
| `model` | `result.model`; `null` on failure |
| `requested_model` | `result.provenance.requested_model`; on failure `decide.model` (may be `null` = provider default) |
| `proposal` | `result.value`; `null` on failure |
| `distribution` | `dict(result.distribution)` in the order returned, or `null`; **order carries no meaning** — compare as a mapping |
| `confidence` | `result.confidence` or `null`; recorded, never read by the rule |
| `probability`, `margin` | as the rule computed them; `null` when there was no distribution or on failure |
| `verdict` | `"accepted"` · `"below_threshold"` · `"no_distribution"` · `"provider_failed"` |
| `failure` | `null`, or `{"kind": error.kind.value, "status": error.status, "retry_after": error.retry_after}` |
| `latency_seconds` | `time.monotonic()` measured by the resolver around `provider.choose(...)`, for success and failure alike |
| `input_tokens`, `output_tokens` | from `result.provenance`; `null` when unreported or on failure |

A state step with no recorded result fails the rung **before** the provider is
called, as in Phase 1, and records no evidence.

## C-4. Persistence and the read projection

- `functualize._primitives.gate_requests.append_candidate` writes
  `"evidence": dict(evaluation.evidence)` into the stored candidate entry **only
  when it is not `None`**; `candidates_for` reads it back
  (`CandidateEvaluation(evidence=entry.get("evidence"))`). Documents written
  before this change, and every candidate without evidence, are byte-identical.
- `functualize.app._workflow_resume._resolution_view` adds `"evidence"` to a
  candidate's projected dict **only when it has one** — so
  `gate_draft(...)["resolution"]["candidates"]` keeps its seven keys for every
  other candidate (`tests/workflow/test_gate_drafts.py:176-186`).
- `InputRecorder.submitted` (answer surfaces) never sets evidence: an answer
  arrives through `evaluate_submission`, which builds evaluations without it.

## C-5. `decision_record` — `functualize.app.utils`

```python
def decision_record(store: Any, scope_id: str, gate: str) -> dict[str, Any] | None: ...
```

Defined in `functualize/app/_decision_record.py`; re-exported from
`functualize.app.utils` and listed in its `__all__`. Returns `None` when the
scope has no record of `gate`. Otherwise, from the gate record's candidates
(ordered by ordinal):

```json
{
  "gate": "route",
  "request_id": "<id>",
  "route": "human_review",
  "decided_by": "fallback",
  "fallback_used": true,
  "reason": "decision: jev/jev-1.13-free proposed 'deterministic' at 0.55 (margin 0.20); workflow requires >= 0.70, margin >= 0.10",
  "evidence": { "...": "the latest decision rung's evidence (C-3), or null" }
}
```

| key | rule |
|---|---|
| `route` | the accepted candidate's `payload[evidence["field"]]` when the latest decision rung has evidence; otherwise the accepted payload's value if it has exactly one key; otherwise `null`. `null` when nothing is accepted yet |
| `decided_by` | from the accepted candidate's `source`: `strategy:decision` → `"decision"`; `strategy:resolve` → `"fallback"`; any other → `"person"`; nothing accepted → `null` |
| `fallback_used` | `decided_by == "fallback"` |
| `reason` | when `fallback_used`: `"<name>: <detail>"` of the latest `strategy:decision` candidate (for `unavailable`, its detail is the install hint); else `null` |
| `evidence` | the latest `strategy:decision` candidate's `evidence`, or `null` |

The decided field's name is not stored on the request, which is why C-3's
evidence carries `"field"`. Without evidence (provider absent) the reference
workflow's one-field `RouteChoice` still yields its route.

`decided_by` reads `source`, which `GateCandidate` documents as "recorded, not
parsed … for the reader of a resolution, never for a decision". This function
*is* such a reader; nothing routes on its output.

## C-6. The walked gate — `functualize._engine.gate_service`

`_gate_strategy_list` returns `["decision", "resolve"]` for a gate whose
`decide.fallback` is not `None`, and `["decision", "prompt", "resolve"]` (as
today) for one whose fallback is `None`. `GateService.service` is otherwise
unchanged.

## C-7. The reference workflow — `examples/standalone/hermetic_router/`

```python
Route = Literal["deterministic", "cheap_model", "frontier_agent", "human_review"]

class RouteChoice(BaseModel):
    route: Route                       # required: no default (C-1)

class Review(BaseModel):
    handled: bool

ROUTER = ChoiceDecision(
    field="route",
    instructions="Choose how this request should be handled.",
    options={
        "deterministic": "a fixed rule or lookup answers it; no model needed",
        "cheap_model": "a short, low-risk text task a small model can do",
        "frontier_agent": "multi-step reasoning or tool use is required",
        "human_review": "risky, ambiguous, or needs a person's judgement",
    },
    state=FromStep("intake"),
    accept_at=0.70,
    min_margin=0.10,
    fallback="human_review",
)

def build_router(app: FunctualizeApp, text: str) -> list[str]:
    """Register the workflow `router` and its jobs on `app`; return the list the stubs append to."""
```

Graph: `intake → route (Gate, decide=ROUTER)`; `ConditionalEdge` from `route`
on `answer["route"]` to `deterministic`, `cheap-model`, `frontier-agent`
(stub steps) and `review` (`Gate`, awaits `Review`) → `handle-by-person`
(stub step); every stub → `END`. No step is `effecting=True`.

## Unchanged, and asserted unchanged

- `EvaluationOutcome`'s five members; the input-request status set;
  `WalkOutcome`; node kinds; `_VALID_GATE_STRATEGIES` (five names);
  `STRATEGY_PROVIDERS`; `CORE_STRATEGIES`.
- `DecisionProvider`, `ChoiceRequest`, `DecisionResult`,
  `DecisionUnavailableError` and the Jev wire mapping.
- `blocked_reason_from` and `DecisionBelowThresholdError`'s message.
- The ladder and digest of every decision without a fallback.
