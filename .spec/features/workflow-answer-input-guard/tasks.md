# tasks.md — workflow-answer-input-guard

Base `11ed0e82`. Every gate runs from the worktree root with `uv run …`.
Every wave also passes `uv run ruff check --fix src/ tests/ plugins/ examples/`,
`uv run ruff format`, `uv run mypy src/` and `uv run lint-imports` before its
tasks are checked. At most two pytest invocations per verification step;
long logs go to `/tmp/functualize-<cmd>.log` and are tailed.

Reachability before `[x]`: each production task names its call path. The
executor proves it by breaking that call and watching the named test fail.
Commit first, because `git checkout -- <file>` reverts everything uncommitted.
For this repair the sabotage half already exists as the base run (task 0.1):
with the guard present, exactly the named test fails; deleting the call is
the restore (task 1.1), and 1.2/2.1 watch both surfaces.

## Wave 0 — the defect, pinned red

- [x] **0.1 The fused resume, red on `11ed0e82`**

Probe `uv run pytest -q tests/cli/test_workflow_answer_relational.py
tests/plugins/test_mcp_workflow_tools.py` on unmodified `11ed0e82` and record
the counts. Expected: `1 failed, 60 passed`, the failure being
`test_resume_with_fused_input_answers_and_advances` with
`{"error": "workflow_not_found", "message": "No workflow scope 'rel-1'."}`;
the MCP file passes because it pins the old contract.

- Files: none (probe only)
- Gate: counts recorded in `spec.md` § *The defect* (already written from
  `/tmp/functualize-repro.log`)

## Wave 1 — the guard and the twin

- [x] **1.1 Delete the expired guard in `resume_scope`**

Delete the `input is not None and isinstance(store, RuntimeStore)` refusal in
`src/functualize/app/_workflow_control.py` (`:351-357`), immediately after
the `retry_epilogue` check. Keep `retry_epilogue`; do not replace the deleted
block with any narrower refusal (contracts §4).

- Files: `src/functualize/app/_workflow_control.py`
- Call path: `workflow_resume` (`_cli/builtins.py:1538`) → `resume_scope`
  (`app/_workflow_control.py:295`) → `answer_gate`
  (`app/_workflow_answer.py:199`) → `store.inputs` writer;
  MCP twin `_resume_workflow`
  (`functualize_mcp/_workflow_tools.py:374`) → `resume_scope`.
- Gate: `uv run pytest -q tests/cli/test_workflow_answer_relational.py` →
  `9 passed`. Sabotage evidence is 0.1's red run (the guard present is the
  broken call); restoring the guard re-breaks
  `test_resume_with_fused_input_answers_and_advances`.

- [x] **1.2 Rewrite the MCP fused-resume test**

In `tests/plugins/test_mcp_workflow_tools.py`, rewrite
`test_sqlite_resume_with_gate_input_returns_a_clean_error` (≈`:157`) as
`test_sqlite_resume_with_gate_input_answers_and_advances`: same
`_gated_app(calls, sqlite=True)` fixture and `RunRequest` for scope
`sql-run`, but assert the relational vocabulary — before the call
`inputs.for_gate("sql-run", "preferences")` yields an OPEN request and no
decision; after it the request is `consumed`, `inputs.decision(...)` is
present, `result["status"] == "success"`, `result["return_value"] ==
"itinerary"`, `calls == ["travel_plan", "body"]`, the scope store still has
no `sql-run` scope, and the sqlite workflow view reports `completed`.

- Files: `tests/plugins/test_mcp_workflow_tools.py`
- Call path: MCP `resume_workflow` → `_resume_workflow` → `resume_scope`
  (same as 1.1)
- Gate: `uv run pytest -q tests/plugins/test_mcp_workflow_tools.py` green,
  the new test included.

## Wave 2 — the record

- [x] **2.1 CHANGELOG `### Fixed` entry**

Add one `## [Unreleased]` `### Fixed` entry in the file's house voice naming
the restored fused `resume … --input` on the runtime store (the
documented §1 contract), and that the `workflow_not_found` outcome for that
call shape is gone by design.

- Files: `CHANGELOG.md`
- Gate: file reads correctly at the `## [Unreleased]` heading; no test.

## Wave 3 — verify and clear

- [ ] **3.1 Full gates, then the clearing commit**

Run and record raw output: `uv run pytest -x -q --no-header` (green, the doc
scenario's command); `PATH="$PWD/.venv/bin:$PATH" python
.agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/
--engine shell --allow-skips` green (`j-dev-contrib`);
`uv run ruff check --fix src/ tests/ plugins/ examples/`, `uv run ruff
format`, `uv run mypy src/`, `uv run lint-imports` green. Then
`uv run python .github/scripts/dead_code_delta.py 11ed0e82 <head>` and paste
the output into the handoff. Two pushes: this package with the change first,
then `docs(spec): clear the completed workflow-answer-input-guard feature`
(`git rm -r .spec/features/workflow-answer-input-guard/`) because
`spec-artifacts-cleared` refuses a tree that keeps it.

- Files: none (verification); the clearing commit deletes the package
- Gate: every command above green; `contract-diff-carries-task-graph` is
  satisfied by this file existing in a commit of the range.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["0.1"]},
    {"id": 1, "tasks": ["1.1", "1.2"]},
    {"id": 2, "tasks": ["2.1"]},
    {"id": 3, "tasks": ["3.1"]}
  ]
}
```
