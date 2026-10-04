# hermetic-evaluation — internal schema

Internal to `tests/hermetic_eval/`. Nothing here is product state.

## S-1 — one ledger line (`cells.jsonl`)

One JSON object per attempted cell, `sort_keys=True`, written and flushed
before the next cell starts. Every gate-derived value is copied from
`decision_record(...)` and its `evidence` (`decision-evidence/1`) — never
recomputed.

| key | type | source |
|---|---|---|
| `cell` | int | 1-based position in the B-10 order |
| `repeat` | int | 1..5 |
| `scenario` | str | corpus `id` |
| `expected` | str | corpus `expected` (harness; never sent to a comparator) |
| `stratum` | str | corpus `stratum` |
| `scope` | str | `<comparator>-r<repeat>-<id>` |
| `status` | str | `routed` · `failed` · `invalid_model` · `not_attempted` |
| `route` | str \| null | `record["route"]` (`null` only for `not_attempted`) |
| `decided_by` | str \| null | `record["decided_by"]` |
| `verdict` | str \| null | `evidence["verdict"]` (`accepted`, `below_threshold`, `provider_failed`, `no_distribution`, `uncovered_proposal`) |
| `proposal` | str \| null | `evidence["proposal"]` |
| `distribution` | object \| null | `evidence["distribution"]` |
| `probability` | float \| null | `evidence["probability"]` |
| `margin` | float \| null | `evidence["margin"]` |
| `confidence` | float \| null | `evidence["confidence"]` (recorded, never consulted) |
| `failure` | object \| null | `evidence["failure"]` = `{kind, status, retry_after}` |
| `latency_seconds` | float \| null | `evidence["latency_seconds"]` |
| `input_tokens`, `output_tokens` | int \| null | evidence |
| `state_sha256` | str | `evidence["state"]["sha256"]` |
| `rule_digest` | str | `evidence["rule"]["digest"]` |
| `frontier` | object \| null | S-2, frontier comparator only |
| `started_at` | str | UTC ISO-8601 when the cell began |

`status` derivation: `failed` when `verdict == "provider_failed"` (the gate
took the fallback); `routed` otherwise; `invalid_model` per spec B-7;
`not_attempted` per spec B-9 (all gate fields `null`).

## S-2 — the frontier block

```json
{"cli_version": "2.1.281 (Claude Code)", "model": "claude-sonnet-5", "model_mismatch": false,
 "cost_usd": 0.00884, "cost_basis": "list", "duration_ms": 5828,
 "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1149, "cache_read_input_tokens": 0, "output_tokens": 424}}
```

`cli_version` is `claude --version`'s stdout, read once per invocation.

## S-3 — `metrics.json`

```
{
  "provenance": {"corpus": {version, sha256}, "runs": {<comparator>: {run_id, identity_sha256, ledger_sha256, started_at, cells}}, "repo_commit"},
  "comparators": {
    <comparator>: {
      "overall" | "clear" | "borderline": {
        "cells", "availability", "routed_accuracy", "macro_f1", "per_route": {<route>: {precision, recall, support}},
        "confusion_routed": {<expected>: {<route>: n}}, "confusion_proposed": {<expected>: {<route|failed>: n}},
        "calibration": {"bins": [{lo, hi, n, mean_p, accuracy}], "ece", "brier"},
        "calibration_confidence": same | null,
        "escalation": {coverage, selective_accuracy, precision, recall, by_cause: {fallback, proposal}},
        "latency": {p50, p95, max},
        "cost": {usd_total, usd_per_cell, input_tokens, output_tokens, usd_per_correct_route},
        "variance": {mean_modal_agreement, flips, mean_probability_sd, flipped: [<scenario>]},
        "errors": {false_continue, unsafe_continue, false_stop: {fallback, proposal}}
      },
      "sweep": [{accept_at, min_margin, coverage, selective_accuracy, false_continue, unsafe_continue, false_stop}],
      "flip_points": {<scenario>: accept_at | null}
    }
  },
  "agreement": {"<a>|<b>": {rate, kappa}}
}
```

Percentiles: nearest-rank on the sorted latencies of non-`not_attempted` cells.
Cohen's κ over the routed outcome of cells sharing `(scenario, repeat)` in both
ledgers.
