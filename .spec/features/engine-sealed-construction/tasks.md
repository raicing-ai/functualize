# Tasks — engine-sealed-construction

Every gate was **run at authoring time** against `e57f0c9`; `now:` is what it returned then.
Run gates from the worktree root.

One gate was narrowed during authoring: `rg -c 'Path\.cwd\(\)'` over `executor.py` returns
**2**, but `:784` is a **docstring** (*"defaults to Path.cwd()"*). The real call is `:1096`
alone. The gate below counts calls, not mentions.

---

## Wave 0 — the port, unused

### [x] T1 · `EngineHost`

**Files:** `src/functualize/_types/protocols.py`

`@runtime_checkable Protocol` per `contracts.md` §1. **Nothing implements or uses it yet** —
this wave is a declaration, and a green suite proves it costs nothing.

Spec AC-1.

**Gate**
```bash
rg -c 'class EngineHost' src/functualize/_types/protocols.py
```
now: `0` · after: `1`

**Gate — Protocol, not ABC (`CONSTITUTION.md` → Ports)**
```bash
rg -n 'class EngineHost' -B2 src/functualize/_types/protocols.py | rg -c 'runtime_checkable'
```
now: `n/a` · after: `1`

---

## Wave 1 — one construction site

### [x] T2 · `build_engine(host)`, called by both boot paths

**Files:** `src/functualize/_app/boot.py`, `tests/app/test_engine_construction.py`

Collapses `boot.py:270-288` and `:482-500` — near-identical, differing only in a config-view
factory, carrying the same twenty-line comment verbatim. The post-hoc writes **stay for now**;
T3 removes them.

Spec AC-2.

**Gate**
```bash
rg -c 'def build_engine' src/functualize/_app/boot.py
```
now: `0` · after: `1`

**Gate — the duplication is gone**
```bash
rg -c 'JobExecutionEngine\(' src/functualize/_app/boot.py
```
now: `2` · after: `1`

---

## Wave 2 — the seal

### [x] T3 · Every post-hoc write and the shared dict die

**Files:** `src/functualize/_app/boot.py`, `src/functualize/app/core.py`,
`src/functualize/_engine/executor.py`, `tests/engine/test_engine_is_sealed.py`

The four writes in `boot.py` (`:286`, `:498`, `:701`, `:1586`), the runtime write in
`core.py:514`, and `add_registry_mirror` (`boot.py:288`, `:500`; `executor.py:232`). `refresh()`
re-resolves **through the host** and writes nothing.

`registered_jobs()` returns a `MappingProxyType` over the registry's map — read-only, no copy
cost. **Measure it here** rather than assuming (risk R-g).

Spec AC-3, AC-4, AC-5.

**Gate — nothing writes into the engine from outside it**
```bash
rg -n 'engine\._[a-z_]+ *=|execution_engine\._[a-z_]+ *=' src/ plugins/ | grep -v '^src/functualize/_engine/'
```
now: `5` *(`boot.py:286,498,701,1586`; `core.py:514`)* · after: `0`

**Gate — the mirror is gone**
```bash
rg -c 'add_registry_mirror' src/functualize/
```
now: `3` *(`boot.py:288`, `boot.py:500`, `executor.py:232`)* · after: `0`

**Test:** an absence assertion in the `test_typer_isolation.py` style — the grep above, as a
test, so a restored write fails the suite rather than being noticed in an audit.
**Sabotage:** restore one write; that test must fail. **Commit before sabotaging.**

---

## Wave 3 — the risk

### [x] T4 · Every `_app` reach-through becomes a host call — **one commit**

**Files:** `src/functualize/_engine/capabilities/runcontext.py`,
`src/functualize/_engine/capabilities/live.py`,
`src/functualize/_engine/capabilities/tty.py`,
`src/functualize/_engine/capabilities/stdout.py`,
`src/functualize/_engine/capabilities/invoke.py`,
`src/functualize/_engine/executor.py`

Twelve reads across six files. Eleven use `getattr(..., "_app", None)`; one is the
unguarded three-hop chain at `runcontext.py:698`.

> **The gate matches code, not prose.** A broader pattern (`rg '_app' _engine/`) returns
> 21 and can never reach `0`: six hits are docstrings that name `_app/boot.py` and
> `_app/impl.py` — including `_engine/__init__.py:8`, which states the very layering rule
> this task enforces — and three are `_apply_prefix` in `capabilities/shell.py`, where
> `_app` is an unrelated substring. Those nine must survive. `surface_routing.py` is named
> in the audit's prose but holds no `_app` read; it is out of this task's file scope.

> **These are load-bearing for live zones** — the TUI's running-job panel resolves through
> `surface_routing.py`. Re-point them **all in one commit**. A half-migrated read set is the
> failure mode, and splitting by file is what would cause it (risk R-a).

Spec AC-7, AC-12.

**Gate**
```bash
rg -n 'getattr\([^,]*, "_app"|\._app\b' src/functualize/_engine/ | wc -l
```
now: `12` · after: `0`

**Verification:** `tests/tui_audit/` — the suite that exists for exactly this surface — plus
the full fast suite.
**Sabotage:** point `host.live_zone()` at `None`; a `tests/tui_audit/` test must fail.

---

## Wave 4 — the kernel stops asking the OS

### [x] T5 · `Path.cwd()` leaves `_engine/`

**Files:** `src/functualize/_engine/executor.py`, `src/functualize/_engine/preflight.py`,
`src/functualize/_engine/capabilities/runcontext.py`,
`tests/app/test_state_root_from_host.py`

Three real call sites: `executor.py:1096`, `preflight.py:116`, `runcontext.py:291`. All read
`host.state_root`.

Spec AC-6.

**Gate (narrowed — see header; excludes the `:784` docstring)**
```bash
rg -n 'Path\.cwd\(\)' src/functualize/_engine/ | grep -v '^\S*:[0-9]*: *#' | grep -v 'defaults to'
```
now: `3` *(`executor.py:1096`, `preflight.py:116`, `runcontext.py:291`)* · after: `0`

**Test:** a run with an explicit root writes its state **there** — the property that makes
F5's durable layer possible, because it needs one answer to "where does run state live".

---

## Wave 5 — workflow walking leaves the engine

### [x] T6 · `WorkflowOrchestrator`

**Files:** `src/functualize/_engine/workflow_orchestrator.py`,
`src/functualize/_engine/executor.py`, `tests/engine/test_lifecycle_order.py`,
`contributor/reference/execution-lifecycle.md`

`_run_workflow_prelude` (`executor.py:1381` at execution time, 154 LOC — the brief said
`:1186`, ~140, which was true when it was written) plus its walker glue, as a sequence of
**pure Move-Method commits** rather than one rewrite.

Spec AC-8, AC-9.

**Two commits, deliberately.** `64f4d9f` moves the body out and leaves
`_run_workflow_prelude` as a delegate; the second deletes the delegate and points
`_execute_lifecycle` at `self._workflow_orchestrator.prelude`. Splitting it means the *move*
is verified against a green lifecycle before the *call site* changes — if something breaks,
only one of the two things could have caused it.

**Gate**
```bash
rg -c 'def _run_workflow_prelude' src/functualize/_engine/executor.py
```
now: `1` · after: `0` *(`rg` exits 1 with no matches, which is the answer)*

**Gate — the lifecycle is untouched, at every commit**
```bash
uv run pytest tests/engine/test_lifecycle_order.py -q
```
now: `passing` · after: `6 passed` — run after **both** commits, not only at the end.

The order list needed one edit in commit 2 and it is not a weakening: the AST scan matches
**call names** inside `_execute_lifecycle`, so `_run_workflow_prelude` became `prelude`.
`contributor/reference/execution-lifecycle.md` step 3 was updated in the same commit, which
the test's own failure message demands — *"update the page and this list together"*.

**Executable size:** `executor.py` 2771 → **2622** LOC; `workflow_orchestrator.py` 209.

**Sabotage:** reorder two lifecycle steps; `test_lifecycle_order.py` must fire. Already wired
— demonstrate once, per `wiring-discipline.md`.

**The eighth instance of hazard #1, in the commit that documents it.** The new module's
docstring explained why its four private reaches are *not* the reach this feature exists to
remove — and named that attribute, which pushed **T4's** gate from `0` to `1`.
`tests/spec/test_task_gates_still_hold.py` caught it on the next run, in a paragraph written
about exactly that failure mode. Reworded without the identifier; T4 reads `0` again.

Demonstrated: `_inject_from_job` moved above `_run_dependencies` (step 10 before step 9).
**4 failed, 2 passed** — the structural check plus three behavioural ones
(`test_a_dep_runs_before_this_jobs_own_freshness_is_decided`,
`test_sources_is_bound_by_the_time_the_body_runs`,
`test_a_fromjob_value_arrives_before_the_body`), the last reporting
`TypeError: downstream() missing 1 required positional argument: 'value'` — a `FromJob` read
before its upstream ran. Reverted; `6 passed`.

---

## Wave 6 — dependency scheduling leaves the engine

### [x] T7 · `DependencyRunner`

**Files:** `src/functualize/_engine/dependency_runner.py`,
`src/functualize/_engine/executor.py`, `tests/engine/test_lifecycle_order.py`,
`contributor/reference/execution-lifecycle.md`

`_run_dependencies` (`executor.py:1803` at execution time, 114 LOC — the brief said `:1741`,
~112) plus its scheduler glue: `_unreusable_upstreams` and `_scope_step_succeeded`, the two
helpers nothing else calls.

**`_declared_dep_names` stayed on the engine.** It is the third helper and it looks like glue,
but `app/core.py:980` calls it as well, so moving it would mean editing an unrelated public
class inside a refactoring commit. **T9** is the task that puts that class on a diet; this one
does not pre-empt it. The runner reaches it through the engine and the module docstring says
why.

**Two commits**, as in T6: `0bac413` moves the bodies and leaves a delegate; the second
deletes the delegate and points `_execute_lifecycle` at `self._dependency_runner.run_for`.

**Gate**
```bash
rg -c 'def _run_dependencies' src/functualize/_engine/executor.py
```
now: `1` · after: `0` *(`rg` exits 1 with no matches)*

**Gate — the lifecycle is untouched** (T6's, re-run here because both waves edit the same
method)
```bash
uv run pytest tests/engine/test_lifecycle_order.py -q
```
now: `passing` · after: `6 passed` — after **both** commits.

Same one edit to `_DOCUMENTED_ORDER` as T6, for the same reason: the AST scan matches call
names, so `_run_dependencies` became `run_for`. `execution-lifecycle.md` step 9 updated in the
same commit.

**Executable size:** `executor.py` 2622 → **2463** LOC; `dependency_runner.py` 199. Across
T6+T7 the file has lost **308 lines**, from 2771.

Separate wave from T6 **only** because both edit `executor.py`. Neither depends on the other.

**What the move broke, and why that is the system working.** Both extractions carry a
`RunStatus` collection — "did this predecessor satisfy its edge?" — which
`tests/types/test_no_second_failure_set.py` allowlists per module. The move turned **both** of
its directions red at once: the two new modules carried an unexplained set, *and*
`_engine/executor.py`'s entry had gone stale. A one-directional allowlist would have caught
only the first and left a permanent excuse behind for a file that no longer needs one. The
exemptions travelled with the code, unchanged in substance.

Also worth recording: the targeted suites run after each commit
(`tests/engine tests/workflow tests/execution tests/spec tests/integration`) did **not**
include `tests/types`, so this surfaced only in the full run. A refactor's blast radius is not
the directory it edits.

---

## Wave 7 — the facades lose weight

### [ ] T8 · `RunContext` diet

**Files:** `src/functualize/_engine/capabilities/runcontext.py`,
`src/functualize/_engine/capabilities/observability_facade.py`,
`src/functualize/_engine/capabilities/discovery_facade.py`

*Additional Facades*. `emit`/`on_event`/`perf_*` → `rc.events`; `get_job_schema`/`list_jobs`
→ `rc.discovery`. The job-author core stays.

**Gate**
```bash
python3 -c "
s=open('src/functualize/_engine/capabilities/runcontext.py').read().splitlines()
st=[i for i,l in enumerate(s,1) if l.startswith('class RunContext:')][0]
print(len(s)-st+1)"
```
now: `788` *(class starts at `:117`; note `:52` is `RunContextMetadata`, a TypedDict)* ·
after: `≤500`

### [ ] T9 · `FunctualizeApp` diet

**Files:** `src/functualize/app/core.py`, `src/functualize/_app/impl.py`

Explain, `execute_parallel` and scope plumbing move to `_app/impl.py`, which exists for this.
`func builtin why`'s second verdict path (`core.py:725-823`) moves **with its tests**
(risk R-c, AC-13).

**Gate**
```bash
python3 -c "
s=open('src/functualize/app/core.py').read().splitlines()
st=[i for i,l in enumerate(s,1) if l.startswith('class FunctualizeApp')][0]
print(len(s)-st+1)"
```
now: `1265` · after: `≤300`

---

## Wave 8 — the constraint acquires a failure mode

### [ ] T10 · The LOC test, and the stale description

**Files:** `tests/test_facade_loc_limits.py`,
`contributor/reference/code-map.md`

Spec AC-10, AC-11. Lands **after** the diets so its first state is green with headroom
(risk R-e), and it **prints the current count** so a breach reads as information.

`code-map.md:31` still says `RunContext` is "~500 LOC" in `job/context.py` — wrong size, wrong
module. Corrected in this commit.

**Gate**
```bash
test -f tests/test_facade_loc_limits.py && uv run pytest tests/test_facade_loc_limits.py -q
```
now: `file absent` · after: `passing`

**Gate — the description is true**
```bash
rg -n '500' contributor/reference/code-map.md | rg -c 'job/context.py'
```
now: `1` · after: `0`

**Sabotage:** append 10 lines to `RunContext`; the LOC test must fail.

---

## Wave 9 — checkpoint

### [ ] T11 · Feature gate

- `uv run ruff check src/ tests/ plugins/`, `ruff format --check`
- `uv run mypy src/`
- `uv run lint-imports` — 6 contracts kept
- `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto`
- `uv run pytest examples/` — the examples are job-authored code and are the real test of the
  `RunContext` diet (risk R-d)
- `tests/perf/test_startup_budget.py` and the `boot_static` < 5 ms test (AC-14)
- `tests/tui_audit/` (AC-12) and `func builtin why`'s tests (AC-13)
- AC-1…AC-14 each named to a test
- orphan scan over every added symbol
- the four sabotages above, **committing before each**

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
| 7 | *(fill from the wave's task headings: T8, T9)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 8 | *(fill from the wave's task headings: T10)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 9 | *(fill from the wave's task headings: T11)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |

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
    {"id": 6, "tasks": ["T7"]},
    {"id": 7, "tasks": ["T8", "T9"]},
    {"id": 8, "tasks": ["T10"]},
    {"id": 9, "tasks": ["T11"]}
  ]
}
```

**Why these boundaries**

Nine of the ten waves hold one task, and the ordering *is* the risk management:

- **W0 → W1 → W2 is a producer chain.** The protocol must exist before a builder can take it;
  the builder must exist before the writes it replaces can be deleted.
- **W3 is the dangerous one, and it sits in the middle deliberately** — after the seal, so the
  host is already proven; before the extractions, so they do not have to move code that is
  still reading through `_app`. It is one task across seven files **on purpose**: splitting it
  by file is the failure mode.
- **W5 and W6 are separate waves only because both edit `executor.py`.** Neither depends on
  the other. When in doubt, serialize.
- **W7's two tasks touch disjoint files** — `runcontext.py` plus two new facades, versus
  `app/core.py` plus `_app/impl.py`.
- **W8 after W7**, so the LOC test's first state is green rather than red.
- **W9 is a checkpoint** and checkpoints always get their own wave.

**File-disjointness within each wave**

| Wave | Tasks | Files |
|---|---|---|
| 7 | T8 / T9 | `capabilities/runcontext.py` + 2 new facades / `app/core.py` + `_app/impl.py` |

`_engine/executor.py` is touched by T3, T4, T5, T6 and T7 — all five are alone in their waves.
`_app/boot.py` is touched by T2 and T3, waves 1 and 2. `capabilities/runcontext.py` is touched
by T4, T5 and T8, waves 3, 4 and 7.
