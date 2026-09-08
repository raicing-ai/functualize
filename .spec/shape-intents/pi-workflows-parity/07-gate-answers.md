# 07 · Gate answers — partial, whole, and corrected

How a gate is answered: one field at a time, all at once, or corrected. The verb is
`answer` ([05 §2.3](05-target-surface.md)); `deposit_gate_input` remains the internal
function name.

---

## 1. Why today's `resume` cannot do it

`deposit_gate_input` (`app/_workflow_resume.py:60-107`) is all-or-nothing by
construction:

```python
model, error = _resolve_gate_model(app, scope, gate)   # the live Pydantic model
...
model(**payload)          # full validation — every required field or nothing
...
store.deposit_gate_payload(scope_id, gate, payload)    # then store the RAW dict
```

Three consequences:

1. **No partial deposit.** `model(**payload)` raises on any missing required field, and
   nothing is stored on failure (by design — the docstring says so).
2. **No editing.** Once `payload` is non-`None`, `pending_gates` stops listing the gate
   (`:27-31`), and every addressing path resolves through `pending_gates`. `resume_gate`
   answers `gate_not_found`. The store would happily overwrite
   (`state_store.py:232-241`); only the tooling refuses.
3. **The stored shape is wrong.** It validates the model but stores the **raw dict**, so
   Pydantic defaults and coercions are discarded. The walker's own strategy path stores
   `model.model_dump()` (`workflow_walker.py:270-277`). Same gate, two different objects
   reaching the node depending on who answered it. **Fix this in the same change** —
   a partial-deposit feature that accumulates raw fragments would make the divergence
   permanent.

## 2. The shape of the fix: a draft slot

Add one field to the gate record. Do not touch `payload`.

```
gates: {
  "approval": {
    "model": "ApprovalInput",
    "input_schema": {...},
    "tools": [...],
    "blocked_at": "...",
    "payload": null,          # unchanged: null until COMPLETE and VALID
    "draft": {                # new
      "values": {"approved": true},
      "updated_at": "...",
      "actor": "agent:claude-code"   # optional, see 06-provenance in the old study
    }
  }
}
```

**The invariant that makes this safe: `payload` is only ever written by a full,
successful `model(**draft.values)` — and it is written as `model_dump()`.** Partial
input lives in `draft` and the walker never reads it. A blocked walk stays blocked until
the draft validates whole. Nothing about resume, replay or memoization changes.

This also fixes §1.3 for free: the one place that writes `payload` now writes the
validated dump, on both the deposit path and the strategy path.

## 3. The command

```
func builtin workflow answer <workflow-id> <gate> [OPTIONS]
```

| Option | Meaning |
|---|---|
| `--set KEY=VALUE` (repeatable) | Merge one field into the draft. JSON-typed values; `KEY` may be dotted for nested models. |
| `--input JSON` | Merge a whole object into the draft (the current `resume --input` shape) |
| `--replace` | With `--input`: replace the draft rather than merging |
| `--unset KEY` (repeatable) | Remove a field from the draft |
| `--clear` | Discard the draft entirely |
| `--show` | Print the draft, the model schema, and **what is still missing** |
| `--commit` | Validate the draft whole; on success write `payload` and clear the draft |
| `--no-commit` | Never auto-commit even if the draft is complete |

### Auto-commit is the default

Every mutating invocation attempts a commit at the end. If the draft validates, the gate
is answered — so the existing one-shot flow is unchanged:

```bash
func builtin workflow answer a3f9c2 approval --input '{"approved": true, "reason": "ok"}'
# → validates, commits, gate answered
```

and the incremental flow falls out of the same command:

```bash
func builtin workflow answer a3f9c2 approval --set approved=true
# → draft saved; still missing: reason (string, required)

func builtin workflow answer a3f9c2 approval --set reason='"signed off by SRE"'
# → draft complete; validated; gate answered
```

`--no-commit` exists for the case where a second actor must review before the gate
opens.

### Editing an answered gate

`--reopen` is a separate, explicit verb — not a side effect of `--set`:

```bash
func builtin workflow answer a3f9c2 approval --reopen
# → payload moved back into draft; gate is pending again
```

Guarded: **refuse when the walk has already consumed the payload.** The walker records
the gate node as replayed and advances past it (`workflow_walker.py:298-301`), so a
scope whose `position` is past the gate has already used the answer. Reopening then
would silently diverge recorded results from the answer that produced them. Refuse with
the position, and point at a fresh scope. Only a gate whose scope is still `blocked` at
that gate may be reopened.

## 4. `--show` is the piece that makes it usable for an agent

```bash
$ func builtin workflow answer a3f9c2 approval --show --format json
{
  "workflow_id": "a3f9c2...", "gate": "approval", "model": "ApprovalInput",
  "input_schema": { ... },
  "draft": {"approved": true},
  "satisfied": ["approved"],
  "missing": [{"field": "reason", "type": "string", "required": true,
               "description": "Why this was approved"}],
  "invalid": [],
  "complete": false
}
```

`missing` / `invalid` come from the same `ValidationError` the commit path already
produces — `exc.errors()` gives field locations and messages. This is the one genuinely
new computation, and it is a projection over `model.model_fields` plus a trial
validation, not new state.

## 5. Surfaces — all three, one implementation

Lift the logic into `app/_workflow_resume.py` beside `deposit_gate_input`, the way
that function was itself lifted out of the MCP plugin. Then:

| Surface | Spelling |
|---|---|
| CLI | `func builtin workflow answer <id> <gate> --set … --show --commit` |
| MCP | `deposit_gate_input(workflow_id, gate, values, mode="merge"\|"replace", commit=true)` and `get_gate_draft(workflow_id, gate)` |
| Job flag | out of scope — deposit is a record-level verb (see §6) |

**Take the addressing fix while you are here.** The MCP tools cannot express
`(workflow_id, gate)` together: `resume_gate` takes a gate only, `resume_workflow` a
scope only, and each refers to the other on ambiguity. The new MCP tool should take
`workflow_id` **and** `gate`, with `gate` optional when exactly one is pending. That
restores the CLI↔MCP parity the previous study asserted already held.

## 6. What this does *not* solve

`deposit` still does not advance the walk. After a successful commit the scope is
answered but parked, and something must still re-invoke the job. That is the separate
`--wf-resume` / in-process-continue work, and it stays the higher priority of the two —
but the two are orthogonal and this one is strictly smaller.

The honest reason to keep them separate is in the codebase already
(`builtins.py:913-917`): deposit is a **second-actor** verb. A human elsewhere, an agent
without a runner, or a reviewer can answer a gate without being the party that runs the
walk. Partial deposit makes that role more useful, not less: two actors can now fill
different fields of the same gate.

## 7. Cost

| Piece | Size |
|---|---|
| `draft` field in `_blank_scope`'s gate record + store accessors | small |
| Merge / unset / clear / show / commit in `_workflow_resume.py` | ~120 lines |
| `--reopen` with the position guard | small |
| CLI command | ~60 lines, mirrors `workflow_resume` |
| MCP tool + `(workflow_id, gate)` addressing | ~60 lines |
| **Fix `payload` to store `model_dump()` on both paths** | 2 lines, do it first |

No engine change. No walker change. No new storage section — and therefore no
`STATE_VERSION` bump, which matters until [07-roadmap](13-roadmap.md) item 0 lands.
