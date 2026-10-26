# workflow-answer-input-guard

Feature branch `fix/fused-input-runtime-store`, base `11ed0e82`. One premise
expired mid-merge and one guard kept enforcing it. This spec retires the guard
and re-contracts the twin assertion that pinned the same dead outcome.

## The defect

`416420d7` added a refusal in `resume_scope`
(`src/functualize/app/_workflow_control.py`), immediately after the
`retry_epilogue` check:

```python
    if input is not None and isinstance(store, RuntimeStore):
        # Fused gate input still uses the document-only answer_gate path.
        # Before operator reads selected the runtime store, a relational
        # scope returned this clean error because the document store did not
        # contain it. Keep that public outcome until input recording moves to
        # the runtime port; never pass a runtime store to get_scope.
        return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")
```

Its own comment names the expiry — *"Keep that public outcome until input
recording moves to the runtime port"* — and `11ed0e82` (#119's squash) did
exactly that: `answer_gate` now records for both stores through the runtime
input port. The guard therefore refuses a case the merged tree delivers. No
parent's CI could see it: the guard did not exist on one parent, the
relational fusion test did not exist on the other, and the merge was
textually clean (`git merge-tree --write-tree` of the two parents equals the
merged tree), so the red is merge-only.

Reproduced on the merged head `11ed0e82` (probe = the ticket's acceptance
experiment, run 2026-10-26):

```
$ uv run pytest -q tests/cli/test_workflow_answer_relational.py tests/plugins/test_mcp_workflow_tools.py
1 failed, 60 passed in 18.99s
FAILED tests/cli/test_workflow_answer_relational.py::TestCliAnswerAndResume::test_resume_with_fused_input_answers_and_advances
E   AssertionError: {"error": "workflow_not_found", "message": "No workflow scope 'rel-1'."}
```

A second assertion site of the same premise is invisible to the ticket text:
`tests/plugins/test_mcp_workflow_tools.py::test_sqlite_resume_with_gate_input_returns_a_clean_error`
pins the refusal on the MCP surface
(`assert result == {"error": "workflow_not_found", "message": "No workflow scope 'sql-run'."}`).
With the guard deleted and nothing else touched, the whole fast tier runs
`1 failed, 12987 passed, 1652 skipped` and that one failure is this test —
a stale assertion, not a second defect.

## User stories

- An operator fuses answer and advance into one command on a project that
  selected the SQLite runtime store:
  `resume rel-1 --input '{"approved": true, "reason": "fused"}'` records the
  gate input and walks on, exactly as on the default store.
- An agent using the MCP `resume_workflow` tool gets the same fusion on a
  relational scope instead of a `workflow_not_found` denial of a scope
  `list_workflows` just showed it.

## Behaviour

### B1 — the fused resume records and advances, whichever store is selected

`resume_scope(input=...)` on a `RuntimeStore` follows the flow its docstring
already promises: read the scope through `_read_scope`, answer through
`answer_gate`, walk. The relational CLI contract
(`tests/cli/test_workflow_answer_relational.py`, unchanged) is the executable
form.

### B2 — the document-store path is byte-identical

The deleted block was `isinstance(store, RuntimeStore)`-gated and never fired
for the document store. Nothing about the legacy path changes.

### B3 — the MCP fused resume answers and advances

`resume_workflow` with `input` on a relational scope records the request and
its decision through the runtime input port (`InputRequest` lifecycle
`OPEN -> ACCEPTED -> CONSUMED`), the remaining steps run, and the walk
completes.

### B4 — refusals that are still true stay

`retry_epilogue` on a `RuntimeStore` is still refused
(`epilogue_retry_unsupported`) — the port has no step deletion.
`gate_not_found`, `ambiguous_gate`, `scope_cancelled` are unchanged.

## Acceptance criteria

| # | Check | Observable result |
| --- | --- | --- |
| AC-1 | `uv run pytest -q tests/cli/test_workflow_answer_relational.py` | `9 passed`, including `test_resume_with_fused_input_answers_and_advances`; the file is otherwise untouched (`b50c7ad7`'s contract) |
| AC-2 | `uv run pytest -q tests/plugins/test_mcp_workflow_tools.py` | green; `test_sqlite_resume_with_gate_input_answers_and_advances` asserts the fused resume records through the port (`inputs.for_gate("sql-run", "preferences")` request accepted then consumed, decision present) and the walk advances (`calls == ["travel_plan", "body"]`, `result["status"] == "success"`) |
| AC-3 | `uv run pytest -x -q --no-header` | green — the doc scenario's command, the full fast tier |
| AC-4 | `PATH="$PWD/.venv/bin:$PATH" python .agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/j-dev-contrib.toml --engine shell --allow-skips` | green |
| AC-5 | After the merge | `doc-verify`, `test-fast`, `test-full` green on `origin/master` (CI; not run here) |

AC-1..AC-4 are the wave gates in `tasks.md`. AC-5 is the post-merge
observation the ticket's acceptance names.

## Non-goals

- No change to `answer_gate`, the input port, or either store's writer.
- No new capability check or refusal: the port records for every store
  `resume_scope` accepts, so no scope shape still needs the deleted outcome
  (`contracts.md` §4).
- No weakening of `tests/cli/test_workflow_answer_relational.py`.
- No docs-site page beyond the changelog: the shape page's §1 transcript is
  already the documented contract.

## Deliberate behaviour changes

- `resume <scope> --input …` on a project that selected a `RuntimeStore`
  answers and advances instead of returning
  `{"error": "workflow_not_found", "message": "No workflow scope '<id>'."}`.
  That error string disappears for this call shape by design; a genuinely
  unknown scope still returns it from `_read_scope`'s miss.
- `test_sqlite_resume_with_gate_input_returns_a_clean_error` is renamed and
  re-contracted to assert the fusion (AC-2). Its old assertion **is** the
  defect and is preserved nowhere.

## Decisions

1. **Delete, do not narrow.** The guard's premise — *"Fused gate input still
   uses the document-only answer_gate path"* — is what `11ed0e82` removed. A
   narrower guard (a capability check, a scope-shape probe) would describe
   nothing real: `answer_gate` records through the port for every store
   `resume_scope` reads. Deleting the whole `if` is the smallest change that
   tells the truth.
2. **Rewrite the MCP twin, never delete it.** Its scenario (a relational
   scope, a fused `input`) is exactly the delivered contract's shape; only
   its asserted outcome was wrong. The file's discipline — every scope
   produced by running the real engine — is kept, and the new assertions
   mirror `tests/cli/test_workflow_answer_relational.py`'s vocabulary.
3. **Both surfaces assert where the record lives.** The relational CLI test
   asserts `_never_in_the_scope_document`; the MCP twin asserts the request
   and decision live in `app.workflow_runtime_store().inputs` and the
   document scope store still holds no `sql-run` scope.

## Out of scope, recorded

- The `retry_epilogue` refusal stays capability-shaped (the port has no step
  deletion) — `plan.md` § *Surviving smells*.
- Shape-page provisional items (JSON key spellings, exact error text) are not
  settled here.

## Confirmation gate

Authorisation for this package is the leader's re-route dispatch
(2026-10-26T13:54:38Z): design approved, spec and code deliberately run
together so master is not left red, member confirmation handled by the
review lane. The shape page is `Authority: Approved` (read live; see
`plan.md` § *Alignment*). Confirming the review confirms the deliberate
behaviour changes above, chiefly the disappearance of the
`workflow_not_found` outcome for a fused resume on a runtime store.
