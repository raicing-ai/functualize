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

**Sabotage:** 12 edits, `sabotage-t4.py`. All 12 bite.

**Measured:** 10,630 passed on the fast suite; `ruff`, `mypy` (352 files),
`lint-imports` (7 contracts) clean.

---

## Wave 4 — the walker speaks, and something listens

### [x] T5 · Emit step-level events, and `watch`

**Files:** `src/functualize/_engine/workflow_walker.py`,
`src/functualize/_cli/builtins.py`,
`plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`,
`tests/workflow/test_watch_stream.py`,
plus the transport this needed and the file list did not name *(deviation, below)*:
`src/functualize/_events/walk_log.py` (new),
`src/functualize/_primitives/scope_store.py`,
`src/functualize/_primitives/scope_format.py`,
`src/functualize/app/_workflow_view.py`,
`src/functualize/_engine/{workflow_runner,workflow_orchestrator}.py`,
`src/functualize/_app/boot.py`

Spec AC-10, AC-11, AC-12. pi-workflows parity test **5**.

**Deviation: emitting was the small half.** The task named the walker and the two
surfaces, which is where the *visible* work is. What it did not name is that
nothing could carry an event from one to the other. `RunLogSubscriber` **buffers
a run's events and writes them once, when the run ends** — correct for its job,
and exactly wrong for watching: a log flushed at the end arrives too late for
anybody following a walk that is still going, so a watcher would see nothing and
then everything. Live and buffered are incompatible, so this is a second
subscriber (`_events/walk_log.py`) writing **through**, onto the **scope** rather
than the run because a scope is advanced by several runs across a resume.
`durable-run-layer`'s AC-5 is honoured rather than worked around: `bus.py` gains
no file I/O, the walker does no writing, persistence stays a subscriber.

**Gate — the walker is silent today**
```bash
rg -c 'emit\(' src/functualize/_engine/workflow_walker.py
```
now: `0` · after: `1`. One call, in `_say`, which is the point: every emit site
goes through one guard, so "nobody is watching" is answered once.

**Gate — and it is called from more than one place**
```bash
rg -c '_say\(' src/functualize/_engine/workflow_walker.py
```
now: `0` · after: `6`. The definition and five sites — the walk's start and end,
a node's start, and a node's end on both the ordinary and the stopped path. The
first gate alone would be satisfied by a `_say` nothing called.

**Gate — MCP stays verb for verb**
```bash
uv run pytest tests/workflow/test_workflow_surface_parity.py -q
```
now: `passing` · after: `passing`, with `watch_workflow` enumerated. That test
reads both surfaces live, so adding the CLI verb alone fails it; `watch` →
`watch_workflow` is registered in `VERB_TO_TOOL`, and `--timeout` is recorded in
`SURFACE_ONLY` with its reason — a terminal can hold a line open and a tool call
returns, so the tool pages with `limit` and `next` instead.

**Test (AC-12):** `watch` on a scope with **no live lease** reports it parked, not running.
This is the assertion that could not be written before F5 —
`app/_workflow_view.py:93-97` says why: *"a resumed walk reports `blocked` for its whole
duration… live-versus-parked needs a lease."* `walk_is_live` is that sentence
answered, and it is **stricter than `_lease_has_lapsed`** on purpose: that helper
reads an absent lease as "not abandoned", which is right for it; here an absent
lease means nobody is walking this, and a watcher that waited on one would wait
for ever. Without it, `watch` on a workflow that finished an hour ago prints its
history and hangs — a released lease is *expired in place*, so every finished
scope looks exactly like an abandoned one.

**AC-11, stated exactly.** *"The walker emits step-level events"* — yes,
and `watch_scope` yields only what was emitted; nothing compares two readings of
the record and infers a transition, which is the shape that cannot tell a step
that **ran** from one that was **replayed**, misses anything that starts and
finishes inside one read, and on a loop cannot tell the second pass from the
first. Three properties a diff cannot supply, each with a test.

*"nothing polls the store in a loop to render"* — the renderer does not, and the
transport does: `watch_scope` asks for "everything after seq N" on an interval.
There is no blocking read over a document substrate and there must not be one
over a substrate that is a table or an object store. Recorded as a deviation
rather than claimed as satisfied: what survives is the half the risk is about,
and the sabotage is what proves it survived.

**The test that would fail if none of this were connected.** Every unit test
here hands `bus.emit` to the walker and installs the subscriber by hand, so all
of them pass with the *engine* wired to nothing — the walker emitting into a bus
the application never built. `TestTheWiringIsReal` runs a real `@workflow`
through `app.execute` and then types the command. Verified by cutting
`emit=self._engine._event_bus.emit` to `None`: 2 failed, 19 passed.

**Sabotage (risk R-e):** 12 edits, `sabotage-t5.py`. Includes the one the risk
names — `watch` falling back to describing the record when the log is empty —
and all 12 bite. **Commit before sabotaging.**

---

## Wave 5 — notify, exactly once

### [x] T6 · `Notify` on F5's outbox

**Files:** `src/functualize/workflow/{__init__,_decorator,_validation}.py`,
`src/functualize/_types/{workflow,protocols,errors}.py`,
`src/functualize/_engine/notify_providers.py` (new) *(deviation, below)*,
`src/functualize/_engine/notify.py` (new),
`src/functualize/_engine/{workflow_walker,workflow_runner,workflow_orchestrator,executor}.py`,
`src/functualize/_app/{boot,impl,extensions_facade}.py`, `src/functualize/app/core.py`,
`tests/workflow/test_notify.py` (new),
`tests/integration/test_notify_exactly_once.py` (new)

Spec AC-13, AC-14. An **effect**, so it rides F5's outbox.

`to` is **opaque to the engine**. Providers are named through the table, never imported —
joining the parametrized provider-table test F6 introduced, so a third table extends a list
rather than copying a file.

**Deviation: the table got its own module.** The plan put `NOTIFY_PROVIDERS` in
`_engine/agent_providers.py`. An executor runs a step and a notifier delivers an
effect; they share a *shape*, not a subject, and a table about notifications
inside a file whose docstring is entirely about agent executors is one nobody
looking for it would find. It costs nothing: `test_provider_tables.py`
**discovers** tables by scanning `src/` and refuses any that has not joined its
list, so a third module inherits every check with a four-line entry — which is
the property that file's opening paragraph was written to defend, exercised
here for the first time.

**Gate — the tables share one test**
```bash
rg -c 'PROVIDERS' tests/gate/test_provider_tables.py
```
recorded `now: file absent · after: ≥3`, and **superseded**: it counts every
line that mentions the word, prose included — it was `11` before this task and
is `12` after, which is one sentence, not one table. The same shape that moved
`durable-run-layer`/T6 and T8 on this branch.

Replaced with a count of the entries themselves:
```bash
rg -c 'table="[A-Z_]+_PROVIDERS"' tests/gate/test_provider_tables.py
```
now: `2` · after: `3` — strategy, executor, notify. It counts the field the
parametrization reads, so a table described in a comment does not satisfy it,
and `test_every_provider_table_in_src_is_listed_here` independently fails if a
fourth table appears in `src/` without joining.

**Test (AC-13):** a declared notification fires **exactly once** across a `kill -9` — a real
signal, as F5's parity test 2 does. A unit test can fake exactly-once; a real crash cannot.
Done: the first runner blocks at a gate, delivers, and hangs **inside the
notifier**; it is SIGKILLed; the resumed walk replays to the same gate, reaches
the same `blocked` status, and stays quiet. The evidence is a file the notifier
appends to, so the count is deliveries and not bookkeeping. Verified to bite —
with the "already recorded" check removed the log reads `blocked\nblocked\n`.

Two guards beside it, because "notified once" is also true of a resumed runner
that crashed on startup or never reached the gate: one asserts the resumed scope
really is `blocked` at `approval`, and one asserts a fresh scope *is* notified.

**The outbox rule, and the direction it fails in.** The record that a
notification fired is committed **before** the provider is called, so a crash
inside a delivery loses one and can never repeat one. Asymmetric on purpose: a
resumed workflow must not page the on-call again for a failure they have already
seen. Recorded in the scope's **branch** store, where `OnFailure` already keeps
its chosen route (T3) — one place a resume reads one kind of fact, *this scope
decided this once*, rather than a second store to keep in agreement. Keyed by
the declaration's content, not its index, so adding a second `Notify` cannot
make the first fire again.

**Nothing is registered by default.** Core ships `LogNotifier` and registers it
nowhere — `_app.boot`'s decision for the `cli-prompt` executor, made again: a
default registration makes the refusal unreachable, and a workflow whose "page
the on-call on failure" quietly became a debug line is worse than one that
refuses to start. `NotifierRegistry.check` runs in `WorkflowRunner.prelude`,
before the walk, so a declaration nobody can deliver fails when nothing has
happened yet.

**`FunctualizeApp`'s facade budget 302 → 303**, for `_notifier_registry`, with
the reason and the two rejected cheaper answers in `tests/test_facade_loc_limits.py`.

> **Not a bus and not a broker** — **N8**. *"The moment `to` becomes load-bearing routing, you
> own a broker."* No retries, no fan-out, no dead-letter queue (risk R-f).
> `TestToIsOpaque` is what keeps them out: six declared targets — an address, a
> channel, a URL with a query string, a comma-separated list, a template-looking
> string, one with padding — each arrives byte for byte, and `"a,b"` is **one**
> target. There is nowhere for a routing rule to attach itself without that
> failing first.

**Sabotage:** 12 edits, `sabotage-t6.py`. All 12 bite, the crash test included.

**A sweep fix that belongs here.** The T4 and T5 scripts now run pytest in its
own process group and `killpg` it on timeout. `subprocess.run`'s timeout kills
the direct child, which is `uv`; pytest is its **grandchild** and survived — three
T5 sweeps left hung runs eating the machine for twenty minutes each, and the
next suite run took 3:37 instead of 2:32 because of them.

---

## Wave 6 — checkpoint

### [x] T7 · Feature gate, and the set's last gate

- [x] `uv run ruff check src/ tests/ plugins/ examples/`, `ruff format --check` —
      clean, 1,426 files
- [x] `uv run mypy src/` — **355 files**, no issues
- [x] `uv run lint-imports` — **7 kept, 0 broken**
- [x] `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto` — **12,142 passed,
      155 skipped**. Found a latent flake; see below
- [x] `FUNCTUALIZE_TEST_SUBSTRATE=sqlite` — **10,630 passed, 0 failed**
- [x] all 12 plugin suites, one package at a time — green, 426 tests
- [x] `uv run pytest examples/` — **204 passed**, from **2 collection errors and
      4 failures**. This is the item that earned its place; see below
- [x] all six pi-workflows parity tests pass — run together, 75 passed:
      **1** `tests/integration/test_mcp_workflow_loop_e2e.py` (already, 0.3.0) ·
      **2** `tests/integration/test_crash_and_resume.py` (F5) ·
      **3** `tests/workflow/test_source_identity.py` (F5) ·
      **4** `tests/workflow/test_agent_step_refusals.py` (F6) ·
      **5** `tests/workflow/test_watch_stream.py` (this feature) ·
      **6** `tests/test_state_split_regression.py` (already, `24c5cc0`)
- [x] AC-1…AC-14 each named to a test — every one appears in **this feature's own**
      test files, not merely somewhere under `tests/`; see below
- [x] orphan scan over all 58 added symbols — one genuine finding, fixed
- [x] sabotages: T4's 12, T5's 12, T6's 12. All 36 bite. Committed before each

## `pytest examples/` is why a gate runs commands nobody runs per task

It found **six breaks, none of them this feature's**, all from
`store-substrate` — which assessed a blast radius of five plugins and did not
look at `examples/` or `docs/`:

- `examples/plugins/custom_state_backend` implemented `StateBackend`, a protocol
  T5/T6 deleted, and failed at **collection**. Ported to a `StoreSubstrate` —
  a better example than the one it replaces, because "bring your own storage"
  is exactly what the substrate seam had no worked example of.
- `examples/standalone/showcase` imported `InMemoryState`. It is now a dict, and
  nothing was lost: the example never demonstrated cross-process state.
- `examples/quickstart/step7_workflow` called three `FreshStore` methods that
  went with T3's 33 forwarders.
- README, `docs/guides/domain-sdks.md`, `docs/guides/plugins.md`,
  `docs/contributing.md` and four more pages described a package that no longer
  exists.
- Two example lockfiles pinned an editable path into the deleted directory.

`durable-run-layer`/T13 recorded the same lesson about `lint-imports` — *"a check
that only runs at a feature boundary will always find things late"* — and this is
the second instance. `pytest examples/` and `lint-imports` belong in the per-task
loop; `ruff + mypy + pytest tests/` is not the set.

## The AC map, and why "it appears in tests/" was not good enough

`rg -c "AC-n" tests/` returns 7–19 hits for every n, because nine features'
specs all number from 1. Scoped to this feature's own files the map is:

| AC | Test file |
|---|---|
| 1, 2 | `test_loops.py::TestTheIterationKeyingIsRightBothWays` (one body — both failure modes are silent) |
| 3, 4 | `test_loops.py` |
| 5, 6, 7 | `test_failure_routing.py` |
| 8, 9 | `test_typed_step_outcomes.py` |
| 10, 11, 12 | `test_watch_stream.py` |
| 13 | `test_notify.py` **and** `test_notify_exactly_once.py` (the crash half) |
| 14 | `test_notify.py::TestToIsOpaque` |

AC-1 and AC-2 were **unlabelled** until this gate — the tests existed and the
file said "Spec AC-3". Labelled now, which is the difference between a map and a
claim.

## The orphan scan found one thing, and it was real

58 symbols added across T1–T6. Twenty had no production caller outside their own
file; nineteen are module-private helpers called within their module, which is
what a private helper is.

The twentieth: **`LogNotifier` was unreachable.** Core "ships a notifier and
registers none" so that a user can leave that state without installing a
package — and the only import path was `functualize._engine.notify`. The claim
in its own docstring was false. Re-exported through `app/utils.py`, the corridor
`_cli` and plugins already use.

**Recorded, not fixed:** `Stored` and `StoreSubstrate` have no public re-export
at all, so `functualize-state-sqlite` and the ported example both import them
from `_types.protocols`. A port a plugin cannot reach publicly is a gap in
`store-substrate`; the example matches the shipped plugin rather than inventing
a third way.

## A flake the sweep surfaced

`tests/test_schema_extractor_properties.py` failed once in two `--run-slow` runs
with `ValueError: invalid enum member name(s) 'mro'`. The generator draws
lowercase identifiers, `mro` is a legal draw, and `EnumType` refuses it at class
construction — so the test failed for a reason that is about `enum`, not about
schema extraction. Filtered in `_make_enum` rather than by narrowing a regex
every other property in the file shares.

## Gates that moved, and why each was replaced rather than adjusted

Four recorded gates drifted while this feature ran, and **three of them were
moved by prose**:

| Gate | Was | Now | Cause |
|---|---|---|---|
| `durable-run-layer`/T6 | `rg -c 'generation' frontier.py` = 13 | `self\._generation|generation=` = 7 | a rename, then T4's docstrings |
| `durable-run-layer`/T8 | `rg -c 'abandoned' _workflow_view.py` = 4 | the derivation = 3 | T5's `walk_is_live` had to say how it differs |
| `workflow-graph-semantics`/T4 | `'"success"|"failed"'` in frontier = 2 | `== "success"` in `_engine/` = 0 | the recorded gate's correct *direction* was unknowable |
| `workflow-graph-semantics`/T6 | `rg -c 'PROVIDERS'` in the test = ≥3 | `table="..._PROVIDERS"` = 3 | counts the word, 11 → 12 for one sentence |

`agent-step-port`/T2's is the fifth and the exception: it counts every provider
table in `src/` and moved 2 → 3 because T6 added one. That gate is **working** —
the count is what made the addition visible — so its `after:` was updated with
the reason rather than the gate replaced.

> The pattern is one hazard, seen five times on one branch: **a gate that counts
> a word counts the explanation too.** Every replacement above counts the
> mechanism instead — a call, an assignment, a field the parametrization reads —
> and none of them can be satisfied by writing about it.

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
