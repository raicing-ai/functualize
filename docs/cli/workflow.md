# Workflow Commands

The `func builtin workflow` (or `functualize builtin workflow`) sub-command
inspects and resumes **persisted workflow scopes** — the paused state a
`@workflow` leaves behind when it blocks at a gate awaiting input.

> **Note:** `func` and `functualize` are aliases for the same CLI. All examples
> below use `func` but `functualize` works identically.

These commands are the CLI half of the same operations the MCP workflow tools
expose to agents. `list`, `state`, and `cancel` read the state store directly;
`resume` deposits gate input through the same shared logic the MCP `resume_gate`
tool uses, so the two surfaces never drift.

## `func builtin workflow`

```
func builtin workflow COMMAND [ARGS]...
```

| Command | What it does |
|---------|--------------|
| `list` | List active (running or blocked) workflow scopes |
| `state <workflow_id>` | Show one scope's status, position, and pending gates |
| `resume <workflow_id> <gate>` | Deposit input for a blocked gate |
| `cancel <workflow_id>` | Cancel a workflow scope |

## `func builtin workflow list`

List every scope that is still running or blocked. Completed, failed, and
cancelled scopes are omitted.

```
func builtin workflow list [--format table|json]
```

`--format` is **domain-aware**: the command knows its items are workflow scopes,
so `json` emits structured scope objects (id, workflow, status, position,
pending gates) rather than a serialized log line. This is distinct from the
global `--output`, which only formats the dispatch layer's return value.

```bash
func builtin workflow list
# rel-1  release  blocked  gates: approval

func builtin workflow list --format json
```

## `func builtin workflow state`

Show one scope's status, walk position, and the gates awaiting input.

```
func builtin workflow state <workflow_id> [--format table|json]
```

## `func builtin workflow resume`

Deposit input for a blocked gate. The input is validated against the gate's
model and **nothing is stored if it fails**. Accepting input does not run the
workflow — invoke the workflow job again with the same `scope_id` to continue
past the gate.

```
func builtin workflow resume <workflow_id> <gate> [--input '<json>']
```

```bash
func builtin workflow resume rel-1 approval --input '{"environment": "prod", "replicas": 3}'
# Input accepted for gate 'approval'. Run the workflow job with scope_id 'rel-1' to continue past it.

func release --scope-id rel-1   # replays past the answered gate to completion
```

## `func builtin workflow cancel`

Mark a scope cancelled so it stops appearing in `list`.

```
func builtin workflow cancel <workflow_id>
```

## See also

- [Workflows Guide](../guides/workflows.md) — declaring `@workflow` graphs and gates
