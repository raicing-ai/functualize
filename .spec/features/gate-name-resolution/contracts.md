# gate-name-resolution — External contracts

Written for D1 = (a), member, 2026-10-01. No parameter changes. What changes is
**which strings the `gate` parameter accepts**, **which spelling comes back**,
and **that an unknown gate in an addressed scope raises instead of returning**.

## C-1 — `GateNotFoundError` (new)

Defined in `src/functualize/_types/errors.py` beside the other refusals, and
re-exported from `functualize.app.utils` (the door `_cli` and plugins use —
the same route as `ScopeStoreUnreadableError`, `utils.py:82,282`).

```python
class GateNotFoundError(Exception):
    """Raised when a scope is addressed and the gate reference matches none of its gates."""

    def __init__(self, gate: str, *, scope_id: str, known: Sequence[str]) -> None:
        self.gate = gate                    # what the caller wrote, verbatim
        self.scope_id = scope_id
        self.known = tuple(sorted(known))   # the scope's gate names, canonical
        super().__init__(
            f"Workflow '{scope_id}' has no gate '{gate}'. "
            f"Gates: {', '.join(self.known) or 'none'}. "
            "Run `func builtin workflow list` to see what is waiting."
        )
```

- Base class `Exception`, like every class in `_types/errors.py`.
- The message carries names only, never payloads or draft values.

## C-2 — Public functions (`functualize.app.utils` re-exports)

| Function | Module | `gate` — AFTER | Raises `GateNotFoundError` when |
|---|---|---|---|
| `resolve_gate(store, scope_id, gate, *, include_answered=False) -> tuple[str, str] \| dict` | `app/_workflow_answer.py:48` | Any spelling resolving to one gate; the tuple carries the **canonical** name | `scope_id` **and** `gate` are both given and the scope has no such gate. With `scope_id=None` it never raises: no match keeps the existing `gate_not_found` **envelope** (B-8) |
| `answer_gate(app, store, scope_id, gate, values=None, *, …) -> dict` | `app/_workflow_answer.py:163` | Same | the scope has no such gate |
| `gate_draft(app, store, scope_id, gate) -> dict` | `app/_workflow_answer.py:130` | Same | the scope has no such gate |
| `deposit_gate_input(app, store, scope_id, gate, payload, *, source="api") -> dict` | `app/_workflow_resume.py:95` | Same | the scope has no such gate |
| `resume_scope(app, store, scope_id, *, input=None, gate=None, …) -> dict` | `app/_workflow_control.py` | Same (via `answer_gate`) | `gate` is given and the scope has no such gate (propagated from `answer_gate`) |
| `list_scopes(app, store, *, …, blocked_on=None) -> list[dict]` | `app/_workflow_view.py:261` | `blocked_on` matches any spelling of a pending gate | never — a filter |

`pending_gates(scope)` is unchanged: it lists canonical keys.

## C-3 — Result envelopes

- Success envelopes keep their shape. The `gate` field, and every message
  quoting the gate, carries the **canonical** name (B-3).
- `gate_not_found` **envelopes** remain only on the survey paths of B-8.
- `gate_unresolvable` keeps its meaning, *the model won't load*: the workflow
  cannot be materialized, or the scope records a gate the workflow no longer
  declares (drift). Its message never carries `AttributeError: 'NoneType'`.
- `ambiguous_gate` is unchanged (the cross-scope survey case).

## C-4 — Surfaces

| Surface | Command / tool | Unknown gate in an addressed scope — AFTER |
|---|---|---|
| CLI | `func builtin workflow answer <workflow_id> <gate> [--input … --set … --show]` | `Error: <C-1 message>` on stderr, exit **1** (unchanged code) |
| CLI | `func builtin workflow resume <workflow_id> --input … --gate <gate>` | Same |
| CLI (fused) | `<entry> <workflow> --wf-resume <id> --wf-input '{…}' --wf-gate <gate>` | Same, exit 1 |
| CLI | `func builtin workflow list --blocked-on <gate>` | Declared spelling filters; unknown → empty list |
| MCP | `answer_gate`, `get_gate_draft`, `resume_workflow` | **Returns** `{"error": "gate_not_found", "message": <C-1 message>, "gates": [<known>]}` |
| MCP | `list_workflows(blocked_on=…)` | Declared spelling filters; unknown → empty |

No surface lets the exception escape as a traceback. There is no MCP
`resume_gate` tool on `master`, and nothing by that name is added.
