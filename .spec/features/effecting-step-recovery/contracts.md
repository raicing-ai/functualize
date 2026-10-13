# effecting-step-recovery — contracts

External interfaces only: what a workflow author, an operator, a surface, or a
reader of the stored record can see. Internal types and storage mechanics belong in
`plan.md`.

## C1 — `Step(effecting=...)` (Python, `functualize.workflow`)

```python
@dataclass(frozen=True)
class Step:
    job: str | Callable[..., Any]
    effecting: bool = False      # signature unchanged
```

The signature and default are unchanged. What changes is what the flag means:

| `effecting` | On a resume after a crash inside the step |
|---|---|
| `False` (default) | The step runs again. Unchanged |
| `True` | The step is never run again without a decision. It stops in doubt on its recovery gate (C2) |

Refusals:

| Condition | When | Error |
|---|---|---|
| A declared node's name equals a derived recovery-gate name (C2) | declaration time (the `@workflow` decorator) | `ValueError`, raised beside today's "Duplicate workflow node name" |
| `effecting=True` on a `Step` whose job is itself a workflow | boot validation | `WorkflowDeclarationError` |

## C2 — The recovery gate

**Name:** `<step-name>-in-doubt`, where `<step-name>` is the step's graph key
(including any group, e.g. `billing.refund-in-doubt`). It goes through the same
canonicalisation as every gate name, so `refund_in_doubt` resolves to it.

**Exists** for every `Step` declared `effecting=True`. It is returned by
`WorkflowDeclaration.node(name)` and appears in the workflow shape (C5). **Opened**
only when a walk finds the step in doubt.

**Answer schema** (the JSON schema published with the gate request):

```json
{
  "type": "object",
  "properties": {
    "outcome": {"type": "string", "enum": ["ran", "did_not_run"]},
    "value": {}
  },
  "required": ["outcome"],
  "additionalProperties": false
}
```

There is no default for `outcome`. `value` is optional and only meaningful with
`"ran"`.

**Answered through** the existing surfaces, unchanged in form:

```bash
func <workflow> --wf-resume <scope> --wf-input '{"outcome": "ran"}'
func builtin workflow answer <scope> refund-in-doubt --input '{"outcome": "did_not_run"}'
```

The same gate is answerable through `answer_gate(...)` and the MCP gate tools.

**Never answered by:** the config chain (`resolve`), `ai_inbound`, `ai_outbound`,
`decision`, a default, a cancelled prompt, or a timeout. Its only automatic rung is
reserved for a future reconciler (shape D3) and is not part of this feature.

**Effect of each outcome:**

| `outcome` | Step record afterwards | Walk |
|---|---|---|
| `ran` | `status: success`. `return_value` = `value`. With no `value`: `return_value: null`, `return_value_reusable: false` | continues past the step |
| `did_not_run` | the attempt is discarded, and the step runs again as attempt *n+1* | continues by running the step |

## C3 — The step record (stored; read by status, API/MCP and auditors)

The `status` vocabulary gains two values. Neither is a terminal success.

| `status` | Meaning | Written when |
|---|---|---|
| `attempting` | The job of an effecting step was handed control, and its ending is not yet recorded | immediately before an effecting step's job runs |
| `in_doubt` | A walk found `attempting` and stopped. Whether the effect happened is unknown | on resume, or on reclaim of an abandoned scope |

Fields carried by an `attempting` record, and kept on the `in_doubt` record that
replaces it:

| Field | Type | Meaning |
|---|---|---|
| `effecting` | `true` | what the step was when it started (already written today on completion) |
| `attempt` | int ≥ 1 | which attempt this is. Starts at 1 and increases on `did_not_run` |
| `attempt_key` | string | a stable identity built from scope id, step key (including loop pass) and attempt number. Recorded for a future reconciler; not exposed to jobs here |
| `started_at` | ISO-8601 string | when the attempt was recorded |
| `generation` | int | the lease generation of the walk that recorded it |

Records of pure steps carry none of these fields. They are unchanged byte-for-byte.

## C4 — The scope, as status and API/MCP report it

When a walk stops in doubt:

| Field | Value |
|---|---|
| `status` | `blocked` (existing value) |
| `blocked_on` | `<step-name>-in-doubt` |
| `blocked_reason` | begins `in_doubt:` and names the step, the attempt number and `started_at` |
| `WalkOutcome` | `BLOCKED` (existing value). No new outcome |

Walk events: no new event names. The stop is reported as the existing `step.end`
with the blocked outcome for the step.

## C5 — Workflow shape (discovery cache, schema §2 `workflow` entry) and graph digest

Following the existing "only when declared" rule (`_types/workflow.py:780-783`):

```json
{"step": "refund", "effecting": true}
{"gate": "refund-in-doubt", "model": "InDoubt", "recovers": "refund"}
```

- A step that is not effecting projects as today: `{"step": name}`.
- The recovery gate entry appears only for effecting steps, and adds no edges.
- `CACHE_VERSION` moves from 21 to 22, because the cache entry's schema changes.
- `graph_digest` is unchanged as a function. Its value changes only for workflows
  with an effecting step.

## C6 — Documentation strings

`Step.effecting`, `GraphModel.is_effecting` and `docs/guides/workflows.md` state:

> An in-flight effecting step is never re-run without a decision, and it is
> exactly-once once that decision is made.

They include the D5 caveat that a raise is the job's own account. They contain no
"at-most-once" claim.
