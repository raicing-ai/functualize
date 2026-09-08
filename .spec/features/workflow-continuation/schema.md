# Schema — workflow-continuation

Internal shapes. The external contract is `contracts.md`.

---

## 1. The gate record gains one key

`scopes.json` → `scopes.<id>.gates.<name>`. **No `SCOPES_VERSION` bump**: the key is
additive and every reader treats its absence as "no draft".

```jsonc
{
  "model": "Approval",
  "input_schema": { ... },
  "tools": [ ... ],
  "blocked_at": "2026-09-09T...",
  "payload": null,
  "draft": {                       // NEW, absent until first --set/--input
    "values": {"approved": true},
    "updated_at": "2026-09-09T..."
  }
}
```

**Invariant (the whole reason a draft is safe):**

> `payload` is non-null **iff** it is the output of a successful
> `model(**draft.values).model_dump()`.

The walker reads `payload` and never `draft`. So a partially answered gate is
indistinguishable, to the walk, from an unanswered one — which is the correct meaning.

`_blank_scope()` is **not** changed: a gate record is created by `put_gate`, not by the
blank scope, and adding `draft: None` there would put the key on every gate that never
gets one.

## 2. Store accessors

```python
# ScopeStore, forwarded verbatim by StateStore (the 24c5cc0 façade pattern)
def get_gate_draft(scope_id: str, gate: str) -> dict | None
def put_gate_draft(scope_id: str, gate: str, values: dict) -> bool   # False: no such gate
def clear_gate_draft(scope_id: str, gate: str) -> bool
def reopen_gate(scope_id: str, gate: str) -> bool   # payload -> draft.values, payload=None
def delete_scope(scope_id: str) -> bool             # for purge
```

`reopen_gate` is a store-level move with **no policy** — the position guard (AC-14) lives
in `app/_workflow_answer.py`, because it needs to compare the scope position against the
graph, which the store cannot see. `pitfalls.md` §22: the store must not reconstruct a
judgement the app layer computes.

## 3. `derived_state` — a pure function of the scope record

```python
def derived_state(scope: dict) -> str:
    status = scope.get("status")
    if status == "cancelled":  return "cancelled"
    if status == "failed":     return "failed"
    if status == "completed":
        ep = scope.get("epilogue") or {}
        return "stalled" if ep.get("status") == "failed" else "completed"
    if status == "running":    return "running"
    if status == "blocked":
        return "waiting" if any(pending_gates(scope)) else "ready"
    return status or "unknown"
```

Pure, total, no store read, no app boot. Every surface derives it the same way because
there is one function — `pitfalls.md` §6.

Ordering matters and is asserted: `completed` + failed epilogue must reach `stalled`
before the plain `completed` branch, or the sticky-body case is invisible.

## 4. The `--wf-*` resolution result

`app/adapters/workflow_flags.py` turns the parsed flags into exactly one of three
outcomes, so both injection points branch on a closed set rather than on flag
combinations:

```python
@dataclass(frozen=True)
class WorkflowFlagOutcome:
    kind: Literal["run", "short_circuit", "error"]
    scope_id: str | None = None       # kind="run": pass to execute()
    deposit: tuple[str, dict] | None = None   # (gate, values) to answer before walking
    retry_epilogue: bool = False
    text: str = ""                    # kind in {"short_circuit","error"}: what to echo
    exit_code: int = 0
```

- `--wf-status` / `--wf-show` → `short_circuit`, exit 0, job never runs.
- `--wf-resume` / `--wf-run-id` → `run` with a resolved `scope_id`.
- ambiguity, unknown id, cancelled scope → `error` with the code table's exit.

`--wf-run-id` may mint; `--wf-resume` may not. That split *is* the phantom-run fix, and it
is expressed as two fields resolving into one `scope_id`, not as one field with a flag.

## 5. Purge selection

```
purgeable  = derived_state ∈ {completed, stalled, failed, cancelled}
protected  = derived_state ∈ {running, waiting, ready}
```

`--state` accepts only a purgeable state; naming a protected one is a usage error rather
than a silent empty result. `--older-than` filters on the **newest** `completed_at` across
the scope's step and epilogue records — the only timestamps that exist
(`_blank_scope` carries none, and `blocked_at` resets on every re-block, so it cannot
measure age).

A scope with no timestamps at all is **never** matched by `--older-than`. It cannot be
aged, and defaulting it to "infinitely old" would purge exactly the records whose history
is least known.
