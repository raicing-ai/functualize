# tasks.md — from-step-walk-reads

Base `master` `c03dfb72`. Every gate below runs from the worktree root with
`uv run …`. Every wave also passes `uv run ruff check`, `uv run ruff format
--check`, `uv run mypy src/` and `uv run lint-imports` (7 kept, 0 broken)
before its tasks are checked. Run pytest by tier
(`.agents/skills/test-tiers/scripts/tests-for-diff`); never one call over 600 s.

Reachability before `[x]`: each production task names its call path, and the
executor proves it by breaking that call and watching the named test fail
(commit first — `git checkout -- <file>` reverts everything uncommitted).

## Wave 0 — the defect, pinned red

- [x] **0.1 End-to-end tests, red on `master`**

New `tests/integration/test_from_step_reads_e2e.py`. One class per spec AC:
AC1 (boot blocks), AC2 (fresh-process resume via
`func builtin workflow resume <scope> --input '{"ok": true}'` in a subprocess;
`act` and the epilogue both receive `Approval(ok=True)`), AC3 (epilogue reads
a step), AC4 (unknown name refused at boot), AC5 (later node; a binding
naming its own gate), AC6 (two scopes plus a fingerprint record — a second
walk never sees the first's value), AC7 (job run outside a walk → message
names `FromStep`), AC9 (skipped branch: default used / no default fails —
use a `ConditionalEdge` graph), AC10 (deposit at a step name refused). Each
fixture module is compiled twice, with and without
`from __future__ import annotations` (AC11). Message assertions match on
`FromStep('<name>')`, the parameter name and the reader — not full text.

- Files: `tests/integration/test_from_step_reads_e2e.py`
- Gate: `uv run pytest tests/integration/test_from_step_reads_e2e.py -q` on
  unmodified `c03dfb72` — AC1 and AC10 pass, every other class fails. Record
  the exact pass/fail counts in this task when run.
- Base `c03dfb72` with the new test file: **4 passed, 18 failed** (AC1 and
  AC10 pass in both annotation modes; AC2–AC7 and AC9 fail in both modes).
  Run with `PYTHONPATH` set to that base checkout's `src` and the feature
  checkout's pytest executable, from the clean base checkout.

## Wave 1 — vocabulary (foundation layers only)

- [x] **1.1 `from_step_refs` and the refusal error**

`_types/from_job.py`: `from_step_refs(func) -> dict[str, FromStepParam]`
(`ref`, declared base type, `has_default`), via `resolved_hints` like
`from_job_refs`; plus `mixed_source_params(func) -> tuple[str, ...]` for a
parameter carrying both `FromJob` and `FromStep`. `from_job_refs`,
`from_job_names`, `from_job_types` unchanged. `_types/errors.py`:
`FromStepUnavailableError(Exception)` carrying `node`, `parameter`,
`reader`, `scope_id`, `reason`.

- Files: `src/functualize/_types/from_job.py`, `src/functualize/_types/errors.py`, `tests/test_from_job.py`
- Gate: `uv run pytest tests/test_from_job.py -q` green, including new
  `TestFromStepRefs` (both annotation modes; `from_job_refs` of a
  `FromStep`-only function is `{}`).
- Gate result: 38 passed. This is a foundation task: boot consumption is
  marked `TRANSITIONAL(3.1)` until wave 3 supplies its production call path.

## Wave 2 — the pure reader (imports 1.1's error)

- [x] **1.2 The pure reader**

New `_primitives/walk_reads.py`: `read_node(records, node, expected_type=None)`
returning `Recorded(value) | NotRecorded() | NotCarriable()`, matching the
record key's part before `::` against the canonical node name;
`resolve_bound_values(records, bound)` replacing every `FromStep` marker and
raising `FromStepUnavailableError` for anything but `Recorded`. Uses
`reusable_return_value` for the rebuild. No fingerprint input, no I/O.

- Files: `src/functualize/_primitives/walk_reads.py`, `tests/primitives/test_walk_reads.py`
- Gate: `uv run pytest tests/primitives/test_walk_reads.py -q` green;
  `rg -n "fingerprint_key|get_fingerprint" src/functualize/_primitives/walk_reads.py`
  returns 0 hits (R1 by construction).
- Gate result: 8 passed; the fingerprint search returned 0 hits. The reader
  and bound resolver are marked `TRANSITIONAL(3.2)` and `TRANSITIONAL(5.1)`
  until those waves supply their production call paths.

## Wave 3 — the engine

- [x] **3.1 Boot validation for every `FromStep` position**

`_engine/workflow_validation.py`: extract the ancestor computation
(`:52-66`) into a helper used by both checks; add
`_validate_workflow_from_step_refs(registered, nesting, resolve)` called from
`validate_workflow_declarations` beside the `FromJob` check (`:184`). Readers:
each `Step` job (B4.1, B4.2, B4.4, B4.5), the workflow function (B4.1, B4.5),
each `Gate`'s `tool_specs()` bindings (B4.1, B4.3). `ChoiceDecision.state` is
not checked. Messages per `contracts.md` §2. Module stays < 500 lines.

- Files: `src/functualize/_engine/workflow_validation.py`, `tests/engine/test_from_step_validation.py` (new)
- Gate: `uv run pytest tests/engine/test_from_step_validation.py -q` green;
  the existing `FromJob` validation messages unchanged
  (`uv run pytest tests/integration/test_declared_capabilities_e2e.py -q` green);
  `wc -l src/functualize/_engine/workflow_validation.py` < 500.
- Call path: `_app` boot → `validate_workflow_declarations` →
  `_validate_workflow_from_step_refs`. Sabotage: remove the call; AC4/AC5 in
  0.1 go red.
- Evidence at `807ea9d1`: validation and existing `FromJob` suites, 57 passed;
  AC4/AC5 passed before sabotage. Removing the validation call made all six
  AC4/AC5 variants fail (16 deselected); the committed file was restored.
  Module length 369 lines; lint, format, mypy and import contracts passed.

- [x] **3.2 Injection, outside the executor**

New `_engine/walk_reads.py`: `step_records(runtime_store, scope_id)`
(StepView → record mapping, the same port call `_from_job_value` makes) and
`inject_from_step(job_name, function, context, scope_id, records, live)`
applying spec B2/B5/D2: explicit argument wins; no scope → error; `Recorded`
→ inject and add to `context.injected`; `NotCarriable` → live value or error;
`NotRecorded` → declared default (D2) else error.

- Files: `src/functualize/_engine/walk_reads.py`, `tests/engine/test_walk_reads.py` (new)
- Gate: `uv run pytest tests/engine/test_walk_reads.py -q` green.
- Evidence: 8 passed; source lint, format, mypy (397 files), and all seven
  import contracts passed. The executor call remains transitional until 4.1.

## Wave 4 — wire the engine

- [x] **4.1 Executor: one call, one shared lookup**

`executor.py`: call `inject_from_step` right after `_inject_from_job`
(`:1456`), inside a `try` that converts `FromStepUnavailableError` with
`_failure_before_execution` (`:1627`). Rewrite `_from_job_value`'s in-walk
branch (`:2201-2228`) to `step_records` + `read_node` — behaviour-identical,
fingerprint fallthrough for `FromJob` kept.

- Files: `src/functualize/_engine/executor.py`
- Gate: AC1–AC3, AC6, AC7, AC9, AC11 in `tests/integration/test_from_step_reads_e2e.py`
  green; `uv run pytest tests/test_from_job.py tests/integration/test_workflow_as_job_e2e.py tests/engine/test_the_walk_on_both_stores.py -q`
  green (AC12); `wc -l src/functualize/_engine/executor.py` ≤ 2813.
- Call path: `JobExecutionEngine.execute` → (`:1456`) `inject_from_step`.
  Sabotage: remove the call; AC2 and AC3 go red.
- Evidence: all 22 end-to-end variants passed after injection (18 failed on
  the dispatched head). The `FromJob`, workflow-as-job, and both-store suites
  passed (84); workflow control and gate-name suites passed (59). The executor
  is 2780 lines; lint, format, mypy and import contracts passed. The resume
  CLI also prints a successful epilogue value so the fresh-process witness can
  observe the value already recorded in the scope.

## Wave 5 — the tool surfaces (5.2 precedes 5.3)

- [x] **5.1 Core gate-tool path**

Delete `_resolve_bound` (`app/_workflow_control.py:836-870`); `_bound_values`
(`:892`) calls `resolve_bound_values(scope["steps"].items(), spec.bound)`.

- Files: `src/functualize/app/_workflow_control.py`
- Gate: `rg -c "def _resolve_bound" src/functualize/app/_workflow_control.py`
  → 0; the core `call_gate_tool` tests green
  (`uv run pytest tests/workflow/test_workflow_control.py -q`).
- Evidence: core workflow-control suite 28 passed; `_resolve_bound` has zero
  definitions in the core module.

- [x] **5.2 MCP resolver test migration**

Update the four test call sites that used
`tools._resolve_bound` to call `resolve_bound_values` directly, and change
the two `None` pins to assert the §3 failure (spec *Deliberate behaviour
changes*); add a binding naming an earlier gate (AC8, D1).

- Files: `tests/plugins/test_gate_tool_narrowing.py`, `tests/integration/test_part_i_remaining_cells.py`
- Gate: `uv run pytest tests/plugins/test_gate_tool_narrowing.py tests/integration/test_part_i_remaining_cells.py -q` green; the four test calls use `resolve_bound_values` and no test calls `tools._resolve_bound`.
- Evidence: migrated suites 48 passed, including a binding that reads an
  earlier gate answer; no test calls the plugin resolver.
- Dependency: 5.3 deletes the old plugin resolver only after these tests
  exercise the shared reader.

- [x] **5.3 Fold the unused MCP declaration lookup into the live core path**

Before deletion, add tests in `tests/plugins/test_gate_tool_narrowing.py` that
invoke both the MCP `_call_gate_tool` and core `call_gate_tool` on the same
fixture. Pin the successful bound-value result and the exact error envelopes
for a missing scope and a forced declaration-load exception, including
`tool_unresolvable`'s `error` and `message`. Run these tests green before
editing plugin source. Then delete the plugin's unused `_bound_values`
(`_workflow_tools.py:475-515`), its now-unused `cast` import, and the plugin's
`_resolve_bound` (`:439-473`). Keep `_call_gate_tool`'s delegation to core
`call_gate_tool` (`:423-427`). Core `_bound_values` remains the sole declaration
lookup and keeps its `({}, None)` no-match return. Do not add a `PluginHost`
member: the live plugin path never accesses `execution_engine`.

- Files: `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py`, `tests/plugins/test_gate_tool_narrowing.py`
- Gate: `rg -n '_resolve_bound|_bound_values|cast\("Any", self\._app\)' plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py` → 0 hits (four now: two definitions, one call, one cast); `rg -n 'def _bound_values' src/functualize/app/_workflow_control.py` → one hit; `uv run pytest tests/plugins/test_gate_tool_narrowing.py tests/integration/test_part_i_remaining_cells.py -q` green, including the pre-deletion parity tests; `uv run pytest tests/spec/test_the_plugin_host_cannot_be_bypassed.py -q` green.
- Call path: MCP `_call_gate_tool` → core `call_gate_tool` → core
  `_bound_values` → `resolve_bound_values`. Sabotage the core
  `_bound_values` call in `call_gate_tool` after committing and verify the
  parity test fails, then restore it.
- Evidence: three parity tests passed before deletion; after deletion the
  plugin/integration/host suites passed (53). The removed symbols have zero
  hits in the plugin, and core `_bound_values` has one definition. Lint,
  format, mypy and all seven import contracts passed.

## Wave 6 — witnesses

- [ ] **6.1 Both stores and invoked children**

`tests/engine/test_the_walk_on_both_stores.py`: a "`FromStep` inside a walk
on SQLite" subject reading a step and a gate (R5). In
`tests/integration/test_from_step_reads_e2e.py`: a job invoked through
`Invoke` from inside a step that declares a `FromStep` parameter fails with
the outside-a-walk message (R4).

- Files: `tests/engine/test_the_walk_on_both_stores.py`, `tests/integration/test_from_step_reads_e2e.py`
- Gate: both files green on both store parametrisations; the full
  `test_from_step_reads_e2e.py` green (every AC).

## Wave 7 — documentation tells the truth (B6, AC13)

- [ ] **7.1 Docstrings and guides**

`FromStep` docstring (table row "this scope's steps only" → "this walk's
nodes"; positions per B1), `Gate` docstring (`_types/workflow.py:289-291` now
true — add how to read it), `docs/guides/workflows.md` (`:437-458` add
"Reading a gate's answer" with the approval example; `:495-511` the three
positions and D1/D2), `contributor/reference/workflow-walker.md` (`:44-50`
keep the subscript note, drop "`FromStep`'s implemented use is the gate-tool
binding"; `:89` split the row — `FromStep` never runs anything),
`skills/functualize/references/workflows.md:58,98`,
`skills/functualize/references/idiomatic.md:162-166`.

- Files: `src/functualize/_types/from_job.py`, `src/functualize/_types/workflow.py`, `docs/guides/workflows.md`, `contributor/reference/workflow-walker.md`, `skills/functualize/references/workflows.md`, `skills/functualize/references/idiomatic.md`
- Gate: `rg -n "this scope's steps only|Its use is binding a gate tool's argument|Reads a recorded step result, to bind a gate tool's argument|implemented use is the gate-tool binding|\`FromJob\` / \`FromStep\` injection" src docs contributor skills`
  → 0 hits (5 at authoring: `docs/guides/workflows.md:497`,
  `contributor/reference/workflow-walker.md:48,89`,
  `skills/functualize/references/workflows.md:58`,
  `src/functualize/_types/from_job.py:256`).

## Wave 8 — checkpoint

- [ ] **8.1 Verify**

All five checks; pytest by tier over the diff; dead-code delta
`uv run python .github/scripts/dead_code_delta.py c03dfb72 HEAD` with every
finding classified; the page's experiment re-run as AC1–AC6 with pasted
output, reading D1/D2 from `plan.md` → *Alignment*. Then the durable half
migrates (an ADR or `.spec/STATUS.md` entry recording option (i), D1, D2) and
the deletion-only clearing commit follows on a second push.

- Files: `.spec/STATUS.md` or `contributor/adr/<next>.md`
- Gate: every check green except the two artifact checks before clearing.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["0.1"]},
    {"id": 1, "tasks": ["1.1"]},
    {"id": 2, "tasks": ["1.2"]},
    {"id": 3, "tasks": ["3.1", "3.2"]},
    {"id": 4, "tasks": ["4.1"]},
    {"id": 5, "tasks": ["5.1", "5.2", "5.3"]},
    {"id": 6, "tasks": ["6.1"]},
    {"id": 7, "tasks": ["7.1"]},
    {"id": 8, "tasks": ["8.1"]}
  ]
}
```
