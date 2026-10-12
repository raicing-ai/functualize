# Lease heartbeat tasks

The specification, plan, and task list are confirmed. All waves are serialized
because later work consumes the preceding symbol or edits the same engine test
file. `[F]` lists edit
scope, based on the symbol references and exact prose search recorded in
`plan.md`. Test commands below were run before authoring: the two existing
engine files passed 18 tests at baseline. New assertions must fail against the
old behavior before their corresponding production change closes a task.

## Wave 0

### [x] 1.1 Classify frontier renewal outcomes

[F] `src/functualize/_engine/frontier.py`,
`tests/engine/test_timeout_is_lease_expiry.py`.

Change `FrontierWalk.renew()` to distinguish renewed, superseded, transient
error, and no claim without changing the lease or generation algorithm. Direct
tests must show a stale generation is a takeover even after expiry, while an
ordinary persistence error does not falsely report takeover. Preserve
best-effort direct-call behavior. This method is already reached through the
walker's current node-boundary renewal until task 2.1 replaces that wire.

Acceptance: the focused timeout test file passes with new assertions that fail
against the old catch-all behavior; the existing node-boundary test still proves
the production wire reaches `FrontierWalk.renew()`. Run
`uv run pytest -q --no-header tests/engine/test_timeout_is_lease_expiry.py`
after the required ruff checks. Commit before sabotaging that wire, and record
the observed failing assertion and safe restoration.

Evidence: the focused file passed 15 tests. Removing the walker's renewal call
after committing produced `AssertionError: the walk renewed 0 times across two
nodes`; the call was restored and the checkout verified clean. The production
path is `WorkflowWalker.run()` → `_run_walk()` → `FrontierWalk.renew()` after
each node. In-step renewal remains for wave 1.

## Wave 1

### [x] 2.1 Renew during the entire claimed walk

[F] `src/functualize/_engine/lease_heartbeat.py`,
`src/functualize/_engine/workflow_walker.py`,
`tests/engine/test_timeout_is_lease_expiry.py`. The prior transitional marker
in `src/functualize/_engine/frontier.py` was removed as a one-line scope
addition because it became false when this task completed.

Build the per-walk stop-event helper and compose it in `WorkflowWalker.run()`
after a successful claim. Remove the boundary-only renewal. Keep the normal
interval at 60 seconds, expose a private test interval, stop/join before
release on all paths, and suppress a normal walk-end report after a stale
renewal. Do not preempt the node body. Rework the old by-hand heartbeat test
into a walker-observed long-step test. Cover completion, exception, and
timeout-shaped failure cleanup without a 300-second test wait.

Acceptance: `uv run pytest -q --no-header
tests/engine/test_timeout_is_lease_expiry.py` passes; the new test sees renewal
while the step is blocked and no heartbeat thread after each exit. Name the
production call path in the commit. Commit before sabotaging the helper start;
the in-step renewal test must fail, then restore the committed source.

Evidence: the focused file passed 19 tests; the mapped step tier passed 1,957
tests with 117 skipped, and the engine wave tier passed 143 tests. Ruff check,
ruff format check, mypy on 389 source files, and all seven import contracts
passed. The production path is `WorkflowWalker.run()` → `LeaseHeartbeat` →
`FrontierWalk.renew()` → `ScopeStore.renew_scope()` while `run_step` is blocked.
After committing the implementation, stopping the helper before its first wait
made the in-step test fail with `the walk did not renew during its live step`;
restoring the committed source left a clean tree and the test passed again.

## Wave 2

### [ ] 3.1 Prove live-step exclusion with two runners

[F] `tests/engine/test_walk_claims_through_the_port.py`,
`tests/engine/test_timeout_is_lease_expiry.py`.

Exercise two actual walkers against one substrate while the first step is
blocked. After the compressed initial lease period, the second ordinary
walker must return `HELD` without executing its step; the first then completes
once. Also retain forced takeover behavior: the first runner is fenced and
reports `SUPERSEDED`. Use event barriers and bounded waits so the test is
deterministic and leaves no test thread active.

Acceptance: `uv run pytest -q --no-header
tests/engine/test_timeout_is_lease_expiry.py
tests/engine/test_walk_claims_through_the_port.py` passes. The test must fail
if the walker no longer starts its heartbeat, as shown by the task 2.1
sabotage. No production change is expected in this wave.

## Wave 3

### [ ] 4.1 Align lease documentation with runtime behavior

[F] `src/functualize/_primitives/lease.py`,
`src/functualize/_engine/frontier.py`, `docs/cli/workflow.md`.

Describe in-step renewal, the 60-second interval, and the distinction between
stale generation and transient renewal failure. Correct the claim that a
still-running slow step necessarily looks abandoned. Preserve the warning
that expiry alone does not prove death or stop old work. The prose scan
`rg -n -i 'heartbeat|long step|step timeout|stops renewing|renew.*nodes'
src/functualize/_engine/frontier.py src/functualize/_primitives/lease.py
docs/cli/workflow.md` returned 7 hits across these three files, including
`lease.py`'s constant comment.

Acceptance: the edited docstrings and CLI page state the same lease semantics
as the tests, and `uv run ruff check src/ tests/ plugins/ examples/` plus
`uv run ruff format --check src/ tests/ plugins/ examples/` pass. No change to
`DEFAULT_LEASE_SECONDS` or claim/fence code.

## Wave 4

### [ ] 5.1 Validate the implemented feature

[F] `.spec/features/lease-heartbeat/tasks.md`, `.spec/STATUS.md` (durable
decision only). This is a checkpoint wave; no new production behavior.

Run `uv run ruff check src/ tests/ plugins/ examples/`,
`uv run ruff format --check src/ tests/ plugins/ examples/`,
`uv run mypy src/`, `uv run lint-imports`, the step-tier mapper, and the
engine wave tier. No pytest command may exceed 600 seconds; CI supplies the
full tip tier. Record the production reachability and sabotage result, the
exact command results, and dead-code delta over the branch range. Update
`.spec/STATUS.md` with durable lease behavior before the feature directory is
cleared later in the branch lifecycle.

Acceptance: all local checks pass, both-runner behavior and cleanup are covered,
and no required gate has been waived. The phase can then move to independent
review; clearing feature artifacts remains the deletion-only last commit after
feature validation.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["5.1"] }
  ]
}
```
