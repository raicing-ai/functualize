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
The heartbeat also remains active through end reporting and notifications,
until the claimed run is ready to release its lease.
After committing the implementation, stopping the helper before its first wait
made the in-step test fail with `the walk did not renew during its live step`;
restoring the committed source left a clean tree and the test passed again.

## Wave 2

### [x] 3.1 Prove live-step exclusion with two runners

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

Evidence: two `WorkflowWalker` instances use distinct `ScopeStore` objects
over one substrate. The first blocks inside step `a`; after its original
compressed lease expires, the second returns `HELD` without running a step.
The first then completes `a` and `b` once, with no heartbeat thread left.
The existing forced-reclaim test in the same file still shows a taken first
walker returns `SUPERSEDED` and never runs `b`. The acceptance pair passed 25
tests. Ruff check and format check, mypy on 389 source files, and all seven
import contracts passed. The production path exercised is
`WorkflowWalker.run()` → `LeaseHeartbeat` → `FrontierWalk.renew()` →
`ScopeStore.renew_scope()` while another `WorkflowWalker.run()` attempts a
claim through its runtime port. No production code changed.
After the test commit, disabling `LeaseHeartbeat._run()` made the new test
fail with `the live walk never renewed`; restoring the committed source made
it pass again and left the checkout clean.

## Wave 3

### [x] 4.1 Align lease documentation with runtime behavior

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

Evidence: the current prose scan found four hits before editing (earlier waves
had already changed the engine prose) and six after editing. The constant
comment, frontier renewal and timeout docstrings, and CLI page now describe
in-step renewal every 60 seconds, the distinction between stale generation
and a transient storage failure, and why expiry neither proves death nor
interrupts old work. Only prose changed. Ruff check passed; ruff format check
reported 1,598 formatted files; mypy passed on 389 source files; all seven
import contracts passed; the two focused engine files passed 25 tests.

## Wave 4

### [x] 5.1 Validate the implemented feature

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

Evidence: `uv run ruff check src/ tests/ plugins/ examples/` passed;
`uv run ruff format --check src/ tests/ plugins/ examples/` reported 1,598
formatted files; `uv run mypy src/` passed on 389 files; `uv run lint-imports`
kept all seven contracts. The mapped step tier passed 2,082 tests with 119
skipped; `uv run pytest -n auto -q --no-header tests/engine/` passed 144.
Each pytest invocation completed within the 600-second cap. The production
path is `WorkflowWalker.run()` → `LeaseHeartbeat` → `FrontierWalk.renew()` →
`ScopeStore.renew_scope()` while a step is blocked; the second walk claims
through its runtime port and receives `HELD`. After the implementation commit,
disabling the heartbeat made the in-step test fail; after the two-runner test
commit, disabling renewal made that test fail with `the live walk never
renewed`. Both sabotages were restored before their passing reruns. The
dead-code delta against `81cc3e8` reports `NEW_DEAD: 0`, `TESTS_ONLY: 0`,
with three pre-existing neighbourhood findings in `frontier.py`. The durable
lease behavior is recorded in `.spec/STATUS.md`. No gate was waived. The
feature directory stays on the draft branch for independent review and is
cleared by a deletion-only last commit later.

## Wave 5

### [x] 6.1 Close the claim-to-first-renewal window found by verification

[F] `src/functualize/_engine/lease_heartbeat.py`,
`src/functualize/_engine/workflow_walker.py`,
`src/functualize/_engine/frontier.py` (prose), `src/functualize/_primitives/lease.py`
(prose), `docs/cli/workflow.md`, `.spec/features/lease-heartbeat/spec.md`,
`.spec/STATUS.md`, `tests/engine/test_walk_claims_through_the_port.py`,
`tests/engine/test_timeout_is_lease_expiry.py`.

Independent verification at `92db0db` reproduced a second ordinary walker
completing at generation 2 while the first walker's step was still blocked.
An instrumented rerun of that probe located the window: the claim's expiry is
computed before its durable write (measured at 0.256 s of the 0.3 s
compressed lease on the loaded host), the heartbeat then waited a full
interval before its first renewal, and that renewal queued for the scope lock
behind the walk's own writes and three writes by the claimant. The claim
lapsed before the first renewal landed.

Renew once on the walking thread when the heartbeat is entered, before any
step, and run nothing when that renewal reports a takeover. Keep the 60-second
interval, the claim algorithm, the fence and the lease value. Align the
remaining contradicting prose (`StepStatus.TIMED_OUT`) and replace the
hand-called renewal in `test_renewing_keeps_the_scope` with a walker-observed
one; make the blocked-step renewal test observe the store rather than wrapping
`renew`.

Acceptance: a deterministic test whose claim outlives its whole compressed
lease, with a heartbeat interval longer than the test, sees the second walker
`HELD` and the first complete once; it fails against `92db0db`. The focused
pair and the engine wave tier pass, with ruff, format, mypy and import
contracts. Commit before sabotaging the entry renewal.

Evidence: `test_a_slow_claim_does_not_leave_the_first_step_claimable` failed
against `92db0db` with the second walker `COMPLETED`, and passes after the
change. After committing, removing the entry renewal from
`LeaseHeartbeat.__enter__` made it fail with the same `COMPLETED is HELD`
assertion; `git checkout --` restored the committed source and left the tree
clean. `test_a_scope_taken_before_the_first_step_runs_nothing` also passes
without the early return, because the walk's first fenced write already stops
it before `a`; it pins the outcome, not the early return. The focused pair
passed 27 tests and `uv run pytest -q --no-header tests/engine/` passed 146.
Ruff check passed, format check reported 1,598 formatted files, mypy passed on
389 source files and all seven import contracts were kept. The dead-code delta
over `81cc3e8..c234984` reports `NEW_DEAD: 0`, `TESTS_ONLY: 0`, with the same
three pre-existing neighbourhood findings in `frontier.py`. The production
path is `WorkflowWalker.run()` → `LeaseHeartbeat.__enter__` →
`FrontierWalk.renew()` → `ScopeStore.renew_scope()` before the first step, then
the heartbeat thread every interval.

Residual, not closed by this task: the verification probe's seam patches
`DEFAULT_LEASE_SECONDS` after import, so `renew_scope` still grants its
import-time 300 seconds and the probe measures only the claim-to-first-renewal
window, which no trial in 100 reached after the change. A stricter variant
that also gives each renewal 0.3 seconds still lets a second walker in, rarely:
once in three trials and once in 222. Instrumented, the cause was a single
durable renewal write taking 0.418 seconds, longer than the whole compressed
lease, so the renewed lease landed already expired. At the production ratio a
renewal would have to stall for more than 240 seconds. Closing that without
timing needs a liveness signal in the claim itself, which this feature keeps
out of scope.

## Wave 6

### [x] 7.1 Report a renewal the SQLite predicate refused as superseded

[F] `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_transaction.py`,
`plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_workflow_sql.py`,
`plugins/substrates/functualize-substrate-sqlite/tests/test_workflow_sql.py`,
`tests/engine/test_the_walk_on_both_stores.py`,
`contributor/architecture/codemaps/data-flow.md`,
`src/functualize/_engine/frontier.py` (docstring wrap only).

After the merge with `master`, the walk renews through the runtime-store port.
On SQLite, `SqlWorkflowWriter.renew` checks the fence when it stages its
conditional `UPDATE`; a claim that commits between that check and the batch
leaves the update matching no row, and `BufferedTransaction.commit` discarded
the row counts. `FrontierWalk.renew()` then returned `RENEWED` while another
runner owned the scope, and the heartbeat waited a full interval before
noticing. Stage the renewal with a refusal that `commit` raises as
`StaleGenerationError` when the statement matched no row, so the classification
follows the stored outcome. Leave the fence, the claim algorithm and every
other writer's reporting unchanged. Align the codemap's lease line, which
still said renewal happens between nodes.

The feature artifacts are restored from before their clearing commit for this
task, because the clearing commit was followed by a source-changing merge;
they are cleared again by a deletion-only last commit.

Acceptance: a SQLite port test that commits a forced claim inside the open
renewal unit expects `StaleGenerationError`, and an engine test that forces the
same takeover inside `FrontierWalk.renew()` expects `SUPERSEDED`. Both fail at
`66bacfa`. The focused files, the engine tier and the SQLite plugin suite pass,
with ruff, format, mypy and import contracts. Commit before sabotaging the
refusal.

Evidence: at `66bacfa` the engine test failed with
`assert <RenewalOutcome.RENEWED: 'renewed'> is <RenewalOutcome.SUPERSEDED: 'superseded'>`
and the port test with `DID NOT RAISE StaleGenerationError`; both pass after
the change. After committing, removing the renewal's `refused=` argument made
both fail again with the same two messages; `git checkout --` restored the
committed source and left the tree clean. `uv run pytest -q --no-header
tests/engine/` passed 184; `uv run pytest
plugins/substrates/functualize-substrate-sqlite/tests -q` passed 185; the
step-tier mapper (`--base 66bacfa`) selected eleven root paths, which passed
182 at `-n auto`, plus the SQLite plugin suite above. Ruff check and format
check passed, mypy passed on 394 source files and on the plugin's 16, and all
seven import contracts were kept. The dead-code delta over `66bacfa..HEAD`
reports `NEW_DEAD: 0`, `TESTS_ONLY: 0`, with three pre-existing
neighbourhood findings in `frontier.py`. Production path:
`WorkflowWalker.run()` → `LeaseHeartbeat` → `FrontierWalk.renew()` →
`SqlWorkflowWriter.renew()` → `BufferedTransaction.commit()`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["7.1"] }
  ]
}
```
