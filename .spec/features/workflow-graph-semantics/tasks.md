# Tasks — workflow-graph-semantics

Every gate was **run at authoring time** against `e57f0c9`; `now:` is what it returned then.
Run gates from the worktree root.

---

## Wave 0 — the breaking change, alone and first

### [x] T1 · An unbounded cycle is refused at declaration

**Files:** `src/functualize/workflow/_validation.py`,
`tests/workflow/test_loops.py` (new), `CHANGELOG.md`

Spec AC-3. Today `_engine/workflow_validation.py:184-185` guards **workflow-to-workflow**
nesting cycles only — *"ordinary jobs terminate a chain and are already cycle-checked as
deps."* Nothing validates a cycle in the step graph, so a declared loop is accepted and
silently runs once.

This changes "silently wrong" to "loudly refused". The message names the cycle and the fix
(declare a `Loop` with a bound). **Breaking** — CHANGELOG entry (risk R-g).

**Gate — the recorded one was wrong, and could not fail**
```bash
rg -c 'cycle' src/functualize/workflow/_validation.py
```
recorded `now: 0`; it actually returned **1**, and that hit was the module
docstring saying *"detecting workflow-nesting cycles … live in discovery, not
here"*. The gate matching its own explanation — the first hazard this feature's
own audit table names. It now returns 19, and would have returned ≥1 for a
comment alone.

Replaced with a count of the code that does it:
```bash
rg -c "def _find_cycle|def _refuse_unbounded_cycle" src/functualize/workflow/_validation.py
```
now: `2` · before: `0`. Deleting either function turns it red; no docstring can
satisfy it.

**Test:** `tests/workflow/test_loops.py`, 16 cases. Half of them build **legal**
graphs, which is not padding: a cycle check that also refused a diamond, or a
conditional whose branches rejoin, would be worse than no check — those are the
ordinary way to write a graph and the refusal would arrive at import time for a
correct declaration. The three-state colouring exists for exactly that, and
`test_a_diamond` is what would catch a plain visited-set.

**Breaking change:** recorded in `CHANGELOG.md` under Unreleased, with the
symptom, the message, what is *not* affected, and the remedy — the graph was
running once, so the edge that closes the cycle was never doing anything.

**Measured:** nothing in the repository declared a cycle. Full suite 10,555
passed, unchanged.

`Loop` does not exist yet (T2), so the message says "declare the repetition with
an explicit bound" rather than naming a type nobody can import. Marked
`# TRANSITIONAL(workflow-graph-semantics/T2)` at the refusal, which says to
update the wording and not the rule when `Loop` lands.

> First and alone deliberately: landing it **before** loops exist makes the refusal
> unambiguous — there is no way to satisfy it except by declaring a bound, which is the intent.

---

## Wave 1 — the dangerous edit

### [x] T2 · `Loop`, iteration identity, and the `visited` keying

**Files:** `src/functualize/workflow/__init__.py`,
`src/functualize/_engine/loop_state.py`,
`src/functualize/_engine/workflow_walker.py`,
`tests/workflow/test_loops.py`

Spec AC-1, AC-2, AC-4. `visited` becomes keyed by `(node, iteration)`. `max_iterations` has no
default.

**Gate**
```bash
rg -c 'visited' src/functualize/_engine/workflow_walker.py
```
now: `4` · before: `3`. Keyed by `(node, iteration)`.

**`7` was written here from memory and was wrong** — the hazard this branch has
now hit about six times, and the reason every gate value is supposed to be
measured before it is written. It is `4`.

A word count is a weak gate either way: it would stay green for a `visited`
keyed any way at all. What actually holds the property is
`test_the_loop_repeats_and_the_join_still_runs_once_per_pass`, and the sabotage
table below is the evidence that it can fail.

#### What landed

- `Loop(source, target, max_iterations, condition=None)` in `_types/workflow.py`,
  exported from `functualize.workflow`. `max_iterations` has no default and
  refuses `0`.
- `_engine/loop_state.py` — `iteration_step_key` and `current_iteration`. The
  iteration is **derived from the step records**, never carried alongside, the
  same argument `workflow_depth` makes for reading nesting out of a scope id: a
  resumed walk in a fresh process has the records and nothing else, and a
  counter beside them could disagree.
- Iteration 0 keys byte-identically to before, so a graph with no `Loop` writes
  exactly the records it always wrote. Nothing is migrated.
- The validator excludes `Loop` from the cycle search, which is the whole
  mechanism: a graph whose only back-edge is a `Loop` passes, and the same graph
  with a plain `Edge` does not.

#### The bug the combined test caught

The first version advanced the iteration as a **cursor** when the loop's source
finished. A diamond join is queued once per branch, so its two arrivals got
different iterations, the second was not pruned, and the join ran twice in one
pass — call order `fan left right join join fan left right join`.

Fixed by making the iteration travel **with the queued work**: `pending` holds
`(node, iteration)` pairs and the back-edge queues `(target, iteration + 1)`.

This is exactly what the task warned about — *"two separate tests can both pass
while the keying is wrong in a third way"* — and it was only visible because the
graph under test is a loop **containing** a diamond and both properties are
asserted in one body.

#### Sabotage — seven, and three were inert until they were fixed

| sabotage | result |
|---|---|
| `visited` keyed by node alone | 1 failed |
| `visited` keyed by iteration alone | 1 failed |
| the iteration is a cursor, not queued work | 1 failed |
| the record key ignores the iteration | 1 failed |
| resume always restarts at iteration 0 | 1 failed |
| the bound is not enforced | walk stops terminating |
| `Loop` edges count as cycle edges again | 1 failed |

Script: `.spec/features/workflow-graph-semantics/sabotage-t2.py`. Three of these
were **inert on the first sweep**, and each was a real finding rather than a
formality:

1. **`Loop` counting as a cycle edge again broke nothing.** Nothing tested that
   a `Loop` makes a cycle legal — the loop tests drive the walker with a
   `WorkflowDeclaration` directly, which bypasses validation, and the cycle
   tests use plain `Edge`s. The one line the feature rests on was unverified.
   `TestALoopIsWhatMakesACycleLegal` now covers it, including the falsifier
   beside it (the same graph with a plain `Edge` is still refused) and that one
   `Loop` does not exempt a *second* unbounded cycle in the same graph.

2. **`_resume_iteration` could return 0 and nothing failed.** Probed rather than
   assumed: the executions are identical, because **replay already skips
   finished work**. What differs is the replaying — `replayed=('approve',
   'approve')` derived, versus `('work', 'approve', 'approve', 'approve')` at
   zero. So it is an *optimization*, and the test asserted the wrong thing. The
   AC-4 test now pins "a resume does not replay iterations it has finished";
   "the loop finishes across a resume" is kept as a separate case precisely
   because it passes either way, and folding the two together is what hid this.

3. **The cursor sabotage was inert twice, in two different ways.** Mutating
   `self._iteration` at the back-edge is overwritten by the next dequeue;
   taking `max(cursor, queued)` at the dequeue is saved by FIFO ordering. The
   property is *the iteration travels with the work*, and removing it takes
   two sites at once — which the sweep script now supports.

#### A limitation found while probing, pinned rather than shipped quietly

**A gate inside a loop is answered once and reused for every later pass.** Gate
payloads are keyed by gate *name*, not by name and iteration, so an approval
inside a retry loop is not asked again. Very likely not what an author expects.

Asserted in `test_a_gate_inside_a_loop_is_answered_once_for_every_pass` rather
than fixed: iteration-keyed gates change the deposit vocabulary that
`--wf-input`, the MCP `answer_gate` tool and the scope record all share, which
is wider than T2 owns. That test is what will fail when it is done, and it
should be **changed** then, not deleted.

#### Known simplification, recorded not guessed at

**One iteration counter for the whole walk.** Two loops in one graph advance the
same counter, so an inner loop's passes also count against an outer one's
`visited` keys. Nothing runs twice under one key and nothing legal is pruned, so
it is correct — but iteration numbers in the records read oddly for nested
loops. A per-loop counter needs a second identity on the record; no shipped
graph nests loops, so it is named in `_loop_back`'s docstring rather than
guessed at.

> **Both failure modes here are silent** (risk R-a). Getting the keying wrong one way runs a
> diamond join twice — which looks like a flaky step. The other way leaves a loop running once
> — which looks like the loop condition was false.
>
> **Write the test before the change**, and assert both properties in **one body**: a diamond
> join runs exactly once per iteration, *and* a loop's second pass is not pruned. Two separate
> tests can both pass while the keying is wrong in a third way.

**Test (AC-4, risk R-b):** resume a walk **mid-loop**; the iteration count continues rather
than restarting. The iteration is part of the step key (F5's record), so replay is unambiguous.

---

## Wave 2 — failure becomes an edge

### [x] T3 · `OnFailure`, with the recorded-route property

**Files:** `src/functualize/workflow/__init__.py`,
`src/functualize/_engine/workflow_walker.py`,
`tests/workflow/test_failure_routing.py`

Spec AC-5, AC-6, AC-7. Today there is one `except`, one exit
(`workflow_walker.py:336-337` — *"a step failure stops the walk"*).

**Gate**
```bash
rg -c 'a step failure stops the walk' src/functualize/_engine/workflow_walker.py
```
now: `1` · after: `1` — **invariant**: the comment stays true for the undeclared
case, which is AC-6. Flagged as one because
`tests/spec/test_task_gates_still_hold.py` rejects a gate whose `now` already
equals its `after` unless it says why, and this one caught it.

It is also a **weak** gate on its own — it counts a comment, which can be
deleted while the behaviour stays and kept while the behaviour changes. The
gate that measures the work:

```bash
rg -c "def _failure_route|_ROUTED_TO_END|isinstance\(edge, OnFailure\)" src/functualize/_engine/workflow_walker.py
```
now: `6` · before: `0`

**Test (AC-6):** `TestAnUndeclaredFailureIsUnchanged`, six cases, **written and
run before any implementation existed** and passing against the unmodified
walker. That is the regression gate: a failure-routing feature that quietly
changes the undeclared case has broken every workflow that exists, invisibly —
the walk would carry on somewhere instead of stopping.

**Test (AC-7):** `TestTheRouteIsRecordedNotReEvaluated`. The route is recorded on
first evaluation and read on replay, extending `_choice_for`'s property rather
than reinventing it. The reason is sharper here: re-evaluating on every resume
pages somebody again for a decision already made.

`END` and "never decided" are recorded **distinctly** (`_ROUTED_TO_END`, a
NUL-prefixed sentinel). Collapsing them made a declared
`OnFailure(target=END)` fail the walk — caught by its own test.

**The validator sees `OnFailure`.** `TestTheValidatorSeesOnFailure` calls
`_validate_workflow_graph` directly, because T2 found that every other test in
these files hands a `WorkflowDeclaration` straight to the walker and never
reaches validation at all. A failure route backwards is deliberately **not** a
cycle: it can only be taken once, since it is recorded on first evaluation and
read on replay, so counting it would refuse the ordinary *"on failure, go back
and clean up"* shape for a loop that cannot run.

### Sabotage

Eight, each asserted to have applied first. All bite.

| sabotage | result |
|---|---|
| every failure routes, declared or not | 1 failed |
| the route is re-evaluated on replay | 1 failed |
| the route is never recorded | 1 failed |
| routed-to-END collapses into no-route | 1 failed |
| a routed failure also takes the success path | 1 failed |
| a routed failure still fails the scope | 1 failed |
| the validator ignores an `OnFailure` target | 1 failed |
| a failure route counts as a cycle edge | 1 failed |

Script: `.spec/features/workflow-graph-semantics/sabotage-t3.py`.

**"A routed failure still fails the scope" was inert twice**, and the reason is
worth keeping. The scope status is rewritten by whatever the walk does next —
`completed` at the end, `blocked` at a gate — so marking it failed at the moment
of routing is invisible to any assertion made *after* the walk.

It is not harmless: a crash in that window leaves the scope reading `failed`,
and `advanceable_scopes` does not offer a failed scope for resume, so a workflow
that was recovering becomes unresumable. The test that catches it has the
**recovery step read the store as it runs**, which is the only place the window
is observable.

---

## Wave 3 — two more outcomes, and a set instead of a literal

### [x] T4 · `timed_out`, `cancelled`, and `TERMINAL_SUCCESS`

**Files:** `src/functualize/_engine/frontier.py`,
`src/functualize/_engine/workflow_walker.py`,
`src/functualize/_engine/dependency_runner.py` *(deviation, below)*,
`tests/workflow/test_typed_step_outcomes.py` (new)

Spec AC-8, AC-9. Decision **L3** — copy pi-workflows' vocabulary rather than invent a third.

**Deviation from the file list, recorded rather than done quietly.**
`dependency_runner._scope_step_succeeded` is a *fourth* replay-skip, and its own
docstring is the argument for including it: *"the same ones the walker replays
from — so 'already ran here' has one answer rather than one per consumer."* Left
comparing the literal, it would be the second consumer with its own spelling,
which is exactly the drift AC-9 names. It is inside the gate's scope
(`src/functualize/_engine/`) even though the task's `**Files:**` line predated
knowing it existed.

**Gate — the recorded one measured the wrong direction**
```bash
rg -c '"success"|"failed"' src/functualize/_engine/frontier.py
```
recorded `now: 2`, and **superseded**. It counts the literals anywhere in the
file, and after this task they legitimately go *up*, not down: the vocabulary
has to be spelled somewhere, and that somewhere is `StepStatus`. A gate whose
correct direction is unknowable measures nothing. (Re-measured before replacing:
it returned `2`, as recorded.)

Replaced with a count of the thing that must disappear — the comparison, not the
string:
```bash
rg -c '== "success"' src/functualize/_engine/
```
now: `4` · after: `0`. Four sites: `frontier.should_replay_skip`, both walker
service handlers, and `dependency_runner._scope_step_succeeded`.

**Gate — replay-skip asks the set**
```bash
rg -c 'in TERMINAL_SUCCESS' src/functualize/_engine/
```
now: `0` · after: `4`. The membership test, not the name: a bare `TERMINAL_SUCCESS`
count is satisfied by the sentence explaining it, which is how
`durable-run-layer`/T6's gate drifted twice (fixed in the same commit — see that
task).

> A future outcome must not silently become replayable by matching a string comparison nobody
> revisited. That is the whole reason for the named set.

**AC-9 cannot be proved by behaviour, and the tests say so.** With one member,
`status in TERMINAL_SUCCESS` and `status == "success"` agree on every input that
exists — the difference appears the day a second success-like outcome is added,
which is the day nobody re-reads the comparison. So the set membership is pinned
**structurally** (`TestNoConsumerSpellsTheOutcomeItself`, an AST walk over the
three consumer modules with a guard that it found real code), and the behaviour
of each outcome is pinned beside it. Claiming a behavioural test for this would
have been the gate-that-cannot-fail shape wearing a test's clothes.

**Test (risk R-d):** `timed_out` is produced **only** by F5's lease expiry. F5's AC-13 grep test
already forbids `SIGALRM`, daemon-thread kills and `asyncio.wait_for` by name; this feature must
not reintroduce them. Honoured, and it decided the design: nothing can preempt a
running step, so the runner that overran is by definition not the one that can
write the fact down. `FrontierWalk.claim` records it — whoever **takes the scope
over** notes the step that went silent.

**What "abandoned" is, and the regression that decides it.** Two facts, not one:
the scope still says `running`, **and** the lease has expired. `lease.release`
expires a lease *in place* rather than deleting it (deleting would reset the
generation and hand out the fence it exists to raise), so "the lease is expired"
is true of every scope that ever finished. A check reading only the lease marks
the gate node of **every resumed workflow** as timed out.
`test_a_clean_release_is_not_a_timeout` is that test, and sabotage 6 is the edit
it catches. The pair is the same one `_workflow_view.derived_state` already
joins, read rather than reinvented.

**`cancelled` is not routable, and the `except` order is what enforces it.**
`ScopeCancelledError` is caught **before** the broad arm, so `OnFailure` (T3)
never sees it: a declared route recovers from a failure, and a human stopping a
workflow is not a failure to recover from. The step outcome and the scope status
move together through `_SCOPE_STATUS_FOR` — a parent left `failed` because its
child was cancelled is a parent someone retries, and every retry re-enters the
child and re-raises the same cancellation.
`test_resuming_the_parent_is_refused_as_cancelled` is the consequence.

**Sabotage:** 11 edits, `sabotage-t4.py`. All 11 bite.

**Measured:** 10,653 passed on the fast suite; `ruff`, `mypy` (352 files),
`lint-imports` (7 contracts) clean.

---

## Wave 4 — the walker speaks, and something listens

### [ ] T5 · Emit step-level events, and `watch`

**Files:** `src/functualize/_engine/workflow_walker.py`,
`src/functualize/_cli/builtins.py`,
`plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`,
`tests/workflow/test_watch_stream.py`

Spec AC-10, AC-11, AC-12. pi-workflows parity test **5**.

**Gate — the walker is silent today**
```bash
rg -c 'emit\(' src/functualize/_engine/workflow_walker.py
```
now: `0` · after: `≥1`

**Gate — MCP stays verb for verb**
```bash
uv run pytest tests/workflow/test_workflow_surface_parity.py -q
```
now: `passing` · after: `passing`, with `watch_workflow` enumerated

**Test (AC-12):** `watch` on a scope with **no live lease** reports it parked, not running.
This is the assertion that could not be written before F5 —
`app/_workflow_view.py:93-97` says why: *"a resumed walk reports `blocked` for its whole
duration… live-versus-parked needs a lease."*

**Sabotage (risk R-e):** remove the emit calls; `watch` must **stop updating**, not fall back
to polling the store in a loop. **Commit before sabotaging.**

---

## Wave 5 — notify, exactly once

### [ ] T6 · `Notify` on F5's outbox

**Files:** `src/functualize/workflow/__init__.py`,
`src/functualize/_engine/agent_providers.py`,
`tests/integration/test_notify_exactly_once.py`

Spec AC-13, AC-14. An **effect**, so it rides F5's outbox.

`to` is **opaque to the engine**. Providers are named through the table, never imported —
joining the parametrized provider-table test F6 introduced, so a third table extends a list
rather than copying a file.

**Gate — the tables share one test**
```bash
rg -c 'PROVIDERS' tests/gate/test_provider_tables.py
```
now: `file absent` *(F6 creates it)* · after: `≥3` *(strategy, executor, notify)*

**Test (AC-13):** a declared notification fires **exactly once** across a `kill -9` — a real
signal, as F5's parity test 2 does. A unit test can fake exactly-once; a real crash cannot.

> **Not a bus and not a broker** — **N8**. *"The moment `to` becomes load-bearing routing, you
> own a broker."* No retries, no fan-out, no dead-letter queue (risk R-f).

---

## Wave 6 — checkpoint

### [ ] T7 · Feature gate, and the set's last gate

- `uv run ruff check src/ tests/ plugins/`, `ruff format --check`
- `uv run mypy src/`
- `uv run lint-imports`
- `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto`
- `uv run pytest examples/`
- **all six pi-workflows parity tests pass** — 1 and 6 already did; 2 and 3 from F5; 4 from F6;
  5 from this feature
- AC-1…AC-14 each named to a test
- orphan scan over every added symbol
- T5's sabotage, **committing before it**

---

---

## Wave Audit

Read `.spec/AUDIT.md` first — it says what this section is for and how to run it. In short:
an agent that did **not** execute this feature works down the table below, per wave, and
tries to show each claim is false. Running the task's own gate and stopping is not an audit:
the gate was written by whoever wrote the code.

For every wave, do all five:

| # | Check | How |
|---|---|---|
| 1 | **The claim is true** | Run the falsifier in the row. The row says what output means the claim is false. |
| 2 | **The gate can fail** | Make the smallest edit that should break it, confirm the gate turns red, restore. A gate that stays green under that edit is **Blocking**. |
| 3 | **The tests are wired** | Apply the wave's sabotage, confirm the named test fails, restore. **Commit before sabotaging** — `git checkout --` reverts everything uncommitted in the file. |
| 4 | **Scope held** | `git show --stat <commit>` against the wave's `**Files:**` lines. Anything extra must be named in the commit message with a reason. |
| 5 | **The answers** | A wave claiming to be behaviour-free must have changed none. A wave that changes one must name it, and a test must assert the *new* answer with the reason beside it. |

Known hazards on this branch, all observed at least once — check for them specifically:

- **A gate matching its own explanation.** `rg` for a removed literal also matches the comment
  saying why it is gone. Three gates here needed rewording or narrowing for this reason.
- **A gate whose `after:` is unreachable.** One counted docstrings that state the rule the
  task enforces; another counted the authority module the task creates.
- **A test that pins the defect.** Check that a changed assertion moved *toward* the spec, not
  toward whatever the code now does.
- **Scope widened into tests no task owns.** The wave graph guarantees source disjointness
  only; the tests pinned to those sources belong to nobody.

### Per-wave

| Wave | The claim | Falsify it | Sabotage |
|---|---|---|---|
| 0 | *(fill from the wave's task headings: T1)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 1 | *(fill from the wave's task headings: T2)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 2 | *(fill from the wave's task headings: T3)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 3 | *(fill from the wave's task headings: T4)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 4 | *(fill from the wave's task headings: T5)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 5 | *(fill from the wave's task headings: T6)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 6 | *(fill from the wave's task headings: T7)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |

> The middle column is deliberately not pre-filled with the task's own gate. Derive the
> falsifier from the **claim**, then check whether the task's gate asks the same question. If
> it asks a narrower one, that difference is the finding.


## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["T1"]},
    {"id": 1, "tasks": ["T2"]},
    {"id": 2, "tasks": ["T3"]},
    {"id": 3, "tasks": ["T4"]},
    {"id": 4, "tasks": ["T5"]},
    {"id": 5, "tasks": ["T6"]},
    {"id": 6, "tasks": ["T7"]}
  ]
}
```

**Why these boundaries**

- **W0 first and alone.** It is the only breaking change in the feature, and landing it before
  loops exist makes the refusal unambiguous.
- **W1 after W0** — the refusal must exist before the thing that satisfies it, or a bounded
  loop and an unbounded one are indistinguishable during the gap.
- **W2 and W3 are separate waves only because both edit `workflow_walker.py`.** Neither
  depends on the other. When in doubt, serialize.
- **W4 after W3** — `watch` renders outcomes, so the outcome vocabulary must be settled or the
  renderer is written against a moving target.
- **W5 last of the work** — `notify` fires on state transitions, which W2 and W3 change.
- **W6 is a checkpoint** and checkpoints always get their own wave. It is also the **final gate
  of the whole nine-feature set**, which is why it runs the six parity tests rather than this
  feature's alone.

**File-disjointness** is trivial with single-task waves.
`_engine/workflow_walker.py` is touched by T2, T3, T4 and T5 — waves 1, 2, 3 and 4, all
separated. `workflow/__init__.py` by T2, T3 and T6 — waves 1, 2 and 5.
`tests/workflow/test_loops.py` by T1 and T2 — waves 0 and 1.
