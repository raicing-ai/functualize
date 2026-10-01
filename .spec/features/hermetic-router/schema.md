# hermetic-router — schema

Internal shapes only; the external ones are in `contracts.md`.

## 1. The stored candidate entry (document backend, `scopes.json`)

`TRANSITIONAL(FUN-21)` storage, unchanged in location. One key is added, and
only when the evaluation carries evidence:

```json
{
  "candidate_id": "cand_…",
  "request_id": "…",
  "ordinal": 0,
  "source": "strategy:decision",
  "submitted_at": "2026-10-01T17:30:00+00:00",
  "outcome": "accepted",
  "detail": "",
  "errors": [],
  "payload": {"route": "cheap_model"},
  "evidence": { "schema": "decision-evidence/1", "...": "C-3" }
}
```

- Absent key ⇒ `CandidateEvaluation.evidence is None` on read.
- Written by `gate_requests.append_candidate` as `dict(evaluation.evidence)`;
  read by `candidates_for` as-is (no validation, like `payload`).
- The future SQL home (`contributor/reference/runtime-persistence-data-model.md`
  §2.4, `input_candidates`) gains `evidence JSON` — nullable, never a
  predicate, so JSON by that document's own §3 rule. T9 records it there.

## 2. A fallback ladder, as recorded

A run whose proposal was below threshold (`fallback="human_review"`), two
candidates on the router's request:

| ordinal | source | outcome | detail | payload | evidence |
|---|---|---|---|---|---|
| 0 | `strategy:decision` | `failed` | `jev/jev-1.13-free proposed 'deterministic' at 0.55 (margin 0.20); workflow requires >= 0.70, margin >= 0.10` | — | C-3, `verdict: below_threshold` |
| 1 | `strategy:resolve` | `accepted` | `""` | `{"route": "human_review"}` | — |

With the provider absent, ordinal 0 is `unavailable` with detail `install
functualize-decision-jev to register it` and no evidence. With an accepted
proposal, ordinal 0 is `accepted` with evidence (`verdict: accepted`) and
ordinal 1 is `not_reached`.

## 3. `RungEvidence` lifecycle

```
GateRegistry.evaluate
  ctx = GateContext(..., evidence=None)                 # shared inputs
  for each rung:
      sink = RungEvidence()                             # fresh, per rung
      rung_ctx = dataclasses.replace(ctx, evidence=sink)
      try:   model = resolver.resolve(rung_ctx)         # may call sink.record(...) once
             rung = (name, CandidateEvaluation(ACCEPTED, evidence=sink.value), dump)
      except Exception as exc:
             rung = (name, CandidateEvaluation(FAILED, detail=str(exc), evidence=sink.value), None)
```

`sink.record` a second time raises `RuntimeError` (a resolver records one
decision per rung). No sink outlives its rung; nothing is module-level.
