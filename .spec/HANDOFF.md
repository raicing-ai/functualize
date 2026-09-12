# Handoff — `feat/run-model`, 2026-09-12

Stopped at the user's request part-way through `workflow-graph-semantics`/T2.
**Read this before touching anything**, then delete it when T2 closes.

Worktree: `.worktrees/pi-parity`. Branch: `feat/run-model`. Tree is clean.
Head: `2f44f66`.

---

## Where the roadmap stands

| Feature | State |
|---|---|
| `capability-duality` | done, 12/12 |
| `durable-run-layer` | done, 14/14 |
| `scope-record-lifecycle` | done, 6/6 |
| **`store-substrate`** | **done, 9/9** — fully verified, see below |
| **`workflow-graph-semantics`** | **T1 done. T2 code landed, verification incomplete. T3–T7 not started.** |

No PR yet; the plan is one PR after the whole roadmap executes.

### Last full verification (at `949789a`, before T1)

- `uv run pytest tests/ --run-slow -q -n 8` → **11,971 passed, 155 skipped**
- All 12 plugin suites pass, run one package at a time
- `FUNCTUALIZE_TEST_SUBSTRATE=sqlite uv run pytest tests/ -q -n 8` → **10,462
  passed, 0 failed** (the alternate-substrate run, `store-substrate`/T8)
- `ruff`, `mypy` (352 files), `lint-imports` (7 contracts) all clean

At head (`2f44f66`) the fast suite was **10,568 passed** and `mypy` /
`lint-imports` were clean, but `--run-slow` has **not** been run since T1 landed.

---

## T2 — exactly what is left

### Done

`Loop`, `_engine/loop_state.py`, the `(node, iteration)` keying, the validator
change, and `tests/workflow/test_loops.py` (31 tests, all passing). The detail
is in `.spec/features/workflow-graph-semantics/tasks.md` under T2, including the
cursor-versus-queued-work bug the combined test caught and the one-counter
simplification that is recorded rather than fixed.

### Not done — do these first

1. **Finish the sabotage sweep.** The script is at
   `.spec/features/workflow-graph-semantics/sabotage-t2.py` — copied out of
   session scratch so it survives. Run it from the worktree root. It asserts
   each sabotage **applied** before reading the result, which matters: a
   sabotage that silently fails to apply reads as "the tests do not catch
   this", and that happened once on this branch.

   One of seven ran before the stop:

   | sabotage | result |
   |---|---|
   | `visited` keyed by node alone | **6 failed** ✓ |
   | `visited` keyed by iteration alone | not run |
   | the iteration is a cursor, not queued work | not run |
   | the record key ignores the iteration | not run |
   | resume always restarts at iteration 0 | not run |
   | the bound is not enforced | not run |
   | `Loop` edges count as cycle edges again | not run |

   Any that fails **0 tests** is a finding, not a formality — three inert
   sabotages were found on this branch and each was a real gap or a stale claim.

2. **`--run-slow` and the plugin suites**, which have not run since T1.

3. **The alternate-substrate run** (`FUNCTUALIZE_TEST_SUBSTRATE=sqlite`). T1 and
   T2 touch the walker and the step-record key, which is exactly the surface
   that run exercises.

4. **Record T2's gate value** in `tasks.md` — it is written (`now: 7`) but
   re-measure rather than trusting it; gate numbers written from memory have
   been wrong about five times on this branch and
   `tests/spec/test_task_gates_still_hold.py` caught every one.

5. **Mark T2 `[x]`** once the above pass. It is currently `[~]`.

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
