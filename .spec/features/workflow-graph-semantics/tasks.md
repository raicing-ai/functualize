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

### [ ] T2 · `Loop`, iteration identity, and the `visited` keying

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
now: `3` *(`:227` declaration, `:237` test, `:238` add)* · after: `≥3`, keyed by node **and**
iteration

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

### [ ] T3 · `OnFailure`, with the recorded-route property

**Files:** `src/functualize/workflow/__init__.py`,
`src/functualize/_engine/workflow_walker.py`,
`tests/workflow/test_failure_routing.py`

Spec AC-5, AC-6, AC-7. Today there is one `except`, one exit
(`workflow_walker.py:336-337` — *"a step failure stops the walk"*).

**Gate**
```bash
rg -c 'a step failure stops the walk' src/functualize/_engine/workflow_walker.py
```
now: `1` · after: `1` — **the comment stays true for the undeclared case**, which is AC-6

**Test (AC-6):** without an `OnFailure`, a raising step stops the walk and marks the scope
`failed` — **unchanged**. Write this first; it is the regression gate.

**Test (AC-7, risk R-c):** a failure predicate is evaluated **exactly once** across a resume.
The route is recorded on first evaluation and **read** on replay — the property
`workflow_walker.py:412-417` already establishes for `ConditionalEdge`, extended rather than
reinvented, because *"calling it and discarding the answer would still run whatever side
effects it has"* and a failure predicate is exactly the kind that pages.

---

## Wave 3 — two more outcomes, and a set instead of a literal

### [ ] T4 · `timed_out`, `cancelled`, and `TERMINAL_SUCCESS`

**Files:** `src/functualize/_engine/frontier.py`,
`src/functualize/_engine/workflow_walker.py`

Spec AC-8, AC-9. Decision **L3** — copy pi-workflows' vocabulary rather than invent a third.

**Gate — the literals today**
```bash
rg -c '"success"|"failed"' src/functualize/_engine/frontier.py
```
now: `2` · after: outcomes drawn from a named set, not compared as literals

**Gate — replay-skip stops matching a string**
```bash
rg -c 'TERMINAL_SUCCESS' src/functualize/_engine/
```
now: `0` · after: `≥2` *(the definition and the replay-skip)*

> A future outcome must not silently become replayable by matching a string comparison nobody
> revisited. That is the whole reason for the named set.

**Test (risk R-d):** `timed_out` is produced **only** by F5's lease expiry. F5's AC-13 grep test
already forbids `SIGALRM`, daemon-thread kills and `asyncio.wait_for` by name; this feature must
not reintroduce them.

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
