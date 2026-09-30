# gate-name-resolution — External contracts

No signature changes. Every function below keeps its parameters and its return
type. What changes is **which strings the `gate` parameter accepts** and **which
spelling and error code come back**.

## Public functions (`functualize.app.utils` re-exports)

| Function | Module | `gate` parameter — AFTER |
|---|---|---|
| `resolve_gate(store, scope_id, gate, *, include_answered=False) -> tuple[str, str] \| dict` | `app/_workflow_answer.py:48` | Any spelling resolving (B-1) to one gate of the scope; the returned tuple carries the **canonical** name |
| `answer_gate(app, store, scope_id, gate, values=None, *, …) -> dict` | `app/_workflow_answer.py:163` | Same |
| `gate_draft(app, store, scope_id, gate) -> dict` | `app/_workflow_answer.py:130` | Same |
| `deposit_gate_input(app, store, scope_id, gate, payload, *, source="api") -> dict` | `app/_workflow_resume.py:95` | Same |
| `resume_scope(app, store, scope_id, *, input=None, gate=None, …) -> dict` | `app/_workflow_control.py` | Same (via `answer_gate`) |
| `list_scopes(app, store, *, …, blocked_on=None) -> list[dict]` | `app/_workflow_view.py:261` | `blocked_on` matches any spelling resolving to a pending gate |

`pending_gates(scope)` is unchanged: it lists canonical keys.

## Result envelopes

Success envelopes are unchanged in shape. The `gate` field, and every message
that quotes the gate, carries the **canonical** name (B-3) — previously it
echoed the caller's string.

Refusal envelopes (flat, `error` is the machine code):

| Code | When — AFTER | Change |
|---|---|---|
| `gate_not_found` | The reference matches no gate recorded in the scope | **New fields:** message lists the scope's gate names; `gates: list[str]` (canonical, sorted). Now also returned by `gate_draft` and `deposit_gate_input`, which previously misreported this case |
| `ambiguous_gate` | The reference matches more than one recorded gate | Now possible from the both-named form of `resolve_gate` and from `answer_gate` / `gate_draft` / `deposit_gate_input`; carries `candidates` like the existing shape at `_workflow_answer.py:117-126` |
| `gate_unresolvable` | The workflow cannot be materialized (the model will not load) | **Narrowed:** no longer returned for a missing node; message never carries `AttributeError: 'NoneType'` |

*If D1 resolves to (a):* the `gate_not_found` row becomes
`raises functualize.types.GateNotFoundError(scope_id, gate, known: tuple[str, ...])`,
and every surface below gains a translation. This contract is written for (b).

## Surfaces

| Surface | Command / tool | AFTER |
|---|---|---|
| CLI | `func builtin workflow answer <workflow_id> <gate> [--input … --set … --show]` | Declared spelling accepted; unknown → `Error: …` on stderr, exit **1** (unchanged mapping, `_cli/builtins.py:1113`) |
| CLI | `func builtin workflow resume <workflow_id> [--input … --gate …]` | Same |
| CLI | `func builtin workflow list --blocked-on <gate>` | Declared spelling filters |
| CLI (fused) | `<entry> <workflow> --wf-resume <id> --wf-input '{…}' [--wf-gate <gate>]` | Same; unknown → exit 1 (unchanged) |
| MCP | `answer_gate`, `get_gate_draft`, `resume_workflow`, `list_workflows` | Declared spelling accepted; envelopes as above |

There is no MCP `resume_gate` tool on `master`; nothing named that is added.
