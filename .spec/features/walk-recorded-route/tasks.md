# tasks.md — walk-recorded-route

Base `master` `91947bb`. Every gate runs from the worktree root with `uv run …`.
Every wave also passes `uv run ruff check`, `uv run ruff format --check`,
`uv run mypy src/` and `uv run lint-imports` before its tasks are checked. Run
pytest by tier (`.agents/skills/test-tiers/scripts/tests-for-diff`), never one
call over 600 s, and at most two invocations per verification. A test that
spawns `func` sets `HOME` and every `XDG_*` root.

Reachability before `[x]`: each production task names its call path. The
executor proves it by breaking that call and watching the named test fail.
Commit first, because `git checkout -- <file>` reverts everything uncommitted.

## Wave 0 — the defect, pinned red

- [x] **0.1 Both-store and CLI tests, red on `91947bb`**

New `tests/workflow/test_recorded_route_on_both_stores.py`, parametrized over
documents and sqlite (the pattern of `tests/engine/test_the_walk_on_both_stores.py`;
sqlite via `pytest.importorskip("functualize_substrate_sqlite")`). It walks
the spec's `release` graph (ConditionalEdge + `OnFailure`) and reads
`describe_scope(app, selected_workflow_store(app), id)` and
`list_scopes(...)`. One test per item:

- AC-1/AC-2: both keys, values, no `\x00`, the same on both stores;
- AC-3: a straight-line walk gives `{}` for both keys;
- AC-4: a `Notify` marker appears in neither key;
- AC-5: `OnFailure(target=END)` gives `"END"`;
- AC-6: `list_scopes` rows equal the `describe_scope` result;
- AC-11: order;
- one CLI subprocess test of `func builtin workflow show` text for AC-1 and
  AC-3 (`Branches: -`, `Failure routes: -`).

Extend `tests/integration/test_cli_workflow_parity.py` with AC-7 on a scope
that took a branch.

- Files: `tests/workflow/test_recorded_route_on_both_stores.py`,
  `tests/integration/test_cli_workflow_parity.py`
- Gate: on unmodified `91947bb`, the new file fails every test that asserts
  `failure_routes` or relational `branches`. Record the counts here (AC-12).
  Red baseline on the unchanged implementation at `179f9a81`: 7 failed,
  21 passed, across both stores and the CLI parity test. The first run before
  `uv sync --all-packages` was 3 failed, 3 skipped (SQLite unavailable).

## Wave 1 — port and declaration (foundation)

- [ ] **1.1 `WorkflowReader.branches` on the port and both stores**

Add `branches(scope_id) -> Mapping[str, str]` to the Protocol
(`_types/persistence.py`, beside `branch`, `:864`). Implement it in:

- `_DocumentWorkflowReader` (`_primitives/document_store.py`, beside `:342`):
  `dict` of `scope["branches"]`, `{}` when the scope is absent;
- `SqlWorkflowReader` (`_readers.py`, beside `:220`): one `SELECT … ORDER BY
  rowid`.

Contracts §4.

- Files: `src/functualize/_types/persistence.py`,
  `src/functualize/_primitives/document_store.py`,
  `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_readers.py`
- Gate: `uv run mypy src/` and `uv run lint-imports` clean; `uv run pytest
  tests/conformance/test_baseline.py -q` still green.
- Call path: `_workflow_view._port_record` (task 3.1); until then
  TRANSITIONAL, disclosed in the commit body.

- [ ] **1.2 Node names refuse NUL**

`Step`, `Gate` and `AgentStep` `__post_init__` raise `ValueError` per
contracts §7, beside each existing empty-name refusal.

- Files: `src/functualize/_types/workflow.py`, `tests/test_workflow_declaration.py`
- Gate: the AC-10 tests pass; `uv run pytest tests/test_workflow_declaration.py
  tests/workflow -q` green.
- Call path: node construction, which every `@workflow` declaration runs.

## Wave 2 — the encoding's owner, and conformance

- [ ] **2.1 `_engine/decision_keys.py`**

Move `_failure_branch`, `_notify_key` and `_ROUTED_TO_END` out of
`_engine/workflow_walker.py` (`:1098-1133`) as `failure_key`, `notify_key`
and `ROUTED_TO_END`. Re-point the three walker call sites (serena:
`_failure_route` ×2, `_notify` ×1). Add `RecordedRoute` (frozen; `branches`,
`failure_routes`) and `recorded_route(raw)`, per `plan.md` → *Approach* 3.
Unit tests cover:

- a conditional key;
- `\x00onfailure`;
- `\x00end` → `"END"`;
- a notify marker dropped;
- an unknown NUL key dropped;
- order kept.

- Files: `src/functualize/_engine/decision_keys.py`,
  `src/functualize/_engine/workflow_walker.py`, `tests/engine/test_decision_keys.py`
- Gate: the new unit tests pass. `uv run pytest tests/workflow/test_failure_routing.py
  tests/workflow/test_notify.py -q` passes **unchanged**, so stored keys are
  byte-identical. `lint-imports` clean.
- Call path: the walker's existing encode paths; decode is reached in 3.1.

- [ ] **2.2 Conformance check `record branch and branches`**

Add it to `testing/conformance/baseline.py` after `record branch and branch`
(`BASELINE`, `:470-484`): write `fork`, then `join`; assert the mapping and
its order; reopen and assert again; `branches("missing") == {}`. A store
without the reader fails with an `AssertionError` that names it (contracts §5).

- Files: `src/functualize/testing/conformance/baseline.py`
- Gate: `uv run pytest tests/conformance/test_baseline.py -q` green for
  documents and sqlite. Sabotage: drop the sqlite `ORDER BY rowid`, or the
  documents method, and watch it fail (AC-8).

## Wave 3 — the projection and the line

- [ ] **3.1 Projection and `show` text**

In `app/_workflow_view.py`:

- `_port_record` emits the raw `reader.branches(id)` and raises
  `ScopeStoreUnreadableError` (contracts §6 message) when the reader has no
  `branches`;
- `_describe` emits `branches` and `failure_routes` from
  `recorded_route(...)`, in contracts §2.7 order.

`_cli/builtins.py` `_render_scope` prints both lines, always, with `-` when
empty (contracts §1).

- Files: `src/functualize/app/_workflow_view.py`, `src/functualize/_cli/builtins.py`
- Gate: every 0.1 test is green; `uv run pytest tests/workflow
  tests/integration/test_cli_workflow_parity.py tests/plugins/test_mcp_workflow_tools.py -q`
  green.
- Call path: `describe_scope` / `list_scopes` → `_describe`, reached by every
  surface in contracts §3. Sabotage each of: `_port_record`'s read (0.1
  relational fails); the `recorded_route` call (AC-2 no-NUL fails); the
  `Failure routes:` echo (CLI test fails).

- [ ] **3.2 Refusal on every surface (tests only) — wave 4, after 3.1**

For a store whose `workflows` lacks `branches`, assert:

- `func builtin workflow show` exits 2 with the §6 message;
- `get_workflow_state`, `list_workflows` and `resume_workflow` return
  `scope_store_unreadable`;
- `--wf-show` exits 2 (via `click_params.py:1170`).

No surface code is expected to change (`plan.md` → *Approach* 5). If one has
to change, stop and report.

- Files: `tests/workflow/test_recorded_route_on_both_stores.py` (or a sibling
  `tests/workflow/test_recorded_route_refusal.py`)
- Gate: AC-9 green.

## Wave 4 — records (runs beside 3.2)

- [ ] **4.1 ADR-034, docs, changelog, codemap**

New `contributor/adr/034-operator-surfaces-read-decision-records-in-bulk.md`
(template `000-template.md`; links ADR-033 and ADR-025; records D2–D7 and the
surviving smells). Update:

- `docs/cli/workflow.md` § `workflow show` (contracts §9.1);
- `CHANGELOG.md` `[Unreleased]` (§9.2);
- `contributor/architecture/codemaps/data-flow.md:237` (add `branches` to the
  reader list).

- Files: the four above
- Gate: `uv run pytest tests/skills tests/docs -q` green (if present); the
  docs say what 3.1 does.

- [ ] **4.2 Example caller for the public member**

Extend `examples/standalone/workflow_store_read/test_workflow_store_read.py`
with `runtime.workflows.branches(...)` from a booted app (D7).

- Files: that file
- Gate: `uv run pytest examples/standalone/workflow_store_read -q` green.

## Wave 5 — verify and clear

- [ ] **5.1 Verification, reachability, clearing**

Run the full gates, including the tip tier dispatched to CI rather than
waited on. Re-run spec § *The defect* probe on both stores and paste its
output (AC-1, AC-2, AC-13 query count). Run `uv run python
.github/scripts/dead_code_delta.py 91947bb HEAD` and classify each finding.

ADR-034 is the durable half, and it lands in 4.1. The deletion-only
`git rm -r .spec/features/walk-recorded-route` commit is the **last** commit,
on a second push.

- Files: none beyond the clearing commit
- Gate: every required check green except the artifact checks before clearing.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["0.1"]},
    {"id": 1, "tasks": ["1.1", "1.2"]},
    {"id": 2, "tasks": ["2.1", "2.2"]},
    {"id": 3, "tasks": ["3.1"]},
    {"id": 4, "tasks": ["3.2", "4.1", "4.2"]},
    {"id": 5, "tasks": ["5.1"]}
  ]
}
```
