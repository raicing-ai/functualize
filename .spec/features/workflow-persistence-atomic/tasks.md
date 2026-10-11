# workflow-persistence-atomic — Tasks

Base `0ede988b`. Each task is 1–3 production files plus tests unless it says why not.

**Wave ordering is binding:** never start a task in wave N+1 while wave N has unchecked tasks.
**Reachability precedes `[x]`:** name the production call path and prove it by breaking the call
and watching a test fail. **Commit before sabotaging.** **Every wave is reachability-closed**: a
task's call path and its close-together partners are in its own wave or an earlier one (the check
at the foot of this file), so no pair can deadlock the binding rule.

**Decision gate:** wave 5 waits on D-W1 (`spec.md` §6). Waves 0–4 do not.

PLUGIN = `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/`;
PLUGIN_TESTS = `plugins/substrates/functualize-substrate-sqlite/tests/`.

## Wave 0 — schema revision `0002`

- [x] **W1** Step-record metadata columns
      *Files:* `PLUGIN/_schema/0002_step_record_metadata.sql` (new), `PLUGIN/_migrations.py` (ship
      the revision), `PLUGIN/_legacy_source.py` (map `return_value_kind`/`return_value_type`/
      `effecting` when present), `PLUGIN_TESTS/test_migrations.py`.
      *Gate (W-AC-5):* a version-1 database (laid down by the existing harness) → `prepare` →
      version 2, three new columns present (`PRAGMA table_info(workflow_steps)`), `effecting`
      defaults 0; `0001`'s checksum unchanged; the migration harness's `historical` gains
      `"version-1"` and the `versioned_migrations` tier passes with it.
      *Call path:* boot step 6.5 → `SqliteRuntimeStoreFactory.prepare` → `migrate` (existing).
      *Sabotage:* drop `0002` from the shipped list → the version-2 test fails.
      *Done (`af6e0c75`):* boot step 6.5 → `SqliteRuntimeStoreFactory.prepare` →
      `migrate` applies revision 2. Removing revision 2 from `SHIPPED_MIGRATIONS`
      made `test_prepare_upgrades_a_version_1_file_and_defaults_step_metadata`
      fail (`[(1,)] != [(2,)]`); the committed file was restored. The plugin
      suite passed (174), the capability tier passed (13), and `lint-imports`
      kept all seven contracts.

## Wave 1 — the lease slice (the defect itself)

- [x] **W2** `RenewLease` / `ReleaseLease` in the vocabulary and the document store
      *Files:* `src/functualize/_types/persistence.py`, `src/functualize/_primitives/document_store.py`,
      `tests/primitives/test_document_runtime_store.py`.
      *Do:* contracts §1.1/§1.2 for the two commands; the document store applies them through
      `ScopeStore.renew_scope` / `release_scope` with the command's generation.
      *Call path:* W4, same wave (closes together with W3, W4).
      *Done (`d5d18b01`):* the document port applies both commands through
      `ScopeStore` with the held generation; W4 proves the production call.
- [x] **W3** The same two on SQLite
      *Files:* `PLUGIN/_workflow_sql.py`, `PLUGIN_TESTS/test_workflow_sql.py`.
      *Do:* contracts §2 — one conditional `UPDATE` each; release clears `lease_owner`, sets
      `lease_expires_at = now`, keeps `lease_generation`.
      *Call path:* W4, same wave.
      *Done (`d5d18b01`):* SQL renew/release are conditional fenced updates;
      W4 proves the selected-store path and the second-process claim.
- [x] **W4** `FrontierWalk.renew` / `release` through the port
      *Depends on:* W2, W3.
      *Files:* `src/functualize/_engine/frontier.py`, `tests/engine/test_walk_leases_through_the_port.py` (new).
      *Do:* `renew()` and `release()` issue the commands in a port transaction; best-effort
      `except` kept. The legacy hold stays for the walk's other writes until wave 2 — mark it
      `# TRANSITIONAL(workflow-persistence-atomic W7): …`.
      *Gate:* on **both** stores: a walk claims, releases; a second process claims **without
      force** and receives generation N+1 (not `Conflict`); a stale renew and a stale release from
      the first walk land nothing.
      *Sabotage (ticks W2, W3, W4):* route `release()` back to `self._store.release_scope` → on
      SQLite the second process gets `Conflict`.
      *Done (`d5d18b01`):* boot-selected runtime store → engine →
      `FrontierWalk.renew/release` → transaction workflow writer → document
      lease or SQLite conditional update. The two-store, second-OS-process test
      passed (2); routing release back to `ScopeStore` made the SQLite case fail
      with `Conflict(scope_id='s1', held_generation=1)` instead of `Claimed`.
      Restored: 2 passed. The focused root suite passed (62), the plugin suite
      passed (175), mypy found no issues, and `lint-imports` kept seven contracts.

## Wave 2 — the records slice (the walk leaves `ScopeStore`)

- [ ] **W5** The rest of the vocabulary, and the document store
      *Files:* `src/functualize/_types/persistence.py`, `src/functualize/_primitives/document_store.py`,
      `tests/primitives/test_document_runtime_store.py`.
      *Do:* `StartWalk`, `RecordStep`, `RecordBranch`, `MoveScope`, the `CompleteStep` fields,
      `StepView`, `EPILOGUE_STEP_KEY`, readers `step`/`steps`/`branch`, `InputReader.for_gate`,
      `InputReader.deposited_answer` (ruling R-1, contracts §1.4 — `TRANSITIONAL(FUN-21)`),
      `WorkflowView.graph_digest` (contracts §1); the document store maps each onto the `ScopeStore`
      method the walk calls today (contracts §2), behaviour unchanged; `deposited_answer` delegates
      to `gate_requests.recorded_answer(self.scope_store, …)`.
      *Call path:* W7/W8, same wave.
- [ ] **W6** The same on SQLite
      *Depends on:* W1.
      *Files:* `PLUGIN/_workflow_sql.py`, `PLUGIN/_readers.py`, `PLUGIN_TESTS/test_workflow_sql.py`.
      *Do:* contracts §2; every statement carries `fence_sql`; `RecordBranch` same-target replay
      is a no-op, different-target raises; `deposited_answer` returns `None` (R-1), with a test:
      an imported legacy gate with a bare payload resumes from its `#legacy` candidate.
      *Call path:* W7/W8, same wave.
- [ ] **W7** `FrontierWalk` speaks only the port
      *Depends on:* W5, W6.
      *Files:* `src/functualize/_engine/frontier.py`.
      *Do:* drop the `store: ScopeStore` parameter and both `hold` calls (and W4's TRANSITIONAL
      marker); `start` → `StartWalk`; `complete` → `CompleteStep` with the record fields;
      `_record_timed_out` → `RecordStep`; `_resolve_branch` → reader `branch` + `RecordBranch`;
      `_step_that_went_silent`, `is_blocked`, `completed_steps`, `should_replay_skip`,
      `_request_id_for` → readers (`workflow`, `step`, `steps`, `for_gate`); `gate_payload`'s
      `TRANSITIONAL(FUN-21)` fallback → `self._runtime_store.inputs.deposited_answer(...)` (R-1),
      precedence unchanged; drop the `recorded_answer` import.
      *Witness:* `tests/workflow/test_gate_resolution_model.py::test_legacy_gate_record_resumes_with_zero_candidates`
      green, unchanged.
- [ ] **W8** The walker, the runner and their callers
      *Depends on:* W7.
      *Files:* `src/functualize/_engine/workflow_walker.py`, `src/functualize/_engine/workflow_runner.py`,
      `src/functualize/_engine/workflow_orchestrator.py`, `src/functualize/_engine/dependency_runner.py`.
      Four files, against the usual 1–3, because the constructor change is one signature and does
      not split without leaving a caller that cannot compile.
      *Do:* graph digest via `WorkflowView.graph_digest` + `StartWalk`; status writes via
      `MoveScope` / `CompleteStep`; failure routes and notify markers via `branch` + `RecordBranch`;
      the failed-step record via `RecordStep`; epilogue via `RecordStep(EPILOGUE_STEP_KEY)` and
      reader `step`; the orchestrator stops passing `_scope_store()`; `DependencyRunner` reads
      `steps`.
- [ ] **W9** Tests that built a walk by hand, and the architecture test
      *Depends on:* W8.
      *Files:* `tests/spec/test_the_walk_writes_only_through_the_port.py` (new), a shared fixture
      in `tests/conftest.py` or `tests/workflow/conftest.py`, and the 20 files that construct
      `FrontierWalk`/`WorkflowWalker`/`WorkflowRunner` — the hit set of
      `rg -l "FrontierWalk\(|WorkflowWalker\(|WorkflowRunner\(" tests plugins` at `0ede988b`:
      `tests/engine/test_gate_service.py`, `tests/engine/test_timeout_is_lease_expiry.py`,
      `tests/engine/test_walk_claims_through_the_port.py`, `tests/integration/test_crash_and_resume.py`,
      `tests/integration/test_notify_exactly_once.py`, `tests/test_d7_graph_probes.py`,
      `tests/test_walk_coalescing.py`, `tests/test_workflow_as_job.py`, `tests/test_workflow_walker.py`,
      `tests/workflow/test_agent_step_refusals.py`, `tests/workflow/test_cancel_wins_the_race.py`,
      `tests/workflow/test_decision_policy_digest.py`, `tests/workflow/test_failure_routing.py`,
      `tests/workflow/test_loops.py`, `tests/workflow/test_max_workflow_depth.py`,
      `tests/workflow/test_notify.py`, `tests/workflow/test_resumed_walk_says_running.py`,
      `tests/workflow/test_source_identity.py`, `tests/workflow/test_typed_step_outcomes.py`,
      `tests/workflow/test_watch_stream.py`. Mechanical: each builds the walk over a store from the
      fixture; no assertion changes except reading a record through the port.
      *Gate (W-AC-1, W-AC-4):* `rg -n "self\._store\." frontier.py workflow_walker.py
      workflow_runner.py` → nothing; the `ast` architecture test green; every listed test green on
      the document store; `tests/workflow` and `tests/engine` green.
      *Sabotage (ticks W5–W9):* (i) make `SqliteRuntimeStore.record_branch` a no-op → a replay test
      parametrised on SQLite takes a different branch than it paused on; (ii) delete the
      `StartWalk` issue in `FrontierWalk.start` → `test_resumed_walk_says_running` fails on both
      stores; (iii) re-add one `self._store.get_scope` → the architecture test fails.

## Wave 3 — the walk's state and events

- [ ] **W10** Reader `state`
      *Files:* `src/functualize/_types/persistence.py`, `src/functualize/_primitives/document_store.py`,
      `PLUGIN/_readers.py`.
      *Call path:* W11, same wave (closes together).
- [ ] **W11** `State` inside a walk writes through the port
      *Depends on:* W10.
      *Files:* `src/functualize/_engine/capabilities/state.py`,
      `src/functualize/_engine/capabilities/workflow_scope.py`, `src/functualize/testing/builder.py`.
      *Do:* `WorkflowScope.generation`; the walk passes its generation into the step's scope; a
      `State` built for a scope with a generation buffers `StateBatch` and reads `state()`; one with
      no generation keeps `ScopeBackedStateStore` (spec §3).
      *Gate (B-4):* on SQLite, a step's `state.set("rows", 500)` lands in `scope_state` and a resumed
      walk in another process reads 500; on documents, unchanged.
      *Sabotage (ticks W10, W11):* route the walk-scoped `State` back to `ScopeBackedStateStore` →
      the `scope_state` row assertion fails.
- [ ] **W12** The walk log through `EventWriter`
      *Files:* `src/functualize/_events/walk_log.py`, `src/functualize/_app/boot.py`.
      *Do:* inject the selected store (as `store_for` is injected today) and append in a port
      transaction.
      *Call path:* boot wires the subscriber; the walk's events reach it on the bus.
      *Gate (B-5):* on SQLite a walk's events are rows of `scope_events` and no `documents['scopes']`
      key is created; on documents, unchanged.
      *Sabotage:* restore `ScopeStore.append_event` → the "no `documents['scopes']`" assertion fails.

## Wave 4 — the suite, the stale walker, and the xfail flip

- [ ] **W13** BASELINE for the new commands
      *Files:* `src/functualize/testing/conformance/baseline.py`, `tests/conformance/test_baseline.py`.
      *Gate (S-8, W-AC-4):* a check per new writer and reader (start/renew/release/record_step/
      record_branch/move round trips, `state`, `steps`, `branch`, epilogue key, and
      `deposited_answer` is `None` for a candidate-answered gate — R-1) green on **both**
      stores and over `BatchOnlySqliteDriver` in Tier A.
      *Call path:* the shipped test library (as in the first feature).
      *Sabotage:* a store whose `release` keeps the owner → the release check fails.
- [ ] **W14** A stale walker lands nothing
      *Files:* `tests/integration/test_stale_walk_lands_nothing.py` (new).
      *Gate (W-AC-3):* two OS processes on SQLite; B force-claims while A is mid-walk; A's renew,
      release, `RecordStep`, `MoveScope` and `StateBatch` each land nothing; B's values survive.
      *Sabotage:* remove `fence_sql` from SQLite `move` → the test fails.
- [ ] **W15** The durability test passes and is no longer an xfail
      *Depends on:* W9, W11, W12.
      *Files:* `tests/integration/test_substrate_durability.py`.
      *Do:* remove the module `pytestmark` strict xfail and its `TRANSITIONAL(workflow-persistence-atomic)`
      comment; rewrite `test_the_substrate_is_where_the_records_actually_are` and
      `test_the_gate_payload_survives_the_crossing` to read `workflow_scopes`, `workflow_steps`,
      `scope_state` and `input_requests`/`input_candidates` with `sqlite3`, never
      `SQLiteSubstrate.read`.
      *Gate (W-AC-2):* `uv run pytest tests/integration/test_substrate_durability.py --run-slow -q`
      all green with no xfail; `rg -n "SQLiteSubstrate|xfail|TRANSITIONAL" tests/integration/test_substrate_durability.py`
      → nothing.
      *Sabotage:* revert W4's `release()` to the legacy call → `test_the_second_worker_resumes_what_the_first_blocked`
      fails (`SUPERSEDED`).

## Wave 5 — operator surfaces (needs D-W1; shown for D-W1 = a)

- [ ] **W16** Workflow control reads and cancels through the port
      *Files:* `src/functualize/app/_workflow_control.py`, `src/functualize/app/_workflow_view.py`.
      *Do:* scope reads via `workflows.workflow` / `resumable` / `steps`; cancel via `CancelWorkflow`;
      reclaim via `ClaimWorkflow(force=True)` + `ReleaseLease`.
- [ ] **W17** The CLI and its flags
      *Files:* `src/functualize/_cli/builtins.py` (the workflow verbs only), `src/functualize/app/adapters/workflow_flags.py`.
      *Note:* `_cli/` may import only public API, so it reads through a public app method that
      wraps the port — add it to `functualize.app` if absent, and record it in `contracts.md`.
- [ ] **W18** The MCP workflow tools
      *Files:* `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py` and its tests.
      *Gate (W16–W18):* on SQLite, a walk parked at a gate is listed, shown, cancelled and reclaimed
      by `func builtin workflow …` and the MCP tools; on documents, unchanged.
      *Call path:* the CLI verb / MCP tool itself. *Sabotage:* restore one `ScopeStore(app.substrate)`
      read → the SQLite listing test sees nothing.
      If D-W1 = b, these three become: refuse the verb on a non-document store with a named error
      and a test; if c, they are dropped and the CHANGELOG states the limitation.

## Wave 6 — documentation

- [ ] **W19** Record the walk's write path
      *Files:* `CHANGELOG.md`, `contributor/reference/runtime-persistence-data-model.md` (§4 tense:
      the walk's transitions are landed), `contributor/architecture/codemaps/data-flow.md` (the walk's
      writes), `src/functualize/_primitives/document_store.py` (marker comment only).
      *Gate:* the CHANGELOG states that a parked SQLite workflow now resumes in another process, and
      the schema revision `0002`.

## Wave 7 — pre-merge (not implementation)

- [ ] **W20** Clear this feature for the merge
      *Do:* migrate the durable half (the new commands' rationale) to `contributor/reference/` or an
      ADR; then, as the deletion-only **last** commit, `git rm -r .spec/features/workflow-persistence-atomic`.
      *Gate:* `spec-artifacts-cleared` green after the two-push sequence
      (`.claude/rules/spec-workflow.md` → *Version control lifecycle*); PR title and body carry no
      tracker key; the tip tier (`HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q`) has no
      failure that is ours.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["W1"]},
    {"id": 1, "tasks": ["W2", "W3", "W4"]},
    {"id": 2, "tasks": ["W5", "W6", "W7", "W8", "W9"]},
    {"id": 3, "tasks": ["W10", "W11", "W12"]},
    {"id": 4, "tasks": ["W13", "W14", "W15"]},
    {"id": 5, "tasks": ["W16", "W17", "W18"]},
    {"id": 6, "tasks": ["W19"]},
    {"id": 7, "tasks": ["W20"]}
  ],
  "depends_on": {
    "W1": [],
    "W2": [], "W3": [], "W4": ["W2", "W3"],
    "W5": [], "W6": ["W1"], "W7": ["W4", "W5", "W6"], "W8": ["W7"], "W9": ["W8"],
    "W10": ["W5", "W6"], "W11": ["W10", "W9"], "W12": ["W9"],
    "W13": ["W9", "W11"], "W14": ["W9", "W11"], "W15": ["W9", "W11", "W12"],
    "W16": ["W15"], "W17": ["W16"], "W18": ["W16"],
    "W19": ["W15", "W18"],
    "W20": ["W19"]
  },
  "call_path": {
    "W1": "W1", "W2": "W4", "W3": "W4", "W4": "W4",
    "W5": "W7", "W6": "W7", "W7": "W7", "W8": "W8", "W9": null,
    "W10": "W11", "W11": "W11", "W12": "W12",
    "W13": null, "W14": null, "W15": null,
    "W16": "W16", "W17": "W17", "W18": "W18", "W19": null, "W20": null
  },
  "close_together": [["W2", "W3", "W4"], ["W5", "W6", "W7", "W8", "W9"], ["W10", "W11"]],
  "decision_gates": {"D-W1": ["W16", "W17", "W18"]}
}
```

Consistency check, run at authoring time against the block above (any non-empty list fails):

```python
import json, re
g = json.loads(re.search(r"```json\n(.*?)\n```", open("tasks.md").read().rpartition("## Task " + "Dependency Graph")[2], re.S).group(1))
wave = {t: w["id"] for w in g["waves"] for t in w["tasks"]}
assert sorted(wave, key=lambda t: int(t[1:])) == [f"W{i}" for i in range(1, 21)]
late_deps   = [(t, d) for t, ds in g["depends_on"].items() for d in ds if wave[d] > wave[t]]
split_pairs = [p for p in g["close_together"] if len({wave[t] for t in p}) > 1]
late_paths  = [(t, c) for t, c in g["call_path"].items() if c and wave[c] > wave[t]]
print(late_deps, split_pairs, late_paths)   # -> [] [] []
```
