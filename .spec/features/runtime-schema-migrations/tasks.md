# Runtime schema — Tasks

Refined against `03fbb64` on 2026-09-25; recomputed 2026-09-26 after the maintainer answered
D1 = A, D2 = 1, D3 = B (`spec.md` → *Decisions*). The scaffold's tables and JSON-boundary tasks
were specification and are done in `schema.md` §2–§3. The migration runner, revision `0001` and
the relational retention statement moved to `sqlite-runtime-provider` (its tasks 0.1–0.3). No
task here is held.

## How to read a task

- **Depends on** is the task's dependency set. It is deliberately *not* spelled `after:` — in this
  repository `after:` is the recorded value of a counting gate, read by
  `tests/spec/_gate_parser.py`, and a dependency list written as `after: T4` next to a fence would
  be read as a gate expecting `4`.
- A **counting gate** is a single command in a `bash` fence followed by `now: \`N\` · after:
  \`M\``. `now:` was measured on this branch at `fc40e63`; `after:` is what the task's work must
  produce. `tests/spec/test_task_gates_still_hold.py` re-runs the gate of every `[x]` task.
- The **behavioural gates** (tests, sabotage) are listed under each task and are what closes it;
  the counting gates are the cheap tripwire that it stays closed.

Every task closes only with: the five checks green (`ruff check`, `ruff format --check`, `mypy
src/`, `lint-imports`, targeted `pytest`), its production call path named, and — for any task
that wires behaviour — the sabotage proof (commit, remove the change, watch the gate fail,
restore). Wave ordering is binding.

| New | Was (2026-09-25) | | New | Was |
|---|---|---|---|---|
| T1 | 1.1 | | T6 | 3.1 |
| T2 | 1.2 | | T7 | 3.2 |
| T3 | — (new, D2) | | T8 | 6.1 |
| T4 | 2.1 | | T9 | 7.1 |
| T5 | 4.1 | | — | 5.1, 5.2 → `sqlite-runtime-provider` 0.1, 0.2 (D3) |

## Wave 0 — vocabulary and the walk's entry stamp

### [x] T1 — the four machines as data

*Depends on:* none. *Files:* `src/functualize/_types/lifecycle.py` (new),
`tests/types/test_lifecycle_tables.py` (new).

Tests: each machine's `transitions ⊆ (states ∪ {None}) × states` and `absorbing ⊆ states`, no
edge leaves an absorbing state; `SCOPE` equals `schema.md` §1.1 row for row (absorbing
`{cancelled}`, evictable `{completed, failed, cancelled}`, `completed → completed` present as a
self-edge); `RUN.absorbing == {s.value.lower() for s in RunStatus if s.terminal}`; an
import-line test shows the module imports stdlib and `functualize._types.enums` only.

```bash
rg -c '^(SCOPE|RUN|ATTEMPT|INPUT_REQUEST): Final\[Machine\]' src/functualize/_types/lifecycle.py
```
now: `0` · after: `4`

```bash
rg -c 'TRANSITIONAL\(workflow-persistence-atomic\)' src/functualize/_types/lifecycle.py
```
now: `0` · after: `2` — the two D1 retry edges, `failed → running` and `completed → running`.

### [x] T2 — `IllegalTransition`

*Depends on:* none. *Files:* `src/functualize/_types/errors.py`,
`tests/types/test_illegal_transition.py` (new).

Tests: the message names machine, current and target; the attributes are readable; it pickles.

```bash
rg -c '^class IllegalTransition\(Exception\)' src/functualize/_types/errors.py
```
now: `0` · after: `1`

### [ ] T3 — every entry into a walk stamps `running` (D2 = 1)

*Depends on:* none. *Files:* `src/functualize/_engine/frontier.py` (`FrontierWalk.start`, resumed
branch `:341-349`), `src/functualize/app/_workflow_view.py` (docstrings `:109`, `:212-215`),
`src/functualize/app/_workflow_control.py` (docstring `:218-220`),
`tests/workflow/test_resumed_walk_says_running.py` (new), `tests/workflow/test_watch_stream.py`
(module docstring `:25` quotes the old sentence).

Tests: (a) a walk resumed from `blocked` reads `running` from the store while a step runs,
`list_scopes` reports it `running` (not `waiting`/`ready`), and `advanceable_scopes` lists it;
(b) the same for a walk resumed from `failed` and for `--retry-epilogue` on a `completed` scope,
each ending `completed`; (c) the silent-step detector (`frontier.py:245`, requires
`status == RUNNING`) diagnoses a silent step inside a **resumed** walk — at `03fbb64` it returns
`None` there; (d) `tests/workflow/test_cancel_is_terminal.py` passes unchanged
(`WorkflowRunner.prelude` refuses a cancelled scope before `start`, so the stamp never overwrites
`cancelled`); (e) sabotage: drop the new stamp, (a) and (c) fail.
*Call path:* `WorkflowWalker._run_walk` (`workflow_walker.py:444`) → `FrontierWalk.start` →
`ScopeStore.set_scope_status`.

```bash
rg -c 'set_scope_status\(self\._scope_id, WalkState\.RUNNING\)' src/functualize/_engine/frontier.py
```
now: `1` · after: `2`

```bash
rg -l 'for its whole duration' src/functualize tests/workflow | wc -l
```
now: `3` · after: `0` — the three files that say a resumed walk reports `blocked`.

## Wave 1 — the check, and one retention policy

### [ ] T4 — `require_transition`

*Depends on:* T1, T2. *Files:* `src/functualize/_primitives/transitions.py` (new),
`tests/primitives/test_transitions.py` (new).

Tests: for every machine the full product `(states ∪ {None}) × states` is enumerated and the
function accepts exactly `machine.transitions`, raising `IllegalTransition` otherwise; an unknown
target raises. AC1.

```bash
rg -c '^def require_transition\(' src/functualize/_primitives/transitions.py
```
now: `0` · after: `1`

### [ ] T5 — one retention policy; the eviction set named for what it is

*Depends on:* T1. *Files:* `src/functualize/_types/retention.py` (new),
`src/functualize/_primitives/scope_format.py`, `src/functualize/_primitives/run_format.py`,
`tests/primitives/test_scope_cap.py`.

Tests: the existing cap tests pass unchanged; a test constructs a smaller policy and sees both
trims honour it; `TERMINAL_SCOPE_STATUSES` takes its value from `SCOPE.evictable`. The run-log
trim (`run_format.py:111-142`) evicts oldest-first by ULID and carries no status wording
(`rg -n -i 'terminal|finished|never leave' src/functualize/_primitives/run_format.py` → 0 at
`03fbb64`), so it only swaps `RUNS_LIMIT` for the policy. AC7 (document half).
*Call path:* `ScopeStore._mutate` → `normalize`/`_trim` on every write.

```bash
rg -n '= 500$' src/functualize/_primitives/scope_format.py src/functualize/_primitives/run_format.py | wc -l
```
now: `3` · after: `0` — `SCOPES_LIMIT`, `EVENTS_PER_SCOPE_LIMIT`, `RUNS_LIMIT`.

```bash
rg -c 'can never leave' src/functualize/_primitives/scope_format.py
```
now: `1` · after: `0` — `scope_format.py:125` calls the evictable set "values a scope can never
leave", which D1 made false: `completed → running` is reachable by a plain `resume <id>`.

## Wave 2 — enforcement at the two writers

### [ ] T6 — scope enforcement at the choke point

*Depends on:* T4, T3. *Files:* `src/functualize/_primitives/scope_store.py`,
`tests/primitives/test_scope_transitions.py` (new), plus the hit set of
`rg -n 'set_scope_status\(' tests plugins` that writes a now-illegal move (38 sites / 18 files at
`03fbb64`; known example: `tests/test_state_store.py:112-116` writes `running → blocked →
completed`, illegal after D2, and is rewritten through `running`; the record-mode run lists the
rest).

Tests: (a) **record mode first, on a tree that already has T3**: run `tests/workflow
tests/integration tests/primitives tests/test_scope_store.py tests/test_state_store.py` and
`plugins/substrates/functualize-substrate-sqlite/tests` with the check logging every pair; zero
pairs outside `SCOPE.transitions`. Expected after D2: `running → {running, blocked, completed,
failed, cancelled}`, `blocked → {running, cancelled}`, `failed → running`,
`completed → {running, completed}` — the pre-D2 probe's `blocked → completed` and
`failed → completed` must be gone. (b) Refuse mode: `cancelled → running` and
`blocked → completed` through `ScopeStore.set_scope_status` raise `IllegalTransition` and leave
the envelope byte-identical. (c) AST line count of `class ScopeStore` ≤ 930 (smell 1, accepted
2026-09-26). (d) The cancel race still resolves by the fence first
(`tests/workflow/test_cancel_wins_the_race.py` unchanged). (e) Sabotage. AC2, AC4.
*Call path:* `FrontierWalk.complete` → `ScopeStore.set_scope_status` (and the other 12 writers).

```bash
rg -c 'require_transition\(SCOPE' src/functualize/_primitives/scope_store.py
```
now: `0` · after: `1`

```bash
rg -c '' src/functualize/_types/persistence.py
```
now: `700` · after: `700` — invariant: ADR-026 stays closed; nothing in this wave adds to the port
module.

### [ ] T7 — run enforcement at `close_run`

*Depends on:* T4. *Files:* `src/functualize/_primitives/run_store.py`,
`tests/primitives/test_run_transitions.py` (new).

Tests: closing an already-`success` run raises and leaves the record unchanged; closing a
`running` run with each of the 9 lower-cased `RunStatus` values behaves per `schema.md` §1.2;
sabotage. AC2.
*Call path:* `Executor._close_run_record` → `RunStore.close_run` (`executor.py:1108`).

```bash
rg -c 'require_transition\(RUN' src/functualize/_primitives/run_store.py
```
now: `0` · after: `1`

## Wave 3 — the durable half

### [ ] T8 — durable half

*Depends on:* T3, T5, T6, T7. *Files:* `contributor/reference/runtime-persistence-data-model.md`
(§1 rows per D1/D2 and the absorbing/evictable split, §6, §7 pointing at
`sqlite-runtime-provider` for the runner), `contributor/reference/workflow-walker.md` (resumed
walks say `running`), `contributor/architecture/dependency-graph.md` (two new `_types` modules,
one `_primitives`), `.spec/STATUS.md`, `CHANGELOG.md`.

Check: every **Δ** and every D-row consequence in `schema.md`/`spec.md` appears in the reference
document; `tasks.md` boxes match the commits; the message-hygiene key pattern
`\b[A-Z]{2,10}-[0-9]{1,6}\b` over the changed prose finds permitted prefixes only.

## Wave 4 — clearing (second push, deletion-only, last)

### [ ] T9 — clearing commit

*Depends on:* T8, and a green validation run on the pushed T8 tip. *Files:*
`git rm -r .spec/features/runtime-schema-migrations contributor/architecture/research`.

Check: `git show --stat HEAD` lists deletions only.

```bash
git ls-files .spec/features contributor/architecture/research | wc -l
```
now: `26` · after: `0`

## Task Dependency Graph

Edges (`task ← depends on`): T1 ← ∅ · T2 ← ∅ · T3 ← ∅ · T4 ← {T1, T2} · T5 ← {T1} ·
T6 ← {T4, T3} · T7 ← {T4} · T8 ← {T3, T5, T6, T7} · T9 ← {T8}.

```json
{
  "waves": [
    {"id": 0, "tasks": ["T1", "T2", "T3"]},
    {"id": 1, "tasks": ["T4", "T5"]},
    {"id": 2, "tasks": ["T6", "T7"]},
    {"id": 3, "tasks": ["T8"]},
    {"id": 4, "tasks": ["T9"]}
  ],
  "depends_on": {
    "T1": [], "T2": [], "T3": [],
    "T4": ["T1", "T2"], "T5": ["T1"],
    "T6": ["T4", "T3"], "T7": ["T4"],
    "T8": ["T3", "T5", "T6", "T7"],
    "T9": ["T8"]
  }
}
```
