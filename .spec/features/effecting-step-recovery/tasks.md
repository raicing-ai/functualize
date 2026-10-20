# effecting-step-recovery — tasks

Execute against the six-file anchor: `AGENTS.md`, `.spec/CONSTITUTION.md`,
`.spec/ARCHITECTURE.md`, `.spec/TESTING.md`, `.spec/STATE.md` (if absent, no work
in flight), and this `tasks.md`. **Wave order is binding.**
Every gate below is a command. A task is `[x]` only when its gate is green **and**
its reachability line has been proven by breaking the call and watching a test go
red. Commit before sabotaging. Each task's checks are run from the repository root:
`uv run ruff check`, `uv run ruff format --check`, `uv run mypy src/`,
`uv run lint-imports`, then the Step tier for the diff
(`uv run pytest -n auto -q --no-header $(.agents/skills/test-tiers/scripts/tests-for-diff)`).
Run `uv sync --frozen --all-extras --all-packages` first.

## Wave 1 — vocabulary and declaration (foundation; parallel-safe)

### T1 [x] — Port vocabulary: attempt fields and `supersedes`
- **Inputs:** an effecting attempt is durably recorded before its job runs with
  `status=attempting`, `effecting=true`, attempt number (starting at 1), and start
  time. The recovery question carries step, attempt, loop iteration, and start
  time; a consumed answer for one doubt must never answer a later doubt. Port
  fields default so existing construction sites remain valid.
- **Files:** `src/functualize/_types/persistence.py`,
  `src/functualize/_engine/recording/input_recorder.py`,
  `tests/conformance/test_baseline.py` (default-value assertions only).
- **Change:** `CompleteStep`, `RecordStep` and `StepView` gain `attempt: int = 0` and
  `started_at: datetime | None = None`. `SuspendAtGate` gains
  `supersedes: str | None = None`. `InputRecorder.opened(...)` gains
  `supersedes=None` and passes it through.
- **Invariants:** every existing construction site compiles unchanged (all defaults);
  `_types` imports nothing internal.
- **Gate:** `uv run mypy src/` clean; `uv run lint-imports` = 7 kept / 0 broken;
  `rg -n "attempt: int = 0" src/functualize/_types/persistence.py` = 3 lines.
- **Reachability:** none yet. These are vocabulary. Marked `[x]` on the gate alone,
  with `# TRANSITIONAL(effecting-step-recovery/T4,T5,T7)` on each new field until
  its writers land.

### T2 [x] — Declaration: recovery gates, `InDoubt`, shape, collision refusal
- **Inputs:** `effecting=True` implies one declared recovery gate named
  `<step>-in-doubt`; it opens only when a walk finds the step in doubt. The gate
  must resolve through `WorkflowDeclaration.node()` because the answer path
  resolves its model from the declaration. Canonicalisation maps
  `refund_in_doubt` to `refund-in-doubt`; `.` separates groups. The answer schema
  requires `outcome` (`ran` or `did_not_run`), permits optional `value`, and
  forbids extra fields. Graph shape and digest add the effecting flag and gate
  only for effecting steps; pure graphs remain byte-identical. A previously
  parked effecting scope with the old digest gets the existing graph-changed
  refusal. Name collisions are refused at declaration time.
- **Files:** `src/functualize/_types/workflow.py`,
  `src/functualize/workflow/_validation.py`,
  `tests/test_workflow_declaration.py`, `tests/workflow/test_source_identity.py`.
- **Change:** `recovery_gate_name(step) -> f"{step}-in-doubt"` (after
  canonicalisation). `InDoubt` (pydantic: `outcome: Literal["ran", "did_not_run"]`,
  no default; `value: Any = None`; `extra="forbid"`).
  `WorkflowDeclaration.recovery_gate(step)` / `recovered_step(gate)`. `node()` and
  `gates()` include recovery gates. `.nodes` is unchanged. `shape()` projects
  `"effecting": true` on an effecting step and a `{"gate", "model": "InDoubt", "recovers"}`
  entry, **only when declared**. The decorator refuses a node whose name equals a
  derived recovery-gate name (`ValueError`, beside "Duplicate workflow node name").
- **Invariants:** a declaration with no effecting step projects byte-identically
  (same `to_dict()`, same `graph_digest`); `.nodes` order and entry are unchanged.
- **Gate (AC-10, AC-11):** new tests in the two files: the digest of a pure graph
  equals a value pinned from `d1c7e40a`; the digest of a one-effecting-step graph
  differs, and its `to_dict()` diff is exactly the two additions; declaring
  `Step("refund", effecting=True)` with `Gate("refund-in-doubt", …)` raises
  `ValueError`; `declaration.node("refund_in_doubt")` resolves.
- **Reachability:** `graph_digest` (`_engine/workflow_validation.py:211`) →
  `declaration.shape()`, called from `WorkflowWalker._check_the_graph_has_not_changed`.
  Proof: remove the `recovers` entry and the AC-10 test goes red.

### T3 [x] — Boot refusal: `effecting=True` on a workflow job (E×W×W)
- **Inputs:** a step whose job is itself a workflow cannot be effecting: its
  child steps declare their own flags. The registry reveals nested workflows
  only at boot, after declaration; refuse this composition at boot validation.
- **Files:** `src/functualize/_engine/workflow_validation.py`,
  `tests/workflow/test_launch_validation.py`.
- **Change:** `validate_workflow_declarations` raises `WorkflowDeclarationError` when
  a `Step(effecting=True)` resolves to a registered function that carries
  `__functualize_workflow__`.
- **Gate (AC-12):** new test: an app whose workflow has `Step(child_workflow, effecting=True)`
  fails boot with `WorkflowDeclarationError` naming the step; the same step with
  `effecting=False` boots.
- **Reachability:** boot → `validate_workflow_declarations`
  (`_engine/workflow_validation.py:113`). Proof: delete the new branch and the test
  goes red.

### T4 [x] — Discovery cache version
- **Inputs:** effecting steps add a flag and recovery-gate entry to the cached
  workflow shape. The cache schema version therefore advances from 21 to 22.
- **Files:** `src/functualize/_primitives/cache_format.py`, plus any test pinning
  `CACHE_VERSION` (the hit set of
  `rg -ln "CACHE_VERSION|\b21\b.*cache" tests src`, re-run at execution time).
- **Gate:** `rg -n "^CACHE_VERSION = 22" src/functualize/_primitives/cache_format.py`
  returns one line; the cache tests in the hit set pass.
- **Reachability:** `_discovery/cached_provider.py:329` compares it on every warm
  boot. Proof: revert it to 21 and a warm-boot test that reads a stale `workflow`
  entry goes red.

## Wave 2 — the two backends, then agreement

### T5 [x] — Document backend: attempt fields and `supersedes`
- **Depends on:** T1.
- **Files:** `src/functualize/_primitives/document_store.py`,
  `src/functualize/_primitives/gate_requests.py`,
  `tests/primitives/test_document_runtime_store.py`, `tests/primitives/test_gate_requests.py`
  (the hit set of `rg -ln "open_request|_step_view|DocumentRuntimeStore" tests/primitives`).
- **Change:** `_step_record` writes `attempt` / `started_at` keys **only when set**;
  `_step_view` reads them. `open_request(…, supersedes=id)` moves a **consumed**
  record with that id onto the gate's `superseded` history (reason `superseded`)
  and opens a fresh request. Without `supersedes`, today's reuse is unchanged.
- **Invariants:** a pure step's record is byte-identical to today's (AC-7).
- **Gate:** new tests: the record round-trips `attempt` and `started_at`; a pure
  record has neither key; `supersedes` yields a new open request and keeps the old
  one in history.
- **Reachability:** `DocumentRuntimeStore._suspend` (`document_store.py:1096`) →
  `gate_requests.open_request`. Proof: ignore `supersedes` there and the test goes
  red.

### T6 [x] — SQLite backend: migration 0003, writer, reader
- **Depends on:** T1.
- **Files:** `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_schema/0003_step_attempt.sql` (new),
  `…/_workflow_sql.py`, `…/_readers.py`, `…/_migrations.py` (`SHIPPED_MIGRATIONS`
  appends `_load(3, "step_attempt")`, and the revision's on-disk object map gains
  the column), `plugins/substrates/functualize-substrate-sqlite/tests/test_migrations.py`,
  `…/tests/test_workflow_sql.py`; and the three files that pin the newest
  schema version 2, so revision 3 turns them red (the hit set of
  `rg -n "max\(version\).*\(2,\)|latest_version = 2|VALUES \(3, 'future'" plugins tests`):
  `…/tests/test_plugin_selection.py`, `…/tests/test_runtime_store.py`,
  `tests/conformance/sqlite_hooks.py` (`latest_version`, and the "ahead"
  damage that must stay ahead of the shipped set).
- **Change:** `ALTER TABLE workflow_steps ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0);`.
  `_stage_step` writes `attempt` and `started_at` (the column exists since `0001`).
  `_step` reads both. `suspend` with `supersedes` verifies that the named request is
  consumed (a new row is already the latest, `_readers.py:264`).
- **Gate:** migration test 0002→0003 on a populated database; round-trip test for
  both fields.
- **Reachability:** `SqlWorkflowWriter._stage_step` from `complete_step` /
  `record_step`. Proof: drop `attempt` from the INSERT and the round-trip goes red.

### T7 [x] — Conformance: both backends agree
- **Depends on:** T5, T6.
- **Files:** `src/functualize/testing/conformance/baseline.py`,
  `tests/conformance/test_baseline.py`; and `src/functualize/_types/persistence.py`
  for its seven `TRANSITIONAL(effecting-step-recovery/…)` comments only (the hit
  set of `rg -n "TRANSITIONAL\(effecting-step-recovery" src plugins`): once both
  backends persist and read the fields they say "later", which is no longer the
  code's behaviour; they are re-pointed at the walk tasks that still owe a writer.
- **Change:** cases for (a) an `attempt` / `started_at` round trip through `RecordStep`
  and `CompleteStep`, (b) a pure step with neither, (c) `SuspendAtGate(supersedes=…)`
  after a consumed request: the reader's request for the gate is the new open one.
- **Gate:** `uv run pytest tests/conformance -q` green for the document backend and
  the SQLite hooks (`tests/conformance/sqlite_hooks.py`).
- **Reachability:** the conformance suite *is* the consumer. Proof: revert T5's
  supersede branch and case (c) goes red on the document backend only.

## Wave 3 — engine plumbing

### T8 [x] — Frontier statuses and pass-through; `GateAsk`
- **Depends on:** T1, T5, T6.
- **Files:** `src/functualize/_engine/frontier.py`,
  `src/functualize/_engine/gate_service.py`, `tests/workflow/test_gate_resolution_model.py`.
- **Change:** `StepStatus.ATTEMPTING = "attempting"`, `IN_DOUBT = "in_doubt"`,
  `BLOCKED = "blocked"`, none added to `TERMINAL_SUCCESS`. `FrontierWalk.record` /
  `complete` accept `attempt`, `started_at`, `effecting` (keyword-only,
  pass-through). `open_request` accepts `supersedes`. The `is_effecting` docstring is
  corrected to say an in-flight effecting step is never re-run without a
  decision and is exactly-once once that decision is made; a raise is the
  job's own account. In `gate_service.py`, a frozen
  `GateAsk(position=None, prompt=None, ladder=_DEFAULT, supersedes=None)` is added,
  and `service(..., ask=GateAsk())` uses it in `_open` and in place of
  `_gate_strategy_list` when `ladder` is given.
- **Invariants:** `GateAsk()` reproduces today exactly (the existing gate tests are
  unchanged and green). **The `FrontierWalk` class span grows by ≤ 15 lines**
  (measure the class span in `frontier.py` against the pre-change span of 578
  lines, counting the class declaration through its last method).
- **Gate:** existing `tests/workflow/test_gate_*` green, unchanged; new test:
  `GateAsk(ladder=["prompt"])` never consults the `resolve` rung (a registry spy
  records the strategies asked); `TERMINAL_SUCCESS` is still `{"success"}`.
- **Reachability:** `WorkflowWalker._service_gate` → `GateService.service`. Proof:
  ignore `ask.ladder` and the new test goes red.

## Wave 4 — the behaviour

### T9 [x] — `EffectRecovery` and the walker's delegation
- **Depends on:** T2, T8.
- **Files:** `src/functualize/_engine/effect_recovery.py` (new),
  `src/functualize/_engine/workflow_walker.py`,
  `src/functualize/_engine/frontier.py` (atomic nonreusable `ran` completion),
  `src/functualize/_engine/executor.py` (refuse a missing recovery value for `FromJob`),
  `tests/workflow/test_effecting_recovery.py` (new).
- **Change:** `EffectRecovery.begin` writes `RecordStep(status=attempting, attempt,
  started_at, effecting=True, completed_at=None)`. `EffectRecovery.verdict`, on an
  `attempting` / `in_doubt` record, writes `in_doubt` (keeping attempt and
  `started_at`), then asks `declaration.recovery_gate(step)` through
  `GateService.service(ask=GateAsk(position=step, prompt={step, attempt, iteration, started_at},
  ladder=["prompt"] if prompt_gates else None, supersedes=<consumed request whose prompt ≠ this doubt>))`,
  and returns `Ran(value, reusable)` / `DidNotRun` / the blocked report.
  `_service_step` delegates for effecting or doubting steps. `StepBlocked` on an
  effecting step records `blocked`: this is an ending, not doubt, and resume
  re-runs the step. `_NodeRun` gains `reusable: bool | None`
  so that `ran` without a value completes as not reusable. `attempt` flows through
  `_advance` → `complete`.
- **Recovery behavior:** an `attempting` record means control reached the
  effecting job; on resume, never call that job before a decision. Record the
  step `in_doubt`, stop the scope with status `blocked`, `blocked_on` equal to
  `<step>-in-doubt`, and a reason beginning `in_doubt:` that names the step,
  attempt, and start time. `ran` records success and continues without calling
  the job; its optional `value` is the return value, and without one a downstream
  `FromJob` / `FromStep` must fail rather than use an invented value.
  `did_not_run` explicitly permits the job to run as attempt *n+1*. An answer
  for one loop pass or attempt never resolves a later doubt: the new question
  identifies step, attempt, iteration, and start time, and supersedes a stale
  consumed request. With prompt gates off, leave the gate pending; with them
  on, allow only an explicit prompt answer. Config, AI, decision, default,
  cancellation, and timeout never decide it. A return, raise, cancellation,
  `BLOCKED` ending, routed failure, or fresh fingerprint skip must replace the
  attempt record. Reclaim leaves `attempting` intact until the resumed walk
  reaches the step; it must not turn into `timed_out`.
- **Invariants:** a pure step's path is byte-for-byte today's; **the `WorkflowWalker`
  class span grows by ≤ 15 lines**; `effect_recovery.py` imports only `_types` and
  `_engine` siblings.
- **Gate (in-process, faults injected by raising `BaseException` subclasses from
  `run_step` to stand in for a crash):** AC-2, AC-3, AC-4, AC-5 (one test per exit:
  return, raise, cancel, `BLOCKED`, routed failure, fingerprint skip), AC-6 (reclaim
  then resume), AC-9 (prompt-gates off → blocks; a config value for `outcome` is not
  used; no AI or decision rung is asked), AC-13 (loop pass, and a second attempt,
  on both backends via the conformance hooks), AC-16 (a subscribed watcher receives
  `step.end` with the blocked outcome).
- **Reachability:** `WorkflowRunner.prelude` → `WorkflowWalker.run` →
  `_service_step` → `EffectRecovery.begin`. Proof: remove the `begin` call, and
  AC-1's in-process twin (a crash after the effect) re-runs the job.

### T10 [ ] — Answer path: a recovery gate stands at its step
- **Depends on:** T2.
- **Files:** `src/functualize/app/_workflow_answer.py`,
  `tests/workflow/test_gate_resume_surfaces.py`.
- **Change:** `_downstream_of(recovery gate)` returns `{step} ∪ _downstream_of(step)`
  via `declaration.recovered_step()`.
- **Gate (AC-8):** the recovery gate is answered through `answer_gate`,
  `func builtin workflow answer … --input`, `--wf-resume --wf-input`, and the MCP
  `_answer_gate` tool; an answer with `outcome: "maybe"` is refused and the gate
  stays open; `--reopen` after the walk passed the step is refused.
- **Reachability:** `answer_gate` → `_walk_has_passed` → `_downstream_of`. Proof:
  revert, and the `--reopen` test goes red.

## Wave 5 — the real crash, and the words

### T11 [ ] — `kill -9` into the window
- **Depends on:** T9, T10.
- **Files:** `tests/integration/test_crash_and_resume.py`.
- **Change:** a hang point **after the effect and before the job returns**, plus a
  hang point inside a `Deps` upstream and one inside an `inv()` child. The existing
  after-record tests are kept (they still pin the replay).
- **Gate (AC-1, AC-3, AC-4, AC-7, AC-14):** `uv run pytest --run-slow tests/integration/test_crash_and_resume.py -q`
  green. Marker counts: effecting = 1 and then `in_doubt`; `ran` = 1; `did_not_run` = 2;
  pure = 2; `Deps` / `inv()` kill → `in_doubt`.
- **Reachability:** the subprocess runs the production `WorkflowWalker` with
  `DocumentRuntimeStore` (as today's test does). Proof: comment out `begin` in T9's
  call site and AC-1 goes red with a marker count of 2.

### T12 [ ] — Docstrings, guide, CLI reference, changelog
- **Depends on:** T9.
- **Files:** `src/functualize/_types/workflow.py` (the `Step.effecting` docstring only),
  `docs/guides/workflows.md`, `docs/cli/workflow.md`, `CHANGELOG.md`.
- **Change:** state that an in-flight effecting step is never re-run without a
  decision and is exactly-once once that decision is made; a raise is the
  job's own account even if its effect already happened. Document the recovery
  gate (`<step>-in-doubt`) and its required `outcome` (`ran` or `did_not_run`),
  optional `value`, and how to answer it through the existing CLI/API surfaces.
  Document the known notification limitation: `Notify(on="blocked")` is keyed
  per declaration and scope, so an earlier blocked stop may prevent a later
  in-doubt stop in the same scope from sending another notification; status
  and `blocked_reason` still expose the stop. Add a changelog entry stating
  the one-time digest refusal for workflows with an effecting step.
- **Gate (AC-15):** `rg -n "exactly once|exactly-once|at-most-once|at most once" src/functualize/_types/workflow.py src/functualize/_engine/frontier.py docs/guides/workflows.md`
  returns only lines carrying "never re-run without a decision"; the docs-example
  parity tests for the guide pass.
- **Reachability:** documentation. Its gate is the `rg` check above.

## Task Dependency Graph

```json
{
  "feature": "effecting-step-recovery",
  "waves": [
    {"id": "W1", "tasks": ["T1", "T2", "T3", "T4"], "depends_on": []},
    {"id": "W2", "tasks": ["T5", "T6", "T7"], "depends_on": ["W1"], "order": {"T7": ["T5", "T6"]}},
    {"id": "W3", "tasks": ["T8"], "depends_on": ["W2"]},
    {"id": "W4", "tasks": ["T9", "T10"], "depends_on": ["W3"]},
    {"id": "W5", "tasks": ["T11", "T12"], "depends_on": ["W4"]}
  ]
}
```
