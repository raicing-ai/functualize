# The Hermetic Router

A reference workflow for **decision gates**: one gate routes each request to
one of four branches, and everything a run did is recorded — the proposal,
its distribution, the rule that judged it, the cost of asking, and who
finally took the gate. This is routing, not model calls: the workflow never
talks to a model itself, and no step here effects anything.

## The four routes

| Route | Means |
|-------|-------|
| `deterministic` | a fixed rule or lookup answers it; no model needed |
| `cheap_model` | a short, low-risk text task a small model can do |
| `frontier_agent` | multi-step reasoning or tool use is required |
| `human_review` | risky, ambiguous, or needs a person's judgement |

## The declaration

`router.py` declares the decision once, on the gate:

```python
ROUTER = ChoiceDecision(
    field="route",
    instructions="Choose how this request should be handled.",
    options={...},                  # the four routes above
    state=FromStep("intake"),       # the text to decide about
    accept_at=0.70,                 # the winner needs >= 70%
    min_margin=0.10,                # ...and a lead of >= 10 points
    fallback="human_review",        # taken when nothing clears both
)
```

A proposal that clears both thresholds routes itself — no person involved.
One that does not is **not** an error: the declared fallback answers, the
walk takes the `human_review` branch, and it blocks at the `review` gate
waiting for a person. The decision rung's reason travels with the record,
so "why did this land on a human?" has an answer.

## Reading a run back

```python
from functualize.app.utils import decision_record

record = decision_record(store, scope_id, "route")
# {"route": "cheap_model", "decided_by": "decision", "fallback_used": False,
#  "reason": None, "evidence": {...}, "gate": "route", "request_id": ...}
```

- `decided_by` — `"decision"` (a proposal was taken), `"fallback"` (the
  declared option answered), `"person"` (somebody answered the gate), or
  `None` (still open).
- `reason` — when the fallback took over, the decision rung's own detail:
  what was proposed, at what probability, and the thresholds it missed.
- `evidence` — the decision rung's record: the state's digest, the rule's
  digest, the distribution, the provider's own scalar (recorded, never read
  by the rule), the latency, and the token counts.

Two runs on the same input can route differently — that is what a
probabilistic router does. The records make that visible; they do not
prevent it.

## It runs without any provider

Delete every provider package and unset every key: the router still runs.
The decision rung records an `unavailable` (or `not_configured`) verdict
with the reason, the fallback answers, and the walk blocks at `review`.
Register any `DecisionProvider` as the `decision` strategy and the same
workflow starts routing on proposals:

```python
app.gates.register_gate_strategy("decision", DecisionGateResolver(provider))
```

## The tests

`tests/test_router.py` drives the whole thing through the public surface
with a fake provider — a clear proposal routes itself, a weak one falls
back and blocks for a person, a rate-limited provider is routed around in
under a second, a resumed scope never asks twice, and a person answering
the review gate cannot forge evidence.

```bash
uv run pytest examples/standalone/hermetic_router -v
```
