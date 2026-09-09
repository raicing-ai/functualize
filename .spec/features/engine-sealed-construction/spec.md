# Feature — engine-sealed-construction

Implements **F3** of `contributor/architecture/run-model/13-roadmap.md`: the audit's steps 3,
6 and 7 — the engine becomes complete at construction, small enough to read, and its size
limits become tests.

**Depends on:** `run-request-entry` (F1), `run-outcome-authority` (F2).
**Blocks:** `surface-request-parity` (F4), `durable-run-layer` (F5).

This is the **highest-risk feature in the set**. §7 says why, and what defends it.

---

## 1. The problem

### 1.1 The engine is finished by its owners, after it is built

Five post-hoc private writes, re-verified at `e57f0c9`:

```
_app/boot.py:286    app._execution_engine._app = app
_app/boot.py:498    app._execution_engine._app = app
_app/boot.py:701    app._execution_engine._resolution_chain = app._resolution_chain
_app/boot.py:1586   app._execution_engine._max_invoke_depth = depth
app/core.py:514     engine._resolution_chain = self._resolution_chain
```

Plus a **shared mutable dictionary** handed across the boundary at `boot.py:288` and `:500`:
`add_registry_mirror(app.job_registry._registered_jobs)` passes the registry's **private** map
by reference (`executor.py:232`), so two objects share mutable state with no contract between
them.

Two of these matter beyond their number:

- `boot.py:286` and `:498` are the **same write in two boot paths** — `boot_static` and
  `boot_standard`. So are `:288` and `:500`. The construction blocks at `boot.py:270-288` and
  `:482-500` are near-identical, differ only in a config-view factory, and carry the same
  twenty-line comment verbatim. **The next engine parameter must be added twice, correctly, by
  whoever notices there are two.**
- `core.py:514` fires on `refresh()` — **at runtime**, not at boot. The engine's config
  dependency is a writable field that can change under a run.

The `REGISTRY_FROZEN → APP_READY` boot contract covers the DI registry. **Nothing freezes the
engine.**

### 1.2 And read back through the app it was handed

`_app` is written twice and read at fourteen sites. One is unguarded:

```python
# _engine/capabilities/runcontext.py:698
return self._execution_engine._app.job_registry.get_descriptor(job_name)
```

Three hops from the kernel into the app's registry. The other thirteen use
`getattr(..., "_app", None)` — the codebase admitting the attribute may not be there.

> The message chain is not laziness. `RunContext` has no sanctioned route to a descriptor,
> so the readable path does not exist.

### 1.3 The kernel wires itself from the process

Three real sites (a fourth match, `executor.py:784`, is a docstring):

| Site | Code |
|---|---|
| `_engine/executor.py:1096` | `self._workflow_state_store = StateStore.for_project(Path.cwd())` |
| `_engine/preflight.py:116` | `self._root = Path(root) if root is not None else Path.cwd()` |
| `_engine/capabilities/runcontext.py:291` | `return self._cwd if self._cwd is not None else Path.cwd()` |

They matter together rather than apart: a run whose `RunRequest` carries `cwd` can still land
its state file somewhere else, because `executor.py:1096` does not consult the request. The
later two take a `None` default and are one argument from correct; the first takes none.

**This is also why the durable run layer cannot simply be added** — it needs one answer to
*"where does this project's run state live?"*, and today three places answer, one differently.

### 1.4 The engine holds four subsystems

`JobExecutionEngine` is **2,401 LOC across 55 methods** and holds execution *and* workflow
walking (`_run_workflow_prelude`, `executor.py:1186`, ~140 LOC) *and* dependency scheduling
(`_run_dependencies`, `:1741`, ~112 LOC) *and* shell/sudo/redaction resolution *and* history.

### 1.5 The budgets are prose, breached, and unenforced

| Class | Constraint | Measured |
|---|---|---|
| `RunContext` (`runcontext.py:117-898`) | ≤ 500 LOC facade | **782** |
| `FunctualizeApp` (`app/core.py:64-1328`) | ≤ 300 LOC facade | **1,265** |
| `JobExecutionEngine` (`executor.py:157-2557`) | decompose above ~500 | **2,401** |

`contributor/reference/code-map.md:31` still calls `RunContext` "~500 LOC" and places it in
`job/context.py` — a stale description of a breached constraint, and `tests/test_facade_loc_limits.py`
does not exist.

The overflow is **breadth, not depth**: `RunContext` is 58 one-line delegations re-exposing
five subsystems. A facade that outgrows its budget has stopped being a facade.

---

## 2. User stories

- **US-1** As a maintainer adding an engine dependency, I add it to one protocol and one
  builder — not to two near-identical construction blocks I have to notice are two.
- **US-2** As a maintainer, `grep` tells me nothing writes into the engine from outside it,
  and a test fails if that stops being true.
- **US-3** As someone running a job with an explicit working directory, its state lands there.
- **US-4** As a maintainer, a facade that outgrows its budget fails the suite, rather than
  being noticed in an audit eighteen months later.
- **US-5** As a reader of `executor.py`, the file is about executing a job.

---

## 3. Behaviour

### 3.1 The engine is complete at construction

An `EngineHost` protocol declares everything the engine needs from outside, wired once by a
single `build_engine(host)`. Every post-hoc private write is deleted. `refresh()` re-resolves
**through** the host rather than writing into the engine.

> **There is no supported way to modify an engine after it is built.** That is the point: the
> "open for modification" complaint becomes structurally false for this axis.

### 3.2 One construction site

`boot_static` and `boot_standard` call the same builder. The duplicated blocks and their
duplicated comment collapse to one.

### 3.3 The host answers "where"

All three `Path.cwd()` sites read the host's state root. The kernel stops asking the operating
system a question its host already knows.

### 3.4 The engine keeps execution, and only execution

`WorkflowOrchestrator` and `DependencyRunner` come out as engine-owned collaborators
constructed from the host — **not** as peers, not as a new layer, not as a registry.

> **`_execute_lifecycle`'s 20-step order does not change.**
> `tests/engine/test_lifecycle_order.py` is green at **every commit** of this feature. That
> test AST-walks the method and checks the call order against
> `contributor/reference/execution-lifecycle.md`; its staying green is the proof each move was
> pure, and the reason the moves are possible at all.

### 3.5 The budgets become tests

`RunContext` keeps the job-author core — name, config, log, invoke, prompt, status/phases,
state. The observability re-exposures (`emit`, `on_event`, `perf_*`) and discovery
re-exposures (`get_job_schema`, `list_jobs`) move to focused facades — ch14's own named remedy,
*Additional Facades*. `FunctualizeApp`'s explain, `execute_parallel` and scope plumbing move to
`_app/impl.py`, which exists for exactly this.

Then a test asserts both numbers, and `code-map.md:31` is corrected in the same commit.

> The point is not the number. It is that the constraint acquires a **failure mode**.

### 3.6 What must not change

- The lifecycle's step order, at every commit.
- Live zones. The `_app` reads in `runcontext.py` and `_engine/surface_routing.py` are
  load-bearing for them; `tests/tui_audit/` stays green.
- `func builtin why`'s second verdict path (`app/core.py:725-823`) must not be orphaned by the
  Extract Class work.
- Boot timings. `boot_static` stays under 5 ms; collapsing two construction blocks into one
  adds no boot work.

---

## 4. Acceptance criteria

- **AC-1** `EngineHost` exists as a `@runtime_checkable Protocol` in `_types/protocols.py`.
  No ABC.
- **AC-2** One `build_engine(host)` constructs the engine; `boot_static` and `boot_standard`
  both call it.
- **AC-3** `rg 'engine\._[a-z_]+ *=|execution_engine\._[a-z_]+ *='` over `src/` and `plugins/`
  returns **zero** hits outside `_engine/`. Asserted by a test, `test_typer_isolation.py`
  style — an absence assertion, not a review note.
- **AC-4** `add_registry_mirror` no longer receives the registry's private map; the host
  exposes a lookup.
- **AC-5** `refresh()` re-resolves through a host method and writes no engine attribute.
- **AC-6** No `Path.cwd()` call remains in `src/functualize/_engine/`. A run with an explicit
  root writes its state there.
- **AC-7** `runcontext.py:698`'s three-hop chain is replaced by one host call.
- **AC-8** `WorkflowOrchestrator` and `DependencyRunner` exist as engine-owned collaborators;
  `executor.py` no longer defines `_run_workflow_prelude` or `_run_dependencies`.
- **AC-9** `tests/engine/test_lifecycle_order.py` passes at **every commit** of this feature.
- **AC-10** `RunContext` ≤ 500 LOC and `FunctualizeApp` ≤ 300 LOC, asserted by
  `tests/test_facade_loc_limits.py`.
- **AC-11** `contributor/reference/code-map.md:31` describes `RunContext` correctly — its size
  and its module.
- **AC-12** `tests/tui_audit/` passes; live zones still resolve.
- **AC-13** `func builtin why` still works and its tests pass.
- **AC-14** `boot_static` cold start is still under 5 ms.

---

## 5. Out of scope

- The `app/utils.py` corridor — **N3**.
- Deriving `RunContext`'s exposures from declarations — **N2**. This feature *shrinks* the
  facade; it does not derive it.
- Any change to the lifecycle's steps or their order.
- The `TYPE_CHECKING` layer-contract blind spot — F8.

## 6. Prior art

- **ADR-020** decision 3.
- **`dependency-graph.md:80-104`** — the house recipe for a protocol port with constructor
  injection. This is that recipe, applied to the engine.
- **`.spec/CONSTITUTION.md` → Ports** — all ports are `@runtime_checkable Protocol`, never ABC.
- **ADR-014** — the precedent this generalizes: declared-beside plus an import-time invariant.
  Deliberately **not** re-opened.
- **`test_typer_isolation.py`** — the absence-assertion shape AC-3 copies.

## 7. Why this is the riskiest feature, and what defends it

The `_app` reads in `runcontext.py` (`:425`, `:479`, `:698`, `:719`, `:764`) and
`_engine/surface_routing.py` (six sites) are **load-bearing for live zones** — the TUI's
running-job panel resolves through them. Re-pointing them at a host is not a rename; it is a
change to how a live surface finds its zone.

Three defences, in order of how much they are trusted:

1. `tests/tui_audit/` — the suite that already exists for exactly this surface.
2. Re-pointing them **in the same commit** as the host lands, so no intermediate state has
   half the reads going each way.
3. `tests/engine/test_lifecycle_order.py` green at every commit, which bounds the Extract
   Class work to pure movement.

It is sequenced third — after F1 and F2, despite being independent of them in principle —
because those two establish the pattern on lower-risk ground, and because the host is what
this feature's own collaborators are constructed from.
