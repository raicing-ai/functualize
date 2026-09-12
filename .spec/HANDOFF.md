# Handoff — `feat/run-model`, 2026-09-12

`workflow-graph-semantics`/T2 is **closed**. What remains is T3–T7; the
hazards section below is the durable half of this file.

Worktree: `.worktrees/pi-parity`. Branch: `feat/run-model`. Tree is clean.

---

## Where the roadmap stands

| Feature | State |
|---|---|
| `capability-duality` | done, 12/12 |
| `durable-run-layer` | done, 14/14 |
| `scope-record-lifecycle` | done, 6/6 |
| **`store-substrate`** | **done, 9/9** — fully verified, see below |
| **`workflow-graph-semantics`** | **T1, T2 done and verified. T3–T7 not started.** |

No PR yet; the plan is one PR after the whole roadmap executes.

### Last full verification (at `5d4799b`, T2 closed)

- `uv run pytest tests/ --run-slow -q -n 8` → **12,009 passed, 155 skipped**
- `FUNCTUALIZE_TEST_SUBSTRATE=sqlite` → **10,500 passed, 0 failed**
- All 12 plugin suites pass, run one package at a time
- `ruff`, `ruff format --check`, `mypy` (352 files), `lint-imports` (7
  contracts) clean
- T2's seven sabotages all bite
  (`.spec/features/workflow-graph-semantics/sabotage-t2.py`)

A package-build test failed twice on one run with `Request failed after 3
retries` and passed on a rerun — network, not code. Rerun before believing one.

---

## What T2 turned up, since it changes how to approach T3–T7

Three of seven sabotages were **inert on the first sweep**, and none was a
formality:

- **Nothing tested the one line `Loop` rests on.** The loop tests drive the
  walker with a `WorkflowDeclaration`, which bypasses validation entirely, and
  the cycle tests use plain `Edge`s — so making `Loop` count as a cycle edge
  again broke nothing. **T3–T7 will have the same blind spot**: a test that
  builds a declaration directly never exercises `_validate_workflow_graph`.
- **An optimization was mistaken for correctness.** `_resume_iteration` could
  return `0` with identical executions, because replay already skips finished
  work. The AC-4 test was asserting something replay guaranteed on its own.
  Probe before assuming which half of a pair does the work.
- **A sabotage can be inert two different ways in a row.** The cursor one
  needed two sites edited at once; the sweep script supports that now.

Also pinned rather than fixed: **a gate inside a loop is answered once and
reused for every later pass**, because gate payloads are keyed by name and not
by name and iteration. `test_a_gate_inside_a_loop_is_answered_once_for_every_
pass` is what will fail when that changes, and it should be *changed* then, not
deleted.

---

## T3–T7, unstarted

Read `.spec/features/workflow-graph-semantics/tasks.md`. Its own Wave Audit
table lists the hazards to check for, and all four have occurred on this branch.

- **T3** `OnFailure` — failure becomes an edge. The regression gate (*without*
  an `OnFailure`, a raising step still stops the walk and marks the scope
  `failed`) is to be written **first**.
- **T4** `timed_out`, `cancelled`, `TERMINAL_SUCCESS` — replay-skip keys on a
  named set, not the literal `"success"`.
- **T5** step-level events and `watch`. Sabotage: remove the emit calls; `watch`
  must **stop updating**, not fall back to polling.
- **T6** `Notify` on the effects outbox, exactly once across a real `kill -9`.
- **T7** feature gate.

---

## Things that will bite you

**Recorded gates on this branch rot, and several were already false.** Four were
found stale while executing `store-substrate`:

- `store-substrate`/T4's counted three symbols earlier tasks had renamed or
  deleted, so it returned `0` *before* the task ran.
- `store-substrate`/T5's grep was satisfied by four docstrings *explaining* the
  deletion.
- `workflow-graph-semantics`/T1's was recorded `0` and actually returned `1`,
  and that hit was the module docstring saying the check lives elsewhere.
- `durable-run-layer`/T6's drifted 14→13 from a rename in T3.

**Measure every gate before writing `now:`.** Where a grep can be satisfied by
prose, replace it with an AST walk — and give the walk a guard that it found
anything at all, or it becomes a gate that cannot fail.

**Commit before sabotaging.** `git checkout -- <file>` reverts everything
uncommitted in that file; this branch has paid for that twice.

**`uv sync --all-packages` drops the dev extras** and Textual goes with them,
which surfaces as ~20 unrelated TUI autocomplete failures. Use
`uv sync --all-extras` to restore.

**The TUI smartbar tests flake under load** at `-n 8` (`.spec/KNOWN-RED.md` §11).
Rerun in isolation before believing one; a *different* test failing on the
second run means load, not a break.

---

## Open items carried forward, not lost

- **A lockless substrate needs a retry loop.** The stores do
  `with lock(key): read; mutate; write(...)` and ignore what `write` returns,
  which is correct while `lock` provides exclusion. A backend that cannot lock —
  DynamoDB, S3 — makes `lock` a no-op and relies on `expect`, and then a `False`
  return means "re-read and retry" and nothing retries. Not built: SQLite locks,
  so no shipped implementation exercises it, and a retry path with no failing
  caller is the gate-that-cannot-fail shape. Recorded under
  `store-substrate`/T7; it belongs with the first lockless substrate.
- **No AWS substrate exists.** The user asked about S3/DynamoDB and a
  localstack-style emulator; the answer is that only SQLite was built, and they
  chose to finish the roadmap first.
- **One inert sabotage, deliberately left.** Caching the engine's `ScopeStore`
  fails nothing, because `durable-run-layer`/T6 keyed fencing per scope. The
  stale safety claim was deleted from `_scope_store()`'s docstring rather than a
  test invented for a hazard that no longer exists.
- **`FunctualizeApp`'s facade budget is 302**, raised from 300 for
  `EngineHost.substrate`, with the reason in `tests/test_facade_loc_limits.py`.
  No headroom was added, so the next addition trips it.
