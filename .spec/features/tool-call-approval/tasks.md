# Tasks — tool-call-approval

Wave ordering is binding: never start a task in wave N+1 while wave N has
unchecked tasks. A task is `[x]` only when its own acceptance gate is
green against the code as it stands.

## Wave 0 — domain plugin surface (`functualize_ai`)

### 1.1 Types and exports

- [x] Add `ToolCallContext` (frozen dataclass: `job_name`, `description`)
  to `_types.py`; add `requires_approval: bool = False` and
  `approval_gate: … | None = None` to `ToolDef` after `config_class`
  (contracts C1, C2). Export `ToolCallContext` from `__init__.py`
  (`__all__` + lazy map, beside `ToolDef`).
- Files: `_types.py`, `__init__.py`.
- Gate: `uv run pytest -n auto -q --no-header tests/plugins/test_tool_scope.py -k 'approval or tool_def_construction'`
  plus a new test in `tests/plugins/test_tool_scope.py` constructing
  `ToolDef` positionally and by keyword with no approval members (E10) and
  asserting `functualize_ai.ToolCallContext` is importable and frozen.

### 1.2 Approval decision module

- [x] Create `_approval.py`: `refusal_message`, `is_tool_refusal`,
  `evaluate_tool_approval` (strict `is True`; deny-all on missing gate;
  marks + re-raises gate failures), `mark_gate_failure`,
  `unwrap_gate_failure` (schema.md §"Gate-failure marker").
- Files: `_approval.py` (new).
- Gate: new unit tests in `tests/plugins/test_tool_scope.py` (or a sibling
  file if cleaner) covering: ungated `ToolDef` → `None`; `(True, None)` →
  refusal message; `True` admits; `False`/`None`/`1`/`"yes"` deny (E4 at
  helper level); raising gate → tool flag untouched, original exception
  re-raised with the marker set; `is_tool_refusal` round-trips
  `refusal_message` and rejects other strings.

### 1.3 Per-filter approval on `ToolScope`

- [x] `_FilterApproval` + `_ScopeFilter.approval`; `approval_required()`
  stamps every filter (append gate; no gate ⇒ stamped with empty tuple);
  `__add__` concatenates filters unchanged and drops the scope-level
  merge; `requires_approval`/`approval_gate` computed per contracts C4
  (docstring marks `approval_gate` not authoritative for mixed scopes);
  `with_instructions` passes filters through; remove the dead
  `_approval_required`/`_approval_gate` stored fields.
- Files: `_tool_scope.py`.
- Gate: `uv run pytest -n auto -q --no-header tests/plugins/test_tool_scope.py`
  — existing approval/union tests must still pass (property semantics
  keep `test_union_merges_approval` green), plus new tests: stamping is
  per filter; `a.approval_required(g) + b` leaves `b`'s filter unstamped;
  double-apply keeps both gates in order (E8 at scope level);
  `with_instructions` preserves stamps; `approval_gate` returns first
  gate in filter order for both union orders.

### 1.4 `to_tool_defs` folding

- [x] Keep first-seen-wins for the def; AND-fold approval from every
  matching filter; gated wins regardless of filter order; fold gate tuples
  via `_fold_gates` (schema.md) into `ToolDef.requires_approval` /
  `approval_gate`.
- Files: `_tool_scope.py`.
- Gate: new tests in `tests/plugins/test_tool_scope.py`: ungated scope →
  every def `(False, None)` (E1 control at scope level); stamped no-gate
  → `(True, None)`; single gate identity-preserved; two stamps →
  folded callable ANDs (allow,g1)+(deny,g2) refused, (deny,g1)+(allow,g2)
  refused (E8); `b + a.approval_required(g)` resolving one name → gated
  regardless of order (E7); same-name defs from mixed scopes keep the
  first-seen def's payload with combined approval.

## Wave 1 — enforcement and surfacing

### 2.1 Translator enforcement (D7a choke point)

- [x] `_wrapper` calls `evaluate_tool_approval(tool_def, kwargs)` before
  `original_fn`; refusal → return the message; gate failure → propagate.
- Files: `functualize_ai_pydantic/_tool_translator.py`.
- Gate: new tests in
  `plugins/domains/functualize-ai-pydantic/tests/test_tool_approval.py`
  driving `ToolScopeTranslator.translate` directly: gated def refuses
  (function never called, message returned), ungated def runs, strict
  True enforced through the wrapper.

### 2.2 `PydanticAI` loops: events + exception surfacing

- [x] `run_agent_loop` and `run_with_history`: `AI_TOOL_CALLED` status
  via `is_tool_refusal`; relabel arm re-raises `unwrap_gate_failure(exc)`
  before the `AINotAvailableError` wrap (contracts C6, C7).
- Files: `functualize_ai_pydantic/_pydantic_ai.py`.
- Gate: E1–E9 in `test_tool_approval.py` via `TestModel` scoped to
  `PydanticAI.run_agent_loop` / `run_with_history` (loop completes,
  refusal text in tool_calls, `status="denied"` captured through a fake
  event bus, gate `RuntimeError` reaches the caller unwrapped).

### 2.3 `AI.run`: events + exception surfacing

- [x] Same two changes at `_ai.py` `run()`'s emission and generic
  relabel sites.
- Files: `functualize_ai/_ai.py`.
- Gate: E9 leg via `AI(provider=PydanticAIProvider(cfg))`.run(tools=…)
  in `test_tool_approval.py`; E5 leg (gate exception unwrapped through
  `AI.run`); E1 control leg through `AI.run` (events identical shape,
  `status="success"`).

## Wave 2 — docs, verification, delivery

### 3.1 Docs and docstrings agree with the code

- [x] Replace `docs/guides/ai.md:101-104` example block with shape D8's
  exact block (real gate, no-gate deny-all form) + the three prose
  sentences; update docstrings: `approval_required` (typed contract),
  `requires_approval` (any-filter semantics), `approval_gate` (first
  gate; not authoritative for mixed scopes), `ToolDef` (new members),
  `ToolCallContext`.
- Files: `docs/guides/ai.md`, `_tool_scope.py`, `_types.py`.
- Gate: `git grep -n "approval_required()" -- docs/guides/ai.md` shows
  only the deny-all annotated form; the doc example's gate signature
  `(tool_name, args, ctx)` matches C3; `uv run pytest -n auto -q
  --no-header tests/plugins/test_tool_scope.py` still green (docstring
  edits don't move behavior).

### 3.2 Full verification + reachability sabotage

- [x] Run: `uv run ruff check src/ tests/ plugins/`, `uv run ruff format
  --check src/ tests/ plugins/`, `uv run mypy src/`, `uv run
  lint-imports`; step tier via
  `.agents/skills/test-tiers/scripts/tests-for-diff --run`; plugin tests
  `uv run pytest -n auto -q --no-header plugins/domains/functualize-ai-pydantic/tests/
  plugins/domains/functualize-ai/tests/`; `uv run pytest -n auto -q
  --no-header tests/plugins/`; examples suite
  `uv run pytest examples/ -q` (workspace packages import
  `functualize_ai`). Then, with everything committed: sabotage — comment
  out the `evaluate_tool_approval` call in `_wrapper`, assert E2 fails
  (reachability proof: the gate is on the production call path, H1),
  `git checkout --` restore.
- Gate: all of the above green in one pass; the sabotage step observed
  red then restored green.

### 3.3 Delivery

- [x] Dead-code delta `uv run python .github/scripts/dead_code_delta.py
  c75a476e <head>`; migrate the durable half to `.spec/STATUS.md`;
  final deletion-only commit removing `.spec/features/tool-call-approval/`;
  push branch `feat/tool-call-approval` (conventional-commit title/body,
  no tracker keys, no agent identities); open PR.
- Gate: `dead_code_delta` reviewed (advisory); `git log --format='%B'`
  hygiene read-back clean; PR opened with the checks listed.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4"]},
    {"id": 1, "tasks": ["2.1", "2.2", "2.3"]},
    {"id": 2, "tasks": ["3.1", "3.2", "3.3"]}
  ]
}
```
