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
| T5 | 4.1 | | T10 | — (new 2026-09-26, the inline-gate write-ahead found by T6's probe) |
| | | | — | 5.1, 5.2 → `sqlite-runtime-provider` 0.1, 0.2 (D3) |

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

### [x] T3 — every entry into a walk stamps `running` (D2 = 1)

*Depends on:* none. *Files:* `src/functualize/_engine/frontier.py` (`FrontierWalk.start`, resumed
branch `:341-349`), `src/functualize/app/_workflow_view.py` (docstrings `:109`, `:212-215`),
`src/functualize/app/_workflow_control.py` (docstring `:218-220`),
`tests/workflow/test_resumed_walk_says_running.py` (new), `tests/workflow/test_watch_stream.py`
(module docstring `:25` quotes the old sentence).

Tests: (a) a walk resumed from `blocked` reads `running` from the store while a step runs,
`list_scopes` reports it `running` (not `waiting`/`ready`), and `advanceable_scopes` lists it;
(b) the same for a walk resumed from `failed`; a `completed` scope re-entered by a resume is
stamped on `FrontierWalk.start`'s **first-entry** branch, because completion cleared the position —
replay then skips every recorded step, so no step callback can witness the stamp and it is read at
the seam, through the call `WorkflowWalker._run_walk` makes (`--retry-epilogue` drives this entry;
the epilogue *body* re-running is `TestRetryEpilogue`'s, not this file's); (c) the silent-step
detector (`frontier.py:245`, requires
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

### [x] T4 — `require_transition`

*Depends on:* T1, T2. *Files:* `src/functualize/_primitives/transitions.py` (new),
`tests/primitives/test_transitions.py` (new).

Tests: for every machine the full product `(states ∪ {None}) × states` is enumerated and the
function accepts exactly `machine.transitions`, raising `IllegalTransition` otherwise; an unknown
target raises. AC1.

```bash
rg -c '^def require_transition\(' src/functualize/_primitives/transitions.py
```
now: `0` · after: `1`

### [x] T5 — one retention policy; the eviction set named for what it is

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

## Wave 2 — the inline gate stops parking the scope

### [x] T10 — an inline-resolved gate records its slot without the `blocked` status

*Depends on:* T3. *Files:* `src/functualize/_engine/frontier.py` (`FrontierWalk.block`, `:434`),
`src/functualize/_engine/workflow_walker.py` (`_service_gate`'s inline arm, `:747-758`),
`tests/integration/test_surface_feature_matrix.py`
(`TestPromptGates::test_the_flag_is_accepted_on_both_doors`, `:512`).

Why (the wave-2 stop at `29ae049`): `FrontierWalk.block` is one batch —
`set_position(node)`, `set_scope_status(BLOCKED)`, `put_gate(payload: None)` — with two callers.
`_block` (`workflow_walker.py:929`, reached from `_service_gate`'s `payload is None` arm) is a real
suspension and ends in `WalkReport(BLOCKED)`. The inline arm (`:747`) is not: the gate ladder has
already resolved the payload, `deposit_gate_payload` (`:758`) needs the gate slot to exist first,
and the same call carries on through `_advance` (`:898`) to `FrontierWalk.complete`
(`frontier.py:368`), which writes `completed` with no `FrontierWalk.start` in between. The
`blocked` stamp there is a side effect of the write-ahead, and it leaves `blocked → completed` in
the durable record — the move D2 was chosen to make impossible. The maintainer's ruling
(2026-09-26): the table stands; the write-ahead stops parking the scope.

Shape (*Replace Parameter with Explicit Methods*, not a boolean flag): a new
`FrontierWalk.record_gate(node, gate_name, *, model, input_schema, tools, blocked_at)` persists
the position and the gate slot in one batch and leaves the status alone; `block(...)` keeps its
signature and becomes `record_gate(...)` plus `set_scope_status(BLOCKED)` in the same batch. The
inline arm calls `record_gate`; `_block` keeps calling `block`. The walk is live throughout, so
`running` is the true stored state and no reader ever sees a parked scope mid-resolution. No new
`RUNNING` call site: T3's gate stays at `2`. The rejected alternative — re-stamp `RUNNING` after
the deposit — would leave a false `blocked` in the durable sequence and add a third `RUNNING`
site; it is only the fallback if the write-ahead turns out to need the parked state, and then this
task stops and reports rather than choosing it.

Tests: (a) **regression witness on both doors** — `test_the_flag_is_accepted_on_both_doors`
(`cli_run` is in-process, `tests/conftest.py:705`, so a `monkeypatch` spy on
`ScopeStore.set_scope_status` sees the real writes) additionally asserts exit code 0, that no
`blocked` status is written during the run, and that the scope ends `completed`, on `[func]` and
`[app]`; (b) the real suspension is unchanged: a gate with no payload and no resolving strategy
still stores `blocked` and returns `WalkOutcome.BLOCKED` (`tests/engine/test_workflow_gates.py`,
`tests/workflow` pass unchanged); (c) sabotage: point the inline arm back at `block` → (a) fails on
both doors. *Call path:* `WorkflowWalker._service_gate` (`workflow_walker.py:726`), inline arm →
`FrontierWalk.record_gate` → `ScopeStore.set_position` / `put_gate`.

```bash
rg -c 'def record_gate\(' src/functualize/_engine/frontier.py
```
now: `0` · after: `1`

```bash
rg -c 'self\._walk\.block\(' src/functualize/_engine/workflow_walker.py
```
now: `2` · after: `1` — only `_block` (`:929`) still parks the scope.

```bash
rg -c 'set_scope_status\(self\._scope_id, WalkState\.BLOCKED\)' src/functualize/_engine/frontier.py
```
now: `1` · after: `1` — invariant: the suspension writer keeps exactly one `BLOCKED` stamp.

## Wave 3 — enforcement at the two writers

### [x] T6 — scope enforcement at the choke point

*Depends on:* T4, T3, T10. *Files:* `src/functualize/_primitives/scope_store.py`,
`tests/primitives/test_scope_transitions.py` (new), `tests/test_state_store.py`
(`test_status_transitions`, `:111-116`, writes `blocked → completed` as setup — rewritten through
`running`), `tests/integration/test_scope_lifecycle.py`
(`test_a_blocked_scopes_state_is_still_writable`, `:177`, writes `blocked → blocked` as setup —
rewritten, the self-edge is **not** admitted), plus any further hit of
`rg -n 'set_scope_status\(' tests plugins` that the record-mode run shows writing an off-table
pair (none expected beyond these two).

Tests: (a) **record mode first, on the tree that has T3 and T10**: run `tests/workflow
tests/integration tests/primitives tests/test_scope_store.py tests/test_state_store.py` and
`plugins/substrates/functualize-substrate-sqlite/tests` with the check logging every pair, and
paste the full set with counts. Before the two setup rewrites the only off-table pairs are those
two direct writes (`blocked → completed` ×1, `blocked → blocked` ×1); after them the set is exactly
`running → {running, blocked, completed, failed, cancelled}`, `blocked → {running, cancelled}`,
`failed → running`, `completed → {running, completed}`. The wave-2 probe at `29ae049` found
`blocked → completed` ×3 — two of them the `[func]` and `[app]` cases of
`test_the_flag_is_accepted_on_both_doors` (the inline-gate write-ahead, closed by T10) — and
`blocked → blocked` ×1; if any production pair outside the table remains, stop and report instead
of enforcing. (b) Refuse mode: `cancelled → running` (the absorbing state) and
`blocked → completed` (a scope completing out of a parked state) through
`ScopeStore.set_scope_status` raise `IllegalTransition` and leave the envelope byte-identical.
These two refusals witness the table; they are not T3's landing evidence, which stays with
`tests/workflow/test_resumed_walk_says_running.py` (its (a)/(c) failed under T3's sabotage). With
the guard on, a regression of T3's stamp or of T10's write-ahead would write `blocked → completed`
on a real path and raise, so `test_resumed_walk_says_running.py` and
`test_the_flag_is_accepted_on_both_doors` fail loudly rather than silently. (c) AST line count of
`class ScopeStore` ≤ 930 (smell 1, accepted 2026-09-26; measured 930 at `29ae049`). (d) The
cancel race still resolves by the fence first (`tests/workflow/test_cancel_wins_the_race.py`
unchanged). (e) Sabotage. AC2, AC4.
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

### [x] T7 — run enforcement at `close_run`

*Depends on:* T4. *Files:* `src/functualize/_primitives/run_store.py`,
`tests/primitives/test_run_transitions.py` (new).

Tests: closing an already-`success` run raises and leaves the record unchanged; closing a
`running` run with each of the 9 lower-cased `RunStatus` values behaves per `schema.md` §1.2;
sabotage. AC2.
*Call path:* `Executor._close_run_record` → `RunStore.close_run` (`executor.py:1108`).

```bash
rg -c 'require_transition\(RUN' src/functualize/_primitives/run_store.py
```
now: `0` · after: `2` — the count stands for the guard on every status write in this file; the
second call site is the creation edge, `RunStore.open_run`, added after the closing guard T7
recorded, so the number moved while the rule did not.

## Wave 4 — the durable half

### [x] T8 — durable half

*Depends on:* T3, T5, T6, T7, T10. *Files:* `contributor/reference/runtime-persistence-data-model.md`
(§1 rows per D1/D2 and the absorbing/evictable split, §6, §7 pointing at
`sqlite-runtime-provider` for the runner), `contributor/reference/workflow-walker.md` (resumed
walks say `running`), `contributor/architecture/dependency-graph.md` (two new `_types` modules,
one `_primitives`), `.spec/STATUS.md`, `CHANGELOG.md`.

Check: every **Δ** and every D-row consequence in `schema.md`/`spec.md` appears in the reference
document; `tasks.md` boxes match the commits; the message-hygiene key pattern
`\b[A-Z]{2,10}-[0-9]{1,6}\b` over the changed prose finds permitted prefixes only; and the two
revision-pinned pages under `contributor/architecture/run-model/` —
`10-graph-semantics.md:97` and `evidence/verified.md:101` — keep the retired sentence
("a resumed walk reports `blocked` for its whole duration") **deliberately**: both are snapshots of
what was true at `e57f0c9` and say so in their headers (`# Verified — fact index at e57f0c9`), so
the quote stays as it was read rather than being rewritten to today. `contributor/reference/
workflow-walker.md` is the live page, and it is the one that changes.

## Wave 5 — clearing (second push, deletion-only, last)

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
T10 ← {T3} · T6 ← {T4, T3, T10} · T7 ← {T4} · T8 ← {T3, T5, T6, T7, T10} · T9 ← {T8}.
T7 does not depend on T10; it sits in wave 3 so that it stays behind the amended T6, as dispatched.

```json
{
  "waves": [
    {"id": 0, "tasks": ["T1", "T2", "T3"]},
    {"id": 1, "tasks": ["T4", "T5"]},
    {"id": 2, "tasks": ["T10"]},
    {"id": 3, "tasks": ["T6", "T7"]},
    {"id": 4, "tasks": ["T8"]},
    {"id": 5, "tasks": ["T9"]}
  ],
  "depends_on": {
    "T1": [], "T2": [], "T3": [],
    "T4": ["T1", "T2"], "T5": ["T1"],
    "T10": ["T3"],
    "T6": ["T4", "T3", "T10"], "T7": ["T4"],
    "T8": ["T3", "T5", "T6", "T7", "T10"],
    "T9": ["T8"]
  }
}
```
