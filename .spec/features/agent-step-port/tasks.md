# Tasks — agent-step-port

Every gate was **run at authoring time** against `e57f0c9`; `now:` is what it returned then.
Run gates from the worktree root.

---

## Wave 0 — the port

### [x] T1 · `AgentStepExecutor`, `AgentCapability`, and two errors

**Files:** `src/functualize/_types/protocols.py`, `src/functualize/_types/errors.py`,
`src/functualize/plugin/__init__.py`

`@runtime_checkable Protocol` per `contracts.md` §1 — never an ABC
(`CONSTITUTION.md` → *Ports*). Nothing implements it yet.

Spec AC-1.

**Gate**
```bash
rg -c 'class AgentStepExecutor' src/functualize/_types/protocols.py
```
now: `0` · after: `1`

**Gate — Protocol, not ABC**
```bash
rg -n 'class AgentStepExecutor' -B2 src/functualize/_types/protocols.py | rg -c 'runtime_checkable'
```
now: `n/a` · after: `1`

---

## Wave 1 — the table, and one test for every table

### [x] T2 · `EXECUTOR_PROVIDERS`, `CORE_EXECUTORS`, and a shared provider-table test

**Files:** `src/functualize/_engine/agent_providers.py`, `tests/gate/test_provider_tables.py`

Spec AC-8, AC-9. Copied from `_gate/_strategy.py:40-66`, **including `CORE_*`** — the hint
returns an empty string for a core name, because *"if `resolve` is unregistered the answer is
not 'install something', it is that the registry was built by hand."*

The existing grep test (`tests/gate/test_registry.py:298-306`) becomes **parametrized over both
tables**, so a third table joins a list rather than copying a file (risk R-e, `pitfalls.md` §6).

**Gate — there is exactly one such table today**
```bash
rg -n '^[A-Z_]+_PROVIDERS' src/functualize/ | wc -l
```
now: `1` *(`_gate/_strategy.py:40`)* · after: `2`

**Gate — core still imports no plugin**
```bash
grep -rn -E 'import functualize_(ai|mcp)' src/ | wc -l
```
now: `0` · after: `0`

---

## Wave 2 — the declaration refuses before the walk

### [x] T3 · `AgentStep`, `_NODE_TYPES`, and the validation refusals

**Files:** `src/functualize/workflow/__init__.py`,
`src/functualize/workflow/_validation.py`,
`tests/workflow/test_agent_step_refusals.py`

Spec AC-3, AC-4, AC-5, AC-6, AC-7. `tools=[…]` implies
`requires={ENFORCES_TOOL_ALLOWLIST}` — widenable explicitly, never narrowed implicitly.

**Gate**
```bash
rg -n '_NODE_TYPES = ' src/functualize/workflow/_validation.py
```
now: `28: _NODE_TYPES = (Step, Gate)` · after: `(Step, Gate, AgentStep)`

**Test (AC-5, risk R-b):** a step needing `ENFORCES_TOOL_ALLOWLIST` against an executor without
it refuses **at validation**, with **zero** step records written. Refusing halfway through a
walk is worse than not starting — side effects have already happened.
**Test (AC-7):** no registered executor → refusal naming the package from
`EXECUTOR_PROVIDERS`, and **no** fallback to prompting a human.

---

## Wave 3 — the walker stops type-testing

### [x] T4 · Open the node dispatch

**Files:** `src/functualize/_engine/workflow_walker.py`,
`src/functualize/_engine/agent_step.py`

Spec AC-10. Today kind is `isinstance(node, Gate)` at `:261` and again at `:313`.

> **Change the dispatch and nothing else in the loop** (risk R-a). The `visited` set, join
> readiness (`_ready`), the deferral counter and the replay-skip all stay exactly as they are —
> they are load-bearing for diamond joins and for resume, and F7 depends on their current
> behaviour being understood.

**Gate**
```bash
rg -c 'isinstance\(node, ' src/functualize/_engine/workflow_walker.py
```
now: `≥1` *(`:261`)* · after: `0`

**Gate — the walk's own mechanics are untouched**
```bash
rg -c 'visited' src/functualize/_engine/workflow_walker.py
```
now: `3` · after: `3`

**Verification:** the existing workflow suites, plus
`uv run pytest tests/engine/test_lifecycle_order.py -q`.

---

## Wave 4 — something implements it

### [x] T5 · The core `cli-prompt` executor, and registration

**Files:** `src/functualize/_engine/agent_step.py`, `src/functualize/_app/impl.py`,
`tests/workflow/test_agent_step_walk.py`

Spec AC-2, AC-11. Registered by an app method — **nothing auto-discovered**
(`GateResolver`'s shape).

`cli-prompt` asks a human and declares **no** capabilities, which makes it the fixture for
every refusal path in T3 as well as the proof the port is wired (risk R-f).

**Gate**
```bash
rg -c 'def register_agent_step_executor' src/functualize/_app/impl.py
```
now: `0` · after: `1`

**Gate — a forgotten declaration is a startup failure (AC-11)**
```bash
rg -c 'def _check_name_agreement' src/functualize/_engine/capabilities/registry.py
```
now: `1` · after: `1`, extended to cover executor capability names

**Sabotage:** delete the registration call; the walk test must fail with
`AgentExecutorUnavailableError`, **not** with a human prompt. **Commit before sabotaging.**

---

## Wave 5 — the parity test

### [x] T6 · A protected gate refuses an agent — parity test 4

**Files:** `tests/workflow/test_agent_step_refusals.py`

Spec AC-12. From the pi-workflows roadmap's six parity tests: *a gate marked protected cannot
be answered by the agent even though the agent answered the previous checkpoint.*

The interesting half is "even though" — the agent's authority is per-gate, not per-scope, so a
test that only checks the refusal in isolation does not test the property.

---

## Wave 6 — checkpoint

### [x] T7 · Feature gate

- `uv run ruff check src/ tests/`, `ruff format --check`
- `uv run mypy src/`
- `uv run lint-imports`
- `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto`
- `uv run pytest examples/`
- `grep -rn -E 'import functualize_(ai|mcp)' src/` is empty (AC-9)
- AC-1…AC-12 each named to a test
- orphan scan over every added symbol
- T4's sabotage, **committing before it**

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

- **W0 → W1 → W2** is a producer chain: the Protocol before the table that names its
  implementations, and both before the declaration that refuses against them.
- **W2 before W3, and this is the one that matters.** The refusals must exist before a node
  kind can reach the walk, so **there is never a commit where an agent step runs unchecked**.
  The reverse order would ship, however briefly, the exact silent-degradation this feature
  exists to prevent.
- **W3 before W4** — the dispatch must accept the kind before an executor can service it.
- **W5 after W4** — parity test 4 needs a registered executor to be refused.
- **W6 is a checkpoint** and checkpoints always get their own wave.

**File-disjointness** is trivial with single-task waves.
`src/functualize/_engine/agent_step.py` is touched by T4 and T5 (waves 3 and 4);
`tests/workflow/test_agent_step_refusals.py` by T3 and T6 (waves 2 and 5). Both separated.
