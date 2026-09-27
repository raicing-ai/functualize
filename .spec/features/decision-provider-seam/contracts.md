# decision-provider-seam — contracts

Declared surfaces only. Internal helpers are the executor's choice, within
`plan.md`'s module map. Signatures are Python 3.11, `from __future__ import
annotations` assumed. Nothing here is exported from a public package in Phase 1
(`spec.md` §6); a bundled plugin reaches `functualize._types` at runtime, as
`functualize-mcp` and `functualize-substrate-sqlite` already do.

## C-1. `functualize._types.decision` — provider half

Values and one Protocol; no logic beyond `__post_init__` range checks, per
`_types/__init__.py`'s rule.

```python
T = TypeVar("T")

@dataclass(frozen=True)
class DecisionProvenance:
    requested_model: str             # what the caller asked for
    latency_seconds: float           # monotonic wall clock of the one round trip
    input_tokens: int | None = None  # the request's single usage block (A2), when reported
    output_tokens: int | None = None

@dataclass(frozen=True)
class DecisionResult(Generic[T]):
    value: T                                   # the proposed candidate
    provider: str                              # e.g. "jev"; never parsed
    model: str                                 # the model the provider says answered
    provenance: DecisionProvenance
    distribution: Mapping[T, float] | None = None  # keyed by option; order is meaningless (B3)
    confidence: float | None = None            # provider's own scalar; NOT max(distribution) (B2)
```

- `distribution`, when present, is stored as a read-only mapping; equality
  compares it as a mapping, so key order never affects `==` (AC-2).
- Every probability and `confidence` is in `[0, 1]`; `__post_init__` raises
  `ValueError` otherwise. No sum-to-one check: the wire reports two decimals.
- There is no boolean field and no `accepted` field. Acceptance is not the
  result's to state.

```python
@dataclass(frozen=True)
class ChoiceRequest:
    state: str                     # the text to decide about, as given
    instructions: str
    options: Mapping[str, str]     # option -> meaning; 2..32 entries, non-empty keys
    model: str | None = None       # None = the provider's configured default

@runtime_checkable
class DecisionProvider(Protocol):
    @property
    def name(self) -> str: ...
    def choose(self, request: ChoiceRequest) -> DecisionResult[str]: ...
```

`choose` either returns a result whose `value` is a key of `request.options`, or
raises `DecisionUnavailableError`. It performs at most one round trip, never
sleeps, never retries.

## C-2. `functualize._types.errors` — provider half

```python
class DecisionFailure(StrEnum):
    NOT_CONFIGURED = "not_configured"
    RATE_LIMITED = "rate_limited"
    REFUSED = "refused"
    UNREACHABLE = "unreachable"
    MALFORMED = "malformed"

class DecisionUnavailableError(Exception):   # the module's convention: errors derive from Exception (errors.py:16-158)
    kind: DecisionFailure
    provider: str
    status: int | None           # HTTP status when there was one
    retry_after: float | None    # seconds, RATE_LIMITED only, as the service sent it
    detail: str                  # clipped to 300 chars; never contains the credential
```

`str(error)` is `"<provider> <kind>[ HTTP <status>][ retry after <n> s]: <detail>"`
— the string a failed rung carries into `blocked_reason` (C-6).

## C-3. The Jev wire mapping — `functualize_jev` (provider half)

New workspace package `plugins/domains/functualize-jev`, distribution name
`functualize-jev`, import name `functualize_jev`, Tier 3 (experimental) under
`plugins/PUBLISHING.md`. Stdlib-only at runtime beyond `functualize` itself.

### Request (row A1, A4)

```json
POST https://opencode.ai/zen/v1/systemone
Authorization: Bearer <OPENCODE_API_KEY>
Content-Type: application/json
User-Agent: functualize-jev/<package version>

{"model": "<request.model or configured default>",
 "state": "<request.state>",
 "questions": {"decision": {"type": "choice",
                            "instructions": "<request.instructions>",
                            "criteria": {"<option>": "<meaning>", ...}}}}
```

### Response → `DecisionResult[str]`

| wire (200) | result |
|---|---|
| `answers.decision.type` | must be `"choice"`, else `MALFORMED` |
| `answers.decision.choice` | `value`; must be a key of `request.options`, else `MALFORMED` |
| `answers.decision.probabilities` | `distribution`, as a dict keyed by option; required, else `MALFORMED` |
| `answers.decision.confidence` | `confidence` |
| `model` | `model` |
| `usage.input_tokens` / `usage.output_tokens` (the keys `tests/jev_probe/cost.py:58` reads) | `provenance.input_tokens` / `output_tokens`; absent → `None` |
| — | `provider = "jev"`, `provenance.requested_model`, `provenance.latency_seconds` |

### Status → `DecisionFailure` (row E)

| status / condition | kind | notes |
|---|---|---|
| `429` | `RATE_LIMITED` | `retry_after` from `Retry-After` (case-insensitive), `None` if absent or non-numeric |
| `400`, `401`, `402`, `403`, `422` | `REFUSED` | `status` set; `detail` is the body clipped to 300 chars, plain text included (E12) |
| any other non-200 | `REFUSED` | same |
| connection error, DNS failure, timeout | `UNREACHABLE` | `status = None` |
| `200` with non-JSON body or a shape violation above | `MALFORMED` | |
| `OPENCODE_API_KEY` unset or empty | `NOT_CONFIGURED` | raised by `choose`, no request made |

### Transport port

```python
@runtime_checkable
class JevTransport(Protocol):
    def post(self, url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> WireResponse: ...

@dataclass(frozen=True)
class WireResponse:
    status: int
    body: str
    headers: Mapping[str, str]   # keys lower-cased

class UrllibTransport: ...       # the production JevTransport; raises only for transport failure
```

A Protocol rather than a bare callable, per `.spec/CONSTITUTION.md` → *Forbidden
Patterns* ("Implicit `Callable` conventions for ports").

### Provider

```python
@dataclass(frozen=True)
class JevConfig:                       # resolved from config section [jev]; all optional
    model: str = "jev-1.13-free"
    endpoint: str = "https://opencode.ai/zen/v1/systemone"
    timeout_seconds: float = 30.0

class JevDecisionProvider:             # satisfies DecisionProvider
    def __init__(self, config: JevConfig = JevConfig(), *,
                 transport: JevTransport | None = None,
                 credential: Callable[[], str | None] | None = None) -> None: ...
    name: str                          # "jev"
    def choose(self, request: ChoiceRequest) -> DecisionResult[str]: ...
```

`credential` defaults to reading `os.environ.get("OPENCODE_API_KEY")` at call
time, never at import time and never from a config file. (It is a zero-argument
supplier used inside one class, not a port; if review reads it as an implicit
callable port, replace it with a `str | None` constructor argument read by the
plugin — `plan.md` → *Surviving smells*, S-3.)

## C-4. `ChoiceDecision` — the workflow's declaration (Gate half)

Added to `functualize._types.decision`.

```python
@dataclass(frozen=True)
class ChoiceDecision:
    field: str                       # the awaits field the decision fills
    instructions: str
    options: Mapping[str, str]       # option -> meaning
    state: FromStep                  # the step whose recorded result is the text
    accept_at: float                 # 0 < accept_at <= 1
    min_margin: float = 0.0          # 0 <= min_margin < 1
    model: str | None = None         # passed through to ChoiceRequest.model
```

## C-5. `Gate` — the declaration surface (Gate half)

`functualize._types.workflow.Gate` (re-exported unchanged as
`functualize.workflow.Gate`) gains one keyword field:

```python
decide: ChoiceDecision | None = None
```

- `"decision"` joins `_VALID_GATE_STRATEGIES`, and `STRATEGY_PROVIDERS` gains
  `"decision": "functualize-jev"` (the table test pins their key sets equal).
- `decide` set and `strategy` `None` → `strategy` becomes `"decision"`.
  `decide` set with any other strategy, or `strategy="decision"` without
  `decide` → `ValueError`.
- `decide.field` must be a field of `awaits` whose annotation is a `Literal` of
  strings or a `StrEnum`; its allowed values must equal `decide.options`' keys
  exactly → otherwise `ValueError` naming both sets.

## C-6. The `decision` gate strategy (Gate half)

`functualize._gate.decision_strategy`:

```python
class DecisionGateResolver:            # satisfies GateResolver
    def __init__(self, provider: DecisionProvider) -> None: ...
    def resolve(self, ctx: GateContext) -> BaseModel: ...
```

`GateContext` gains `decision: ChoiceDecision | None = None`;
`GateRegistry.evaluate` gains the keyword `decision: ChoiceDecision | None =
None`, passed into the context unchanged. `GateRegistry.resolve_gate` and
`app.gates.resolve_gate` are **not** widened: Phase 1's only caller is the walk
(C-7), and a keyword nobody passes is speculative.

`resolve`:

1. `ctx.decision is None` → raise `ValueError("gate has no decision declared")`.
2. State: `ctx.workflow_context[decision.state.name]`; missing → raise
   `ValueError` naming the step. A `str` is used as is; anything else is
   `json.dumps(value, sort_keys=True, default=str)`.
3. `provider.choose(ChoiceRequest(...))`; `DecisionUnavailableError`
   propagates (the ladder records it as `failed`, `detail = str(error)`).
4. `distribution is None` → raise `ValueError` (a threshold needs one).
5. `p = distribution[value]`; `runner_up = max(v for k, v in distribution.items() if k != value, default=0.0)`;
   `margin = p - runner_up`. Accept iff `p >= accept_at and margin >= min_margin`.
   `confidence` is not read.
6. Accepted → `ctx.model_class(**{**ctx.resolved_fields, decision.field: value})`.
   Not accepted → raise `DecisionBelowThresholdError` (a `ValueError`) whose
   `str` is exactly:

```
<provider>/<model> proposed '<value>' at <p:.2f> (margin <margin:.2f>); workflow requires >= <accept_at:.2f>, margin >= <min_margin:.2f>
```

The rung's detail is this string, and `blocked_reason` composes it through the
unchanged `blocked_reason_from` (`_gate/_evaluation.py`) as
`decision: <that string>; …`.

## C-7. The walked gate (Gate half)

`functualize._engine.gate_service`:

- `_gate_strategy_list` returns `["decision", "prompt", "resolve"]` for a gate
  whose strategy is `"decision"`.
- `GateService.service` calls
  `registry.evaluate(node.awaits, gate_strategy=…, gate_name=node.name,
  workflow_context=dict(ledger.results), decision=node.decide)`.

## C-8. The Jev plugin's boot surface (Gate half)

```toml
[project.entry-points."functualize.plugins"]
jev = "functualize_jev:JevPlugin"
```

`JevPlugin.__call__(app)` resolves `JevConfig` from `app.configuration`
(defaults when the section is absent) and calls
`app.gates.register_gate_strategy("decision", DecisionGateResolver(JevDecisionProvider(config)))`.
It registers no preset and no DI capability, and reads no credential at boot.

## Unchanged, and asserted unchanged

- `EvaluationOutcome`'s five members; the input-request status set; `WalkOutcome`;
  the workflow node types (`Step`, `Gate`, `AgentStep`, `Loop`, edges).
- `blocked_reason_from`'s composition.
- `ai_inbound`, `ai_outbound`, `prompt`, `resolve` ladders.
