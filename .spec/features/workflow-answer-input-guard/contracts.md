# contracts.md — workflow-answer-input-guard

## 1. `resume <scope> --input <json>` — fused answer and advance (CLI)

`func builtin workflow resume` (`src/functualize/_cli/builtins.py`,
`workflow_resume`) with `--input` records the gate input and advances the
walk **in one call**, on every store `resume_scope` accepts.

```console
$ func builtin workflow resume rel-1 --input '{"approved": true, "reason": "fused"}' --format json
{"status": "success", "workflow_id": "rel-1", "return_value": "itinerary", ...}
```

- Identifiers are illustrative (shape page §7).
- Success shape is whatever `resume_scope` already returns:
  `{"status", "workflow_id", "return_value", "metadata", "scope"}`.
- Binding (shape page §1, §5): "`answer` records; `resume` advances" — the
  fused form is the §1 transcript's second command carrying the first's
  `--input`. `--input` and `--format json` are binding; added JSON identity
  key spellings stay provisional and are not added by this feature.
- Executable form: `tests/cli/test_workflow_answer_relational.py`
  (`test_resume_with_fused_input_answers_and_advances`) and the document-store
  twins (`test_it_answers_and_advances_in_one_call`,
  `test_it_actually_runs_the_remaining_steps`).

## 2. MCP `resume_workflow` — the same fusion

`resume_workflow` with `input`
(`plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py`,
`_resume_workflow`) calls `resume_scope(..., source="mcp", surface="mcp.tool")`
on the operator's selected store and returns the same success shape:

```python
result["status"] == "success"
result["return_value"] == "itinerary"
```

- Executable form: `tests/plugins/test_mcp_workflow_tools.py`,
  `test_sqlite_resume_with_gate_input_answers_and_advances` (sqlite project,
  scope `sql-run`): the remaining steps run
  (`calls == ["travel_plan", "body"]`) and the request is consumed.
- The adapter stays thin: it decodes the payload and delegates. No adapter
  field is part of gate authority (shape page §8, *Transport*).

## 3. Where the record lives — the runtime input port

The fused input is recorded through the runtime input port, exactly as
`answer` records it (shape page §8, *Runtime records*: "Selected
`RuntimeStore` owns durable request, candidate, decision, evidence reference,
transition and outbox intent. No `scopes.json` read is needed to retrieve
interaction evidence."):

- `store.inputs.for_gate(scope_id, gate)` yields the `InputRequest`;
  the walk's use of the answer moves it `OPEN -> ACCEPTED -> CONSUMED`.
- `store.inputs.decision(...)` holds the recorded decision.
- The scope document never holds it: `ScopeStore(...).get_scope(scope_id)` is
  `None` on a relational project, before and after the fused resume.

## 4. Refusals — what is still refused, and why

| Condition | Outcome | Why |
| --- | --- | --- |
| Unknown scope | `workflow_not_found` (`_read_scope`'s miss) | unchanged |
| Fused input at a retry epilogue on a `RuntimeStore` | `epilogue_retry_unsupported` | the port has no step deletion (spec B4) |
| No pending gate / ambiguous gate | `gate_not_found` / `ambiguous_gate` | unchanged |
| Cancelled scope | `scope_cancelled` | unchanged |

**Nothing is refused merely because the store is a `RuntimeStore`.** The
deleted guard's outcome (`workflow_not_found` for a *present* relational
scope) is gone by design (spec § *Deliberate behaviour changes*). If a future
store shape cannot record fused input, the refusal must be a store capability
check — never an `isinstance(store, RuntimeStore)` branch.

## 5. Unchanged external surfaces

- `tests/cli/test_workflow_answer_relational.py` is not edited: every
  assertion `b50c7ad7` pinned keeps pinning the same thing.
- `answer_gate`, `answer_scope`, `answer_scope_by_gate`, `pending_gates`,
  `_read_scope` and the two stores' writers keep their signatures and
  behaviour.
- The `retry_epilogue` refusal keeps its exact message and call site.

## 6. Documentation and changelog

- `CHANGELOG.md` `## [Unreleased]` gains one `### Fixed` entry naming the
  restored fused `resume … --input` on the runtime store, in the file's
  house voice (`### Fixed — <title>` + prose).
- No docs-site page: the shape page §1 transcript is the documented contract.
- These feature artifacts are cleared before merge (`docs(spec): clear the
  completed workflow-answer-input-guard feature`); the changelog entry is the
  durable record.
