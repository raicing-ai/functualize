# Contracts — workflow-continuation

External interfaces only. Internal types are in `schema.md`.

---

## 1. `functualize.app.utils` — the shared implementation

Every verb has **one** implementation here. `_cli` may import public folders only, so
this is the only legal arrangement (`.spec/ARCHITECTURE.md` layer rules); the MCP plugin
imports the same names.

```python
# --- projection (item 3) ---
def describe_scope(app, store, scope_id: str) -> dict | None: ...
def list_scopes(
    app, store, *,
    workflow_name: str | None = None,
    state: str | None = None,
    blocked_on: str | None = None,
) -> list[dict]: ...
def derived_state(scope: dict) -> str: ...

# --- gate answers (item 4) ---
def answer_gate(
    app, store, scope_id: str, gate: str, values: dict, *,
    mode: str = "merge",          # "merge" | "replace"
    unset: list[str] | None = None,
    clear: bool = False,
    commit: bool = True,
    reopen: bool = False,
) -> dict: ...
def gate_draft(app, store, scope_id: str, gate: str) -> dict: ...
def resolve_gate(store, scope_id: str | None, gate: str | None) -> tuple[str, str] | dict:
    """Joint addressing. Returns (scope_id, gate) or an error envelope."""

# --- continuation (item 5) ---
def resume_scope(
    app, store, scope_id: str, *,
    input: dict | None = None,
    gate: str | None = None,
    retry_epilogue: bool = False,
) -> dict: ...
def advanceable_scopes(store, workflow_name: str | None = None) -> list[str]: ...

# --- gate tools (item 3) ---
def call_gate_tool(app, store, scope_id: str, tool: str, args: dict | None = None) -> dict: ...

# --- management ---
def cancel_scope(store, scope_id: str) -> dict: ...
def purge_scopes(store, *, older_than: str | None = None, state: str | None = None) -> dict: ...
```

`deposit_gate_input` and `pending_gates` keep their current names and signatures —
`deposit_gate_input` is accurate about mechanism where `answer` is accurate about intent.

## 2. The scope projection

Returned identically by `builtin workflow show --format json`, `--wf-show` and MCP
`get_workflow_state`. **AC-6 asserts byte-identical JSON.**

```jsonc
{
  "workflow_id": "a3f9c2e1b7d4",
  "workflow": "release",
  "status": "blocked",          // stored
  "state": "waiting",           // derived — spec §3.2
  "steps": [ {"name": "build", "kind": "step"}, ... ],
  "edges": [ {"source": "build", "target": "approve"}, ... ],
  "current_position": "approve",
  "results": {
    "build": {"status": "success", "return_value": "v2",
              "inputs": {}, "completed_at": "..."}
  },
  "branches": {"check": "deploy"},
  "epilogue": {"status": "success", "return_value": "shipped"} | null,
  "pending_gates": [ {
      "gate": "approve",
      "model": "Approval",
      "input_schema": {...},
      "unresolved_fields": ["reason"],
      "draft": {"approved": true} | null,
      "tools": [ {"tool": "read-file", "bound": ["allowed"], "schema": {...}} ],
      "blocked_at": "...",
      "workflow_context": {"workflow_id": ..., "workflow": ..., "position": ...}
  } ]
}
```

The list row (`list --format json`, `list_workflows`) is the projection **minus**
`steps`, `edges`, `results` and `branches` — id, workflow, status, state,
current_position, and gate names. Same derivation, one function.

## 3. MCP tools — the tier-2 surface

Renamed and added; every one accepts the same identifiers as its CLI twin.

| Tool | Signature | Change |
|---|---|---|
| `get_workflow_state` | `(workflow_id)` | + `state`, `draft`, `epilogue` |
| `list_workflows` | `(workflow_name?, state?, blocked_on?)` | **renamed** from `list_active_workflows`; gains filters |
| `answer_gate` | `(workflow_id?, gate?, values, mode?, commit?, reopen?, unset?, clear?)` | **new** — replaces `resume_gate` |
| `resume_workflow` | `(workflow_id?, input?, gate?, retry_epilogue?)` | now **advances**; `workflow_id` optional when one is advanceable |
| `call_gate_tool` | `(workflow_id, tool, args?)` | unchanged |
| `cancel_workflow` | `(workflow_id)` | now enforced |
| `purge_workflows` | `(older_than?, state?)` | **new** |

`resume_gate` and `list_active_workflows` are **removed**, not aliased. Pre-release, no
shims (`.spec/CONSTITUTION.md`).

## 4. MCP execution doors — the metadata contract

`run_job`, `run_job_async` → `get_execution_status`, `_execute_job` and every per-job tool
return:

```jsonc
{
  "status": "blocked",          // str, always; lowercase RunStatus.value
  "return_value": ...,
  "duration_ms": 12.3,
  "metadata": {                 // NEW — verbatim JobResult.metadata
    "workflow_scope": "a3f9c2e1b7d4",
    "workflow_status": "blocked",
    "blocked_on": ["approve"],
    "blocked_reason": "..."
  }
}
```

`metadata` is `{}` for a job that produces none — the key is always present, so a caller
never branches on its absence.

## 5. `MCPConfig`

```python
job_tools: Literal["all", "tagged", "none"] = "all"
job_tools_tag: str = "mcp"     # which tag "tagged" selects
```

Composes with the existing `include_tags` / `exclude_tags` / `exclude_jobs` /
`visibility` filters: `job_tools` decides the **candidate set**, the existing filters
narrow it.

## 6. Click surface

### 6.1 `func builtin workflow`

```
list    [--workflow NAME] [--state STATE] [--blocked-on GATE] [--format table|json]
show    <id> [--format table|json]
answer  <id> <gate> [--input JSON] [--set K=V]... [--unset K]... [--clear]
                    [--replace] [--show] [--commit/--no-commit] [--reopen]
                    [--format table|json]
resume  <id> [--input JSON] [--gate NAME] [--retry-epilogue]
             [--no-epilogue|--epilogue-only]
gate-tool <id> <tool> [--args JSON]
cancel  <id>
purge   [--older-than DURATION] [--state STATE]
```

`state` is **removed** and replaced by `show` — same argument, strictly more output.

### 6.2 `--wf-*` on a `@workflow` job

Spec §3.4. Two injection points, `click_params.py` (cold) and `lazy_command.py` (warm);
`pitfalls.md` §23 — every assertion runs on both.

### 6.3 Removed

- pre-command `--scope-id` (`_cli/dispatch.py:79`, `_GLOBAL_OPTIONS_ALWAYS_VALUE`)
- `GlobalOptions.scope_id` and its `_assign_option` branch
- `scope_id` from four `main.py` handler signatures and their call sites
- per-command `_scope_id_option()` and `_SCOPE_ID_PARAM`
- `create_job_click_command(workflow_scope_id=...)` and the
  `app_ref._workflow_scope_id` fallback

`app._workflow_scope_id` is **retained as an API-only seam** for embedded hosts that set
it programmatically, documented as having no CLI spelling.

## 7. Error codes — one table, both surfaces

| Code | CLI exit | Meaning |
|---|---|---|
| `workflow_not_found` | 1 | no scope with that id |
| `gate_not_found` | 1 | no such gate pending |
| `ambiguous_gate` | 2 | several gates pending; name one |
| `ambiguous_scope` | 2 | several advanceable scopes; name one |
| `no_advanceable_scope` | 1 | none to advance; names the survey verb |
| `scope_cancelled` | 2 | terminal; start fresh |
| `validation_error` | 1 | draft does not satisfy the model |
| `gate_unresolvable` | 1 | the gate's model will not load |
| `gate_already_consumed` | 2 | `--reopen` past the walk position |
| `tool_not_permitted` | 2 | gate policy |
| `argument_not_permitted` | 2 | bound argument supplied |
| `scope_store_unreadable` | 2 | unchanged (shipped in `24c5cc0`) |
