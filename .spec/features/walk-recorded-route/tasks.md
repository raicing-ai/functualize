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
Wave 0 deliberately preserves the red baseline. Wave 1 closes only the
independent declaration change; its focused pytest gate excludes wave 0's
projection tests, which remain red until wave 2. Tasks 1.1, 2.1, 3.1 and 4.2
join 1.3 in one integration wave: the already-written readers remain transitional and
unchecked until 3.1 supplies the relational production caller and 4.2
supplies a public caller for the documents port. Run each named task
gate against the integrated wave 2 code before checking any of those tasks or
starting wave 3. A green focused gate never stands in for the deferred
workflow gate, which runs at 3.1.

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
  An added isolated CLI subprocess test also fails as expected on the
  still-unprojected code (1 failed, because `Branches: -` is absent).

## Wave 1 — independent declaration refusal

- [x] **1.2 Node names refuse NUL**

`Step`, `Gate` and `AgentStep` `__post_init__` raise `ValueError` per
contracts §7, beside each existing empty-name refusal.

- Files: `src/functualize/_types/workflow.py`, `tests/test_workflow_declaration.py`
- Gate: AC-10 and the declaration suite: `uv run pytest
  tests/test_workflow_declaration.py -q --no-header` green. On `44168c54`
  this gate is 25 passed. This explicitly narrows the old gate: its
  `tests/workflow` portion contains wave 0's intentionally red projection
  tests (10 failed, 523 passed, 24 skipped at `44168c54`) and is deferred to
  task 3.1 in wave 2. Do not claim that broader suite is green here.
- Call path: node construction, which every `@workflow` declaration runs.
  Sabotage one NUL check after committing and verify its AC-10 case fails.
- Evidence: at `c3f13d1c` the gate is 25 passed, with `ruff check`, `ruff
  format --check`, `mypy src/` and `lint-imports` clean. Sabotage: `Gate`'s
  NUL check disabled after commit → `test_node_names_refuse_nul[<lambda>1]`
  failed (1 failed, 2 passed); restored with `git checkout --`.
  Follow-up `11d3d68f`: the message now has contracts §7.2's shape
  (`<Kind> name must not contain a NUL character ('\x00'): <repr>`), from one
  helper; the test asserts the exact message. Gate 25 passed; disabling the
  helper's check fails all three cases.

## Wave 2 — integrate the reader, encoding owner and projection

**Status at `11710023`: integrated; ordering A approved; no wave 2 task checked.**
The four original tasks' code is committed. Every gate below was green except
one test of the deferred 3.1 gate:
`test_choices_and_failure_routes_are_separate_and_ordered[documents]`, the
AC-11 recording-order case on the documents store. The cause is a false plan
premise, not the projection. `atomic_write_json`
(`_primitives/fresh_format.py:217`), the only writer `JsonFileSubstrate` uses,
calls `json.dump(..., sort_keys=True)`, so `scopes.json` stores `branches` in
key order and recording order is gone before any reader runs. Plan *Approach*
2 claimed "the JSON object keeps insertion order across a `scopes.json` round
trip". It does not. SQLite keeps rowid order and passes. Settling contracts
§2.6/§4.3 against §8.1 was a design decision. The member chose ordering A in
comment `01a15671` at `2026-10-19T23:13:37Z`: preserve recording order by
stopping the shared document writer from sorting keys. Task 1.3 and the
revised contracts §8.1 and plan *Approach* 2 carry that decision. Wave 2
was left open until its full gate turned green; wave 3 had not started.

Evidence at `ed05211`: the targeted store, decoder, conformance and example
gate passed (136); the deferred workflow/CLI/MCP gate passed (580 passed, 24
skipped); the root step selection passed (1780 passed, 36 skipped), and the
SQLite plugin selection passed (186). Ruff check, Ruff format check, mypy and
lint-imports passed. Restoring `sort_keys=True` only for sabotage after commit
made the document round-trip/eviction test and the document AC-11 test fail
(2 failed, 1 passed including SQLite); the committed writer was restored.
The integrated reader, decoder, projection and example call paths and their
sabotages were recorded at `38328d83`. All their named gates now pass.

Evidence at `38328d83`:

- Deferred 3.1 gate (`tests/workflow`, CLI parity, MCP workflow tools):
  1 failed (above), 579 passed, 24 skipped.
- Step tier from `tests-for-diff` without `tests/workflow`, plus
  `tests/conformance/test_baseline.py`: 1168 passed, 35 skipped. SQLite plugin
  tests: 186 passed.
- `tests/engine/test_decision_keys.py`, `test_failure_routing.py` and
  `test_notify.py` (both unchanged): 73 passed.
- `examples/standalone/workflow_store_read`: 3 passed, both stores.
- `ruff check`, `ruff format --check`, `mypy src/` and `lint-imports` are clean.
  The `TRANSITIONAL(3.1)` reader markers are removed because both callers exist.
- Sabotage after commit, each restored with `git checkout --`. Every run also
  shows the known documents-order red.
  - SQLite reader returns `{}`: 0.1 sqlite cases and the sqlite example fail.
  - Documents reader returns `{}`: 0.1 documents walk cases and the documents
    example fail.
  - `_port_record` emits `{}`: relational and port-backed 0.1 cases fail.
  - `_describe` emits raw records in place of `recorded_route(...)`: the AC-2,
    AC-4 and walk cases fail on both stores.
  - The `Failure routes:` echo is removed: both CLI text tests fail.

- [x] **1.3 Documents store writes in recording order**

Remove `sort_keys=True` from `atomic_write_json`. Preserve mapping insertion
order across document writes so raw workflow branches retain recording order
and scope retention drops the oldest finished scope. The same payload still
writes identical bytes on repetition. Existing documents keep their stored
order; there is no migration or backfill.

- Files: `src/functualize/_primitives/fresh_format.py`,
  `tests/primitives/test_scope_cap.py`
- Gate: the new document round-trip, eviction, and repeat-write assertions
  pass; 0.1's AC-11 passes on documents and sqlite; the deferred 3.1 gate and
  the step tier pass.
- Call path: `RecordBranch` → `ScopeStore.record_branch` →
  `JsonFileSubstrate.write` → `atomic_write_json` → reloaded
  `_DocumentWorkflowReader.branches` → `describe_scope`. Scope retention uses
  the same write/read path before `_trim`. After committing, restore
  `sort_keys=True` once and confirm both ordering and eviction tests fail;
  then restore the committed implementation.

- [x] **1.1 `WorkflowReader.branches` on the port and both stores**

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
- Gate, after 3.1 and 4.2 in this wave: `uv run mypy src/` and `uv run lint-imports`
  clean; `uv run pytest tests/conformance/test_baseline.py -q --no-header`
  green; the relational AC-1/AC-2 projection tests in 0.1 and the 4.2
  public caller green.
- Call path: `func builtin workflow show` / `get_workflow_state` →
  `describe_scope` → `_port_record` (3.1) → `store.workflows.branches` →
  `SqlWorkflowReader.branches`; the documents reader is reached through a
  booted app's public `RuntimeStore.workflows.branches` caller (4.2).
  Sabotage each store's reader and confirm respectively that 0.1 and the
  example fail. The readers are transitional until 3.1 and 4.2 are committed;
  leave 1.1 unchecked until both call paths, this gate and sabotage pass.

- [x] **2.1 `_engine/decision_keys.py`**

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
- Gate, after 3.1 in this wave: the new unit tests pass; `uv run pytest
  tests/workflow/test_failure_routing.py tests/workflow/test_notify.py -q
  --no-header` passes **unchanged**, so stored keys are byte-identical;
  0.1's AC-2 and AC-4 projection tests pass; `lint-imports` clean.
- Call path: the walker's existing encode paths → `decision_keys` when a
  walk records a failure route or notification; `describe_scope` → `_describe`
  (3.1) → `recorded_route` decodes that record. Sabotage the decoder call and
  confirm AC-2 fails. Leave 2.1 unchecked until both paths and its gate pass.

- [x] **3.1 Projection and `show` text**

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
  tests/integration/test_cli_workflow_parity.py tests/plugins/test_mcp_workflow_tools.py
  -q --no-header` green. This is the deferred whole-workflow gate from 1.2.
- Call path: `describe_scope` / `list_scopes` → `_describe`, reached by every
  surface in contracts §3. Sabotage each of: `_port_record`'s read (0.1
  relational fails); the `recorded_route` call (AC-2 no-NUL fails); the
  `Failure routes:` echo (CLI test fails).

- [x] **4.2 Example caller for the public member**

Extend `examples/standalone/workflow_store_read/test_workflow_store_read.py`
with `runtime.workflows.branches(...)` from a booted app (D7). Exercise both
store implementations through the public port so 1.1's reachability proof
covers both before wave 3.

- Files: that file
- Gate: `uv run pytest examples/standalone/workflow_store_read -q --no-header`
  green on both stores. Sabotage each reader after committing and confirm its
  example case fails.
- Call path: example caller → booted app's `RuntimeStore.workflows.branches`
  → each built-in reader; this is the public API's production entry path.

## Wave 3 — conformance and refusal

**Scope revision at 3.2 (resolved).** The refusal test exercises a real booted
SQLite app whose `SqlWorkflowReader.branches` member is removed after a scope
has been recorded. `builtin workflow show` exits 2 with the upgrade message,
and MCP `get_workflow_state` and `list_workflows` return
`scope_store_unreadable`. Two required surfaces failed the original
tests-only gate:

- MCP `resume_workflow("route", {})` returned `workflow_not_found` for that
  existing SQLite scope because `WorkflowToolProvider._resume_workflow` read
  its legacy document `self.store`, rather than `operator_store`.
- `--wf-show route` exited 1 with `_BranchReaderMissingError` instead of
  mapping it to the usage refusal. The eager click callback called
  `apply_workflow_flags` before entering `prelude_refusal`.

The focused gate was 2 failed, 1 passed. Task 3.2 is therefore widened to the
two surface fixes: the pause it declared is resolved by that revision, not by
a design change. Ruff check, Ruff format check, mypy and lint-imports passed
at the paused head.

- [x] **2.2 Conformance check `record branch and branches`**

Add it to `testing/conformance/baseline.py` after `record branch and branch`
(`BASELINE`, `:470-484`): write `fork`, then `join`; assert the mapping and
its order; reopen and assert again; `branches("missing") == {}`. A store
without the reader fails with an `AssertionError` that names it (contracts §5).

- Files: `src/functualize/testing/conformance/baseline.py`
- Gate: `uv run pytest tests/conformance/test_baseline.py -q --no-header` green for
  documents and sqlite. Sabotage: reverse the sqlite ordering to
  `ORDER BY rowid DESC`, or break the documents method, and watch the order
  assertion fail (AC-8). Merely dropping `ORDER BY` can retain rowid order.
- Evidence: 33 passed for the full baseline; reversing SQLite's read order
  after commit made the new check fail (1 failed, 32 deselected), then the
  reader was restored. Production caller: `run_baseline` → `BASELINE` →
  `record_branch_and_branches` → public writer and reader on a reopened store.

- [x] **3.2 Refusal on every surface**

For a store whose `workflows` lacks `branches`, assert:

- `func builtin workflow show` exits 2 with the §6 message;
- `get_workflow_state`, `list_workflows` and `resume_workflow` return
  `scope_store_unreadable`;
- `--wf-show` exits 2 (via `click_params.py:1170`).

A tests-only gate cannot hold: contracts §6.1 ("Every surface in §3 refuses
instead of emitting `{}`") is only true when the refusal reaches the MCP tool
and the CLI flag surface, not just `builtin workflow show`. Two surface fixes
are therefore in this task:

- `_resume_workflow` reads `operator_store`, like its siblings
  `get_workflow_state`, `list_workflows` and `cancel_workflow`;
- the eager and lazy click wrappers enter `prelude_refusal` **before**
  `apply_workflow_flags`, so a flag-surface refusal maps to exit 2 instead of
  escaping as a traceback.

`resume_scope` reads its head scope through `_read_scope`, so the fixed tool
reaches a relational store instead of calling a document-only `get_scope`.
`retry_epilogue` and `--wf-input` on a relational store stay out of scope
(ADR-033's open migration).

- Files: `tests/workflow/test_recorded_route_refusal.py` (new),
  `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py`,
  `src/functualize/app/_workflow_control.py`,
  `src/functualize/app/adapters/click_params.py`,
  `src/functualize/app/adapters/lazy_command.py`
- Gate: `uv run pytest tests/workflow/test_recorded_route_refusal.py -q
  --no-header` green for AC-9; the wave 2 projection
  remains green. Sabotage the missing-reader guard in `_port_record` and
  verify the refusal test fails.

- Evidence: red baseline at the paused head was 2 failed, 1 passed
  (`resume_workflow` → `workflow_not_found`; `--wf-show` exit 1 with
  `_BranchReaderMissingError`); after the two surface fixes the file is 3
  passed, and the wider set (`test_lazy_wrapper`, `test_lazy_wrapper_properties`,
  `test_cold_warm_history_parity`, `test_workflow_control`,
  `test_mcp_workflow_tools`) is 133 passed, 11 skipped. Sabotaging
  `_port_record`'s `if not callable(read_branches)` guard makes all three
  refuse-test cases fail (`'NoneType' object is not callable`, `assert 1 == 2`),
  so the gate measures the guard rather than incidental behaviour. Ruff check,
  Ruff format check, mypy and lint-imports passed after the fixes.

## Wave 4 — records

- [ ] **4.1 ADR-034, docs, changelog, codemap**

New `contributor/adr/034-operator-surfaces-read-decision-records-in-bulk.md`
(template `000-template.md`; links ADR-033 and ADR-025; records D2–D7 and the
surviving smells). Update:

- `docs/cli/workflow.md` § `workflow show` (contracts §9.1);
- `CHANGELOG.md` `[Unreleased]` (§9.2);
- `contributor/architecture/codemaps/data-flow.md:237` (add `branches` to the
  reader list).

- Files: the four above
- Gate: `uv run pytest tests/skills tests/test_contributor_docs.py -q
  --no-header` green; the docs say what 3.1 does. There is no `tests/docs`
  directory at `44168c54`, so the former command could not execute.

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
    {"id": 1, "tasks": ["1.2"]},
    {"id": 2, "tasks": ["1.3", "1.1", "2.1", "3.1", "4.2"]},
    {"id": 3, "tasks": ["2.2", "3.2"]},
    {"id": 4, "tasks": ["4.1"]},
    {"id": 5, "tasks": ["5.1"]}
  ]
}
```
