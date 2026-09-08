# Contracts: workflow-state-durability

External interfaces only. Internal types and the on-disk layout are `schema.md` /
`plan.md`.

---

## 1. Public Python surface — `functualize.app.utils`

The public door both `_cli` and plugins import (`_cli` may import public folders only —
`pyproject.toml:294-308`). Today it re-exports `StateStore` and `resolve_state_path`
(`app/utils.py:44-46`, `:145-146`).

### 1.1 Unchanged signatures

`StateStore` keeps its scope API verbatim. Every caller below is external to
`_primitives` and must not need editing:

| Method | Callers |
|---|---|
| `StateStore.for_project(root: Path) -> StateStore` | `_cli/builtins.py`, `functualize-mcp` |
| `get_scope(scope_id) -> dict \| None` | `_cli/builtins.py`, `_workflow_tools.py`, `app/_workflow_resume.py` |
| `scope_ids() -> list[str]` | `_cli/builtins.py`, `_workflow_tools.py` |
| `get_gate(scope_id, gate_name) -> dict \| None` | `_engine/frontier.py` |
| `deposit_gate_payload(scope_id, gate_name, payload) -> bool` | `app/_workflow_resume.py` |
| `record_step`, `get_step`, `set_position`, `get_position`, `set_scope_status`, `ensure_scope`, `get_branch`, `put_gate`, `record_epilogue`, `get_epilogue`, `record_tool_call` | `_engine/frontier.py`, `_engine/workflow_walker.py`, `_engine/workflow_runner.py`, `_engine/executor.py` |
| `get_fingerprint`, `put_fingerprint`, `delete_fingerprint`, `fingerprint_keys` | `_engine/preflight.py` |
| `get_history`, `clear_session` | `_cli/builtins.py`, `_engine/executor.py` |

**Contract: no caller outside `_primitives` changes.** `StateStore` continues to present
one façade over both stores; which file a section lives in is not its callers' concern.

### 1.2 Changed signature

```python
StateStore.clear(*, scopes: bool = False) -> None
```

Clears fingerprints, history and session state. Scopes are cleared only when
`scopes=True`. Previously cleared everything unconditionally (AC-7, AC-9).

### 1.3 Added

```python
def resolve_scopes_path(root: Path | str) -> Path: ...
```

Sibling of the existing `resolve_state_path`, re-exported through
`functualize.app.utils` and added to its `__all__`. Needed by `func builtin state show`
to report the scope store's location (AC-11).

```python
class ScopeStoreUnreadableError(Exception): ...
```

Raised when the scope store exists but cannot be honoured — a version mismatch or corrupt
content (AC-4, AC-6). Suffixed `Error` per `CONSTITUTION.md` naming. Carries:

| Attribute | Type | Meaning |
|---|---|---|
| `path` | `Path` | the file that could not be read |
| `preserved_path` | `Path` | where it was moved |
| `scope_count` | `int \| None` | scopes visible in the old file, or `None` if unparseable |
| `found_version` / `expected_version` | `int \| None` / `int` | the mismatch, when that is the cause |

Exported from `functualize.types` alongside the other public error types.

## 2. CLI surface

### 2.1 `func builtin state clear`

```
Usage: func builtin state clear [OPTIONS]

  Reset derived runtime state — fingerprints, run history, and the session
  precondition cache. Workflow scopes are kept unless --scopes is passed.
  Never touches the discovery cache.

Options:
  --scopes  Also clear persisted workflow scopes, discarding any in-flight run.
```

Output with scopes present (AC-8):

```
Cleared fingerprints, history and session state.
Kept 3 workflow scopes — pass --scopes to clear those too.
```

With `--scopes` (AC-9):

```
Cleared fingerprints, history and session state.
Cleared 3 workflow scopes.
```

With none present:

```
Cleared fingerprints, history and session state.
```

Exit `0` in all three cases. Exit `0` and no output when neither file exists (current
behaviour).

### 2.2 `func builtin state show`

Gains two lines (AC-11); existing lines keep their wording and order:

```
Fingerprints: 12
Scopes:       3
History entries: 47
State path: /repo/.functualize/state.json
Scopes path: /repo/.functualize/scopes.json
Mode:       project
```

### 2.3 `state` group help

```
func builtin state --help
  Manage runtime state — fingerprints, history, session cache, and workflow scopes.
```

Replaces *"Manage the runtime state store (fingerprints, history)."* (AC-10).

### 2.4 Refusal on an unreadable scope store

Any command that would read scopes — a workflow job invocation, `builtin workflow
list|state|resume|cancel`, `builtin state show` — fails closed (AC-4, AC-6):

```
Error: .functualize/scopes.json cannot be read (found version 1, expected 2).
       It holds 3 workflow scopes, including any recorded gate input.

  Preserved as: .functualize/scopes.json.bak-v1
  To discard them and start fresh:
      func builtin state clear --scopes

exit 2
```

Exit `2` — usage/config, per `_types/exit_codes.py`. **Not** exit 1, and never exit 0
with an empty list.

## 3. MCP surface

**No tool signature changes.** `get_workflow_state`, `list_active_workflows`,
`resume_gate`, `resume_workflow`, `call_gate_tool` and `cancel_workflow` keep their
parameters and result shapes.

One added error envelope, matching the existing flat shape
(`_workflow_tools.py` `_error`):

```json
{
  "error": "scope_store_unreadable",
  "message": "Scope store cannot be read (found version 1, expected 2). 3 scopes preserved at .functualize/scopes.json.bak-v1.",
  "preserved_path": ".functualize/scopes.json.bak-v1",
  "scope_count": 3
}
```

Returned by any workflow tool that would otherwise report an empty or missing scope.

## 4. Unchanged contracts

Called out because they are the regression surface:

- **Exit codes.** `0` success · `1` job raised · `2` usage/config · `3` refused ·
  `4` stale · `5` blocked. Exit 5 keeps printing the scope id and gate name on stderr
  (AC-13).
- **`JobResult.metadata`** keys on a block — `workflow_scope`, `workflow_status`,
  `blocked_on`, `blocked_reason` — unchanged in name and meaning.
- **`deposit_gate_input(app, store, scope_id, gate, payload) -> dict`** and
  **`pending_gates(scope) -> list[tuple[str, dict]]`** in `app/_workflow_resume.py`:
  signatures and result dicts unchanged.
- **Scope record shape.** `{workflow, status, steps, branches, gates, position, epilogue,
  tool_calls}` — no field added, renamed or removed. The `{str: record}` section layout is
  preserved so the `StateBackend` seam stays open.
- **`functualize-state` / `functualize-state-sqlite`** are untouched. The scope store is
  core and unconditional; no optional package is required to read or write it (AC-15).
