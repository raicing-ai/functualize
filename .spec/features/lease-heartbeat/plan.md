# Lease heartbeat plan

## Approval and boundaries

The behavior in `spec.md` was confirmed on 2026-10-11. This plan and its task
graph await review before Execute. `Shape state` is `not-required`; the change
adds no job-facing control or public API. The existing claim algorithm,
generation fence, non-interruptible step rule, and 300-second default lease stay
in place.

## Architecture gate

The Specify prose pass found the established timeout decision in
`contributor/architecture/run-model/08-durable-runs.md` §D: an in-process Python
step is not preempted by a lease. This Plan pass used `zg` over the worktree's
866-file local index, Serena symbol and reference queries activated by absolute
worktree path, and graphify neighbors for `WorkflowWalker`, `FrontierWalk`,
`ScopeStore`, and `WorkflowRunner`. The committed graph names the dependency
direction, but its `built_at_commit` is not resolvable in this checkout; source
and Serena are the authority for current methods and call sites. I read the five
`contributor/architecture/codemaps/` documents; their layer model matches the
region below. `uv run lint-imports` reports 7 kept, 0 broken before the change.

The design review consulted the repository's `python-design-patterns` skill
(single responsibility, composition, keep it simple) and the
`design-patterns-refactoring` skill (Large Class, Long Method, and Shotgun
Surgery). The BEFORE already has a Large Class in `WorkflowWalker` and a Long
Method in `_run_walk`; renewal timing is mixed into graph traversal. A candidate
that added a loop and thread state inside `WorkflowWalker` worsened Large Class.
The settled AFTER extracts one per-walk lifecycle object. It does not split
lease timing across the runner, store, and public delivery layers, avoiding
Shotgun Surgery.

### BEFORE

```text
_engine/workflow_runner.py                 engine peer layer
  -> _engine/workflow_walker.py            engine peer layer: claim/run/release
       -> _engine/frontier.py              engine peer layer: claim, renew, step record
            -> _types/persistence.py       data/port boundary: claim outcome
            -> _primitives/scope_store.py  foundation boundary: renewal + fenced write
                 -> _primitives/lease.py    foundation: generation and expiry rules

WorkflowWalker._run_walk -> FrontierWalk.renew AFTER each node returns.
The node body runs without a renewal caller; the lease may lapse mid-step.
```

### AFTER

```text
_engine/workflow_runner.py                 engine peer layer
  -> _engine/workflow_walker.py            engine peer layer: owns walk lifetime
       -> _engine/lease_heartbeat.py       engine peer layer: per-walk wait/stop/join
            -> _engine/frontier.py         engine peer layer: classified renewal
                 -> _primitives/scope_store.py -> _primitives/lease.py
       -> _engine/frontier.py              claim, fenced step writes, release
            -> _types/persistence.py       existing claim port boundary

After claim, one heartbeat waits 60 seconds between renewals, even during a
node. Before the walk reports an outcome, it stops and joins. The walker
continues to own the existing generation-fenced writes and release.
```

All new imports stay within `_engine/` or point down to `_primitives/`; there is
no peer-layer import, delivery-layer import, or schema change. `ScopeStore`
already keeps open batches in `threading.local()` and serializes document
mutations under the substrate lock, so a heartbeat renewal can use the same
store from a separate thread without joining the step thread's batch. The
`runner_identity()` value is process-based, not thread-based.

## Technical approach

1. Make `FrontierWalk.renew()` report distinct internal outcomes for success,
   stale generation, and another renewal error while preserving best-effort
   behavior for direct callers. A missing claim has its own outcome. Keep the
   generation unchanged and use `ScopeStore.renew_scope()` as before.
2. Add a per-walk helper in `_engine/lease_heartbeat.py`. Its stop event waits
   for the 60-second interval, avoiding immediate wakeups; each elapsed wait
   renews once. A stale result records lost ownership and ends renewal. A
   transient error is logged and retried on the next interval. The helper
   exposes a testable interval without changing the public API.
3. `WorkflowWalker.run()` starts the helper only after a successful claim and
   stops and joins it on completion, failure, exception, and supersession,
   before releasing the lease. Remove the per-node renewal. Check the helper's
   lost-ownership state before reporting a normal walk end; do not interrupt a
   running step or emit a misleading successful end after takeover.
4. Use the existing engine test harness with a blocked first step, a shortened
   test lease/interval, and a second walker over the same substrate. Observe
   that the second gets `HELD` after the initial lease period while the first
   step is still running, then release the step and assert one execution. Test
   transient and stale renewal separately, and prove the helper thread ends on
   success, a raised step, and a timeout-shaped failure.
5. Align the lease and frontier docstrings and the workflow CLI guide with the
   new behavior. Keep the warning that expiry alone does not prove a runner is
   dead: a delayed or failed heartbeat may allow a live step to be claimed.

## Blast radius and risks

Serena finds the production caller of `WorkflowWalker.run()` in
`WorkflowRunner.prelude()`. Its `FrontierWalk.renew()` reference is the
walker's node-boundary call; other direct references are in
`tests/engine/test_timeout_is_lease_expiry.py`. `ScopeStore.renew_scope()` has
the frontier as its production caller. Graphify confirms the direction from
runner to walker to frontier to store, but its stored line numbers are stale.
The changed files and tests in `tasks.md` follow these hits and the exact prose
search in the documentation task.

The main risk is a renewal I/O failure lasting beyond the lease: another
runner can then claim despite a live step. The design reports and retries a
transient failure; it cannot promise ownership when persistence is unavailable.
Stop-and-join also waits for any in-progress renewal I/O to return. This is
required to leave no heartbeat thread behind; a backend that hangs forever is
a broader storage failure, not a timer behavior to conceal. File locking and
thread-local batches deserve the concurrent two-runner regression test.

## Surviving smells

- **Long Method** — `WorkflowWalker._run_walk` still performs graph scheduling
  and reporting. The plan removes its renewal block and adds no timer branch
  there; decomposing graph traversal is separate work. Needs maintainer review:
  no.
- **Large Class** — `WorkflowWalker` remains broad. The heartbeat is extracted,
  and the class does not gain a new timing responsibility or grow a thread loop.
  A wider class decomposition would expand this bounded fix. Needs maintainer
  review: yes, because the class is already beyond the constitution's size
  guidance. This is an existing smell, not proposed God-object growth.

## Verification and delivery

Before authoring these tasks, baseline `ruff check`, `ruff format --check`,
`mypy src/`, and `lint-imports` passed; the two focused engine test files passed
18 tests. Execute uses the step tier after edits, the engine wave tier at the
checkpoint, and the repository's full PR CI as the tip tier. The production
path to sabotage after a coherent commit is
`WorkflowRunner.prelude -> WorkflowWalker.run -> LeaseHeartbeat ->
FrontierWalk.renew -> ScopeStore.renew_scope`; removing the helper start must
make the long-step two-runner test fail. Restore only after that observation.

After feature validation, migrate durable behavior to `.spec/STATUS.md` or a
contributor reference, then remove `.spec/features/lease-heartbeat/` in the
required deletion-only last commit. The draft PR remains draft until the
implementation and validation evidence are ready for independent review.
