# Tasks — engine-sealed-construction

Every gate was **run at authoring time** against `e57f0c9`; `now:` is what it returned then.
Run gates from the worktree root.

One gate was narrowed during authoring: `rg -c 'Path\.cwd\(\)'` over `executor.py` returns
**2**, but `:784` is a **docstring** (*"defaults to Path.cwd()"*). The real call is `:1096`
alone. The gate below counts calls, not mentions.

---

## Wave 0 — the port, unused

### [ ] T1 · `EngineHost`

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

### [ ] T2 · `build_engine(host)`, called by both boot paths

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

### [ ] T3 · Every post-hoc write and the shared dict die

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

### [ ] T4 · Every `_app` reach-through becomes a host call — **one commit**

**Files:** `src/functualize/_engine/capabilities/runcontext.py`,
`src/functualize/_engine/surface_routing.py`,
`src/functualize/_engine/capabilities/live.py`,
`src/functualize/_engine/capabilities/tty.py`,
`src/functualize/_engine/capabilities/stdout.py`,
`src/functualize/_engine/capabilities/invoke.py`,
`src/functualize/_engine/executor.py`

Fourteen reads. Thirteen use `getattr(..., "_app", None)`; one is the unguarded three-hop
chain at `runcontext.py:698`.

> **These are load-bearing for live zones** — the TUI's running-job panel resolves through
> `surface_routing.py`. Re-point them **all in one commit**. A half-migrated read set is the
> failure mode, and splitting by file is what would cause it (risk R-a).

Spec AC-7, AC-12.

**Gate**
```bash
rg -n '_app' src/functualize/_engine/ | grep -v 'host' | wc -l
```
now: `14` · after: `0`

**Verification:** `tests/tui_audit/` — the suite that exists for exactly this surface — plus
the full fast suite.
**Sabotage:** point `host.live_zone()` at `None`; a `tests/tui_audit/` test must fail.

---

## Wave 4 — the kernel stops asking the OS

### [ ] T5 · `Path.cwd()` leaves `_engine/`

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

### [ ] T6 · `WorkflowOrchestrator`

**Files:** `src/functualize/_engine/workflow_orchestrator.py`,
`src/functualize/_engine/executor.py`

`_run_workflow_prelude` (`executor.py:1186`, ~140 LOC) plus its walker glue, as a sequence of
**pure Move-Method commits** rather than one rewrite.

Spec AC-8, AC-9.

**Gate**
```bash
rg -c 'def _run_workflow_prelude' src/functualize/_engine/executor.py
```
now: `1` · after: `0`

**Gate — the lifecycle is untouched, at every commit**
```bash
uv run pytest tests/engine/test_lifecycle_order.py -q
```
now: `passing` · after: `passing` *(run after **each** commit in this wave, not only at its end)*

**Sabotage:** reorder two lifecycle steps; `test_lifecycle_order.py` must fire. Already wired
— demonstrate once, per `wiring-discipline.md`.

---

## Wave 6 — dependency scheduling leaves the engine

### [ ] T7 · `DependencyRunner`

**Files:** `src/functualize/_engine/dependency_runner.py`,
`src/functualize/_engine/executor.py`

`_run_dependencies` (`executor.py:1741`, ~112 LOC) plus its scheduler glue.

**Gate**
```bash
rg -c 'def _run_dependencies' src/functualize/_engine/executor.py
```
now: `1` · after: `0`

Separate wave from T6 **only** because both edit `executor.py`. Neither depends on the other.

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
now: `782` *(class starts at `:117`; note `:52` is `RunContextMetadata`, a TypedDict)* ·
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
