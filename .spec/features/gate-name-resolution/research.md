# gate-name-resolution — Research (retrieval record)

Checkout `fix/gate-name-resolution` at `e7a93bf`, 2026-09-30. Every command ran
from the repository root.

## Specify pass — prior art (zvec-grep) and premises (rg)

`zg status` reported *not configured*; index built under the standing
authorization: 13 364 entities, 1 m 13 s, glob `src/**|docs/**|contributor/**|plugins/**|*.md`.

| Query | What it found that matters |
|---|---|
| `zg query "gate name canonical spelling resume by declared name"` | `_types/naming.py:99-156` (`resolve_name`), `app/_workflow_answer.py:48-127` (`resolve_gate`). No ADR or guide on gate-name spelling |
| `zg query "resolve_name single naming policy every consumer"` | Consumers: `_engine/job_graph.py`, `_engine/executor.py`, `_discovery/registry.py`, `app/vault.py:243` — **no gate-answer path** |
| `zg query "return error envelope dict versus raise exception public API surfaces"` + `rg` over `.spec contributor docs` | `.spec/STATUS.md:1155` *"the exception is returned, never raised"*; `contributor/reference/pitfalls.md` §25 *a new error … escapes as a traceback* (twice). Both inform D1 |
| `zg query "gate_not_found gate_unresolvable error code"` | Only the code under change; no ADR. `contributor/adr/029-gate-resolution-is-recorded-not-recomputed.md` concerns candidate recording, not names |

| Premise | Command | Result |
|---|---|---|
| No test asserts `gate_unresolvable` | `rg -n gate_unresolvable src plugins tests docs` | 3 hits, all `src/` (`_workflow_resume.py:87,113`, `_cli/builtins.py:1116`); 0 in `tests/` |
| No MCP `resume_gate` tool | `rg -n 'resume_gate' plugins/**/src` | Docstring mentions only; tool list via `dir(WorkflowToolProvider)` has no `_resume_gate` |
| `deposit_gate_input` has no production caller | `rg -n 'deposit_gate_input' src plugins` | definition + `utils.py:142,210` re-export + docstrings |
| `app/` does not use `resolve_name` for gates | `rg -n resolve_name src/functualize/app` | `utils.py:105,312`, `vault.py:243,251,261` |
| Refusal-envelope census | `rg -c '"error"\|_error\(' app/_workflow_{answer,resume,control}.py` | 13 / 6 / 24 = 43 lines |
| PR #71 file overlap | `git diff --stat e7a93bf...origin/sdd/decision-provider-seam -- src plugins` | touches `_types/workflow.py`, `_types/errors.py`, `_engine/gate_service.py`, `_gate/*`; **none** of `app/_workflow_*`, `_cli/builtins.py`, MCP `_workflow_tools.py` |

## Probe (live behavior on `e7a93bf`)

A scratch pytest under `tests/workflow/` (deleted after; not committed) declared
`build → Gate(name="approve_refund", awaits=Approval) → deploy`, ran it to
`blocked`, and called every entry with four spellings. Output (abridged):

```
PROBE status blocked … pending ['approve-refund']
PROBE == approve_refund
  resolve_gate(both):      gate_not_found  "Workflow 'rel-1' has no gate 'approve_refund'."
  resolve_gate(gate only): gate_not_found  "No workflow is awaiting 'approve_refund'. …"
  gate_draft:              gate_unresolvable  "… AttributeError: 'NoneType' object has no attribute 'awaits'"
PROBE == approve-refund    ('rel-1', 'approve-refund') ×2; gate_draft ok
PROBE == approveRefund     same as approve_refund
PROBE == nope              same as approve_refund
PROBE deposit_gate_input underscore: gate_unresolvable (AttributeError text)
PROBE answer_gate underscore:        gate_not_found
PROBE resume_scope underscore:       gate_not_found
PROBE after: status blocked payload None
PROBE canonical resume_scope: {'status': 'success'}
```

Note: running the same probe as a bare `uv run python` script outside pytest
wrote to a substrate `ScopeStore.for_project` did not read back (`scope_ids() == []`);
the `tests/conftest.py` environment isolation (strips `FUNCTUALIZE_*`/`XDG_*`)
is what makes the store agree. Integration tests for this feature must use the
repo fixtures, not an ad-hoc script.

## Plan pass 3a — architecture

- **serena** (activated by absolute path): `find_referencing_symbols
  _resolve_gate_model` → 3 callers (`gate_draft`, `answer_gate`,
  `deposit_gate_input`); `resolve_gate` → MCP `_answer_gate:282`,
  `_get_gate_draft:319`, `workflow_flags._record:421`, `utils` re-export, tests.
- **graphify** `get_neighbors _workflow_answer.py`: imports from
  `_workflow_resume.py`; imported by `utils.py`, `_workflow_control.py`.
  Staleness check failed — `graph.json`'s `built_at_commit` (`2269b8d`) is not
  an ancestor of this checkout — so it is used for direction only.
- **Codemaps**: `contributor/architecture/codemaps/*.md` do not mention
  `_workflow_answer`, `_workflow_resume`, `workflow_flags` or the MCP workflow
  tools (`rg` → 0). `data-flow.md` §5 covers gate *resolution by strategy* in
  the engine, not answering. No contradiction; a coverage gap, not in scope.

## Plan pass 3b — blast radius (the task hit sets)

```
rg -n 'get_gate\(|get_gate_draft\(|put_gate_draft\(|clear_gate_draft\(|declaration\.node\(|name == (gate|blocked_on)' \
   src/functualize/app plugins/adapters/functualize-mcp/src
```

14 hits: `_workflow_resume.py:83,122`; `_workflow_answer.py:79,100,144,145,195,208,220,229,239,266`;
`_workflow_view.py:319`; and `_workflow_tools.py:317` (a method *name*
`_get_gate_draft`, a false positive — the MCP file needs no edit because every
tool routes through `resolve_gate` / `answer_gate` / `gate_draft` /
`resume_scope` / `list_scopes`). So `src/` edits are exactly three files:
`app/_workflow_resume.py`, `app/_workflow_answer.py`, `app/_workflow_view.py`.
