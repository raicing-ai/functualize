# hermetic-router-repair — Tasks

Authored 2026-10-03 against `2b987a3` (`origin/master`, which carries the
merged delivery `e8fac3e`). Four tasks in three waves. Every `now:` below
was produced by running its command on this branch at authoring time.

**Authority.** This package exists to repair the two blocking findings of
the head-specific review of the merged delivery (ReviewReport against
`3c51a862`, 2026-10-02) plus the PR-72 body inaccuracy it flagged. It is
deliberately the only artifact: the behaviour under repair, its contracts
(C-3, B-6) and its acceptance criteria are those of the merged
`hermetic-router` feature, whose durable half lives in `.spec/STATUS.md`,
ADR-030 and `docs/guides/workflows.md`, and whose branch artifacts are
recoverable via PR #72's ref. This file restates what the repair changes;
nothing else is re-specified.

**One disclosed amendment.** The uncovered-proposal path (finding 1) gets
its own recorded verdict value, `uncovered_proposal`. C-3's verdict
vocabulary was four values; recording this path under any of them would
misreport it (`no_distribution` lies — there is one; `provider_failed`
implies a `failure` block there is none). The widening is additive: no
reader keys on the value set, and no durable doc enumerates the values —
`docs/guides/workflows.md` names the `verdict` key, not its values.

## Standing rules

- Worktree `/home/ubuntu/orca/workspaces/functualize/sdd-hermetic-router`,
  branch `sdd/hermetic-router-repair`, cut from `2b987a3`.
- Checks from the repository root, output redirected: `ruff check --fix`,
  `ruff format`, `mypy src/`, `lint-imports`, and each task's own pytest
  command. At most two pytest invocations per verification.
- One commit per task, conventional subject, single scope token, ≤72
  chars, lowercase, imperative. No tracker key, issue URL, agent, model or
  run identity in any commit message.
- Sabotage order is binding: **commit first**, then break, then
  `git checkout -- <file>`.
- Wave ordering is binding: never start wave N+1 while wave N has an
  unchecked task.

## Wave 0 — the repairs

### [x] R1 — an uncovered proposal records its evidence before it fails

*Files:* `src/functualize/_gate/decision_strategy.py`,
`tests/gate/test_decision_strategy.py`

Finding 1 (blocking): the path where a provider returns a distribution
that does not cover its own proposal raises without recording, so a
failed rung of exactly the kind the feature exists to audit can carry
`evidence=None` — against C-3 ("whenever the provider was called") and
B-6.

1. Write the regression first and watch it fail: through
   `GateRegistry.evaluate` with the file's existing `FakeProvider`
   returning `FakeProvider("returns", {"shipping": 0.9, "billing": 0.1})`
   over a decision whose options include `returns`, the rung is `failed`
   with `detail` containing `does not cover` — and, before the fix, its
   evaluation's `evidence` is `None`. After the fix the same rung carries
   evidence with `verdict == "uncovered_proposal"`, the reported
   `distribution`, `proposal == "returns"`, `probability is None` and
   `margin is None` (the rule never ran), and `failure is None`.
2. In `DecisionGateResolver.resolve`, on the `value not in distribution`
   path, record before raising — exactly as the `no_distribution` path
   directly above does: `record(latency_seconds, "uncovered_proposal", result=result)`
   then the unchanged `ValueError`. The message does not move.

Production call path: walk → `GateService.service` → `GateRegistry.evaluate`
→ `DecisionGateResolver.resolve` → `RungEvidence.record` → the rung's
`CandidateEvaluation(evidence=…)`.

Commands: `uv run pytest tests/gate/test_decision_strategy.py -q --no-header > /tmp/repair-r1.log 2>&1` → the new test fails before the fix
(reproducing the finding), passes after; the file's existing tests stay
green.

Gates:

```bash
rg -c "uncovered_proposal" src/functualize/_gate/decision_strategy.py
```
now: `0` · after: `1`

```bash
rg -c "test_an_uncovered_proposal_records_its_evidence" tests/gate/test_decision_strategy.py
```
now: `0` · after: `1`

Closed when: gates as `after:`, the failing-then-passing sequence is
recorded in the commit body, pytest passes, and the standing checks are
clean. Commit: `fix(gate): record the evidence of an uncovered proposal`.

### [x] R2 — the weak-proposal test reaches the ladder it depends on

*Files:* `examples/standalone/hermetic_router/tests/test_router.py`

Finding 2 (blocking): T10's named sabotage — reverting
`_engine/gate_service.py` to the Phase 1 ladder — did **not** fail the
AC-3 test `test_a_weak_proposal_falls_back_and_blocks_on_review`, because
without an interactive surface the sabotaged ladder ends in the same
blocked place. A test named as a sabotage detector must detect the
sabotage.

1. In that test, after the existing record assertions, assert the route
   gate's recorded ladder through the same public read the integration
   guard uses — `gate_draft(...)["resolution"]["candidates"]` — is exactly
   `[("strategy:decision", "failed"), ("strategy:resolve", "accepted")]`.
   The Phase 1 ladder inserts an unavailable `strategy:prompt` rung
   between them, so the sabotaged module now fails this test.
2. Re-run the sabotage and record the result (the step T10 left
   unrecorded): with R1 and R2 committed, change
   `_gate_strategy_list`'s `declared == "decision"` branch back to
   `["decision", "prompt", "resolve"]` unconditionally, run
   `uv run pytest examples/standalone/hermetic_router/tests/test_router.py::test_a_weak_proposal_falls_back_and_blocks_on_review -q --no-header`
   → it must FAIL; `git checkout -- src/functualize/_engine/gate_service.py`;
   re-run → pass. The failing run's summary goes in the tick commit body.

Commands: `uv run pytest examples/standalone/hermetic_router -q --no-header > /tmp/repair-r2.log 2>&1` → all pass, including the strengthened test.

Gates:

```bash
rg -c "\"strategy:resolve\"" examples/standalone/hermetic_router/tests/test_router.py
```
now: `0` · after: `1`

```bash
rg -c "effecting=True" examples/standalone/hermetic_router
```
now: `0` · after: `0` (invariant — carried from the feature)

Closed when: gates as `after:`, the example suite passes, the sabotage
re-run is recorded in the commit body, and the standing checks are clean.
Commit: `test(examples): make the weak-proposal test assert its ladder`.

## Wave 1 — the public record

### [x] R3 — PR #72's body matches its checkpoint

*Files:* none in the repository — the merged PR #72's body on GitHub.

Finding 3: PR #72's body line 25 claimed "Each production path was broken
once and a test failed; the checkpoint commit lists each sabotage and the
acceptance-criteria sweep." Its own checkpoint (`420b6b3`) records that
the `gate_service.py` sabotage did **not** fail the named AC-3 test — two
other tests caught it. The sentence is corrected to say what happened:
every path was broken once; one sabotage (the ladder revert) was caught
by two other tests rather than its named one, disclosed in the checkpoint
at the time, and this repair's checkpoint records the re-run of that
sabotage against the strengthened test, which now fails it.

Closed when: the live PR body carries the corrected sentence and nothing
else in it changed. Evidence: the before/after sentence quoted in the
tick commit body. Commit (repository-side tick only):
`docs(spec): tick the pr body correction`.

**Closed 2026-10-03 — found already corrected.** The live body no longer
contains the inaccurate sentence; its correction paragraph and a matching
*Risks* bullet describe exactly this repair (the recorded-rung assertion,
the sabotage now failing on the extra prompt rung), and read true against
this branch's commits. The correction could not be attributed to an actor
from the readable PR timeline; no further edit is needed and none was
made here.

## Wave 2 — clearing

### [ ] R4 — the deletion-only tip

*Files:* `.spec/features/hermetic-router-repair/` (deleted)

Whole-tree gates first, then:

```
git rm -r .spec/features/hermetic-router-repair
git commit -m "chore(spec): clear the hermetic-router-repair artifacts"
git push
```

Deletion-only under `.spec/features/` — no other path in the commit, so
`spec-artifacts-cleared` goes green on the pushed head. No merge by any
agent.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["R1", "R2"] },
    { "id": 1, "tasks": ["R3"] },
    { "id": 2, "tasks": ["R4"] }
  ]
}
```
