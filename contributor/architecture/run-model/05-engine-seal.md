# 05 · The engine seal — complete at construction, and small enough to read

Cause **C-II** — the engine is mutable white-box state, assembled by its owners after it is
built, and read back through message chains.

---

## A. The engine is finished by its owners, twice

Five post-hoc private writes, re-verified at `e57f0c9` — **exactly the five the audit found,
at exactly the lines it gave**:

```
_app/boot.py:286    app._execution_engine._app = app
_app/boot.py:498    app._execution_engine._app = app
_app/boot.py:701    app._execution_engine._resolution_chain = app._resolution_chain
_app/boot.py:1586   app._execution_engine._max_invoke_depth = depth
app/core.py:514     engine._resolution_chain = self._resolution_chain
```

Plus a shared mutable dictionary handed across the boundary:

```
_app/boot.py:288    app._execution_engine.add_registry_mirror(app.job_registry._registered_jobs)
_app/boot.py:500    app._execution_engine.add_registry_mirror(app.job_registry._registered_jobs)
```

`_registered_jobs` is the registry's **private** map, passed by reference to the engine
(`executor.py:232`), so the two objects share mutable state with no contract between them.

Two things are worth separating:

- `boot.py:286` and `:498` are the **same write in two boot paths** — `boot_static` and
  `boot_standard`. So are `:288` and `:500`. The construction blocks at `boot.py:270-288`
  and `boot.py:482-500` are near-identical, differing only in a config-view factory, and
  carry the same twenty-line comment verbatim. This is a Divergent Change trap: the next
  engine parameter must be added twice, correctly, by whoever notices there are two.
- `core.py:514` fires on **`refresh()` — at runtime**, not at boot. The engine's config
  dependency is a writable field that can change under a run.

The boot contract (`AGENTS.md` steps 8–9, `REGISTRY_FROZEN → APP_READY`) covers the DI
registry. **Nothing freezes the engine.**

## B. And read back through the app it was handed

`_app` is written twice and read fourteen times. The chain the audit named is real, and it
is the only unguarded one:

```python
# _engine/capabilities/runcontext.py:698
return self._execution_engine._app.job_registry.get_descriptor(job_name)
```

Three hops from the kernel into the app's registry, with no `getattr` default. The others —
`runcontext.py:425,479,719,764`, `invoke.py:710`, `live.py:135`, `stdout.py:151`,
`tty.py:132`, `executor.py:1283,1550,1573` — all use `getattr(..., "_app", None)`, which is
the codebase admitting the attribute may not be there.

> **The correct path is not the readable one.** `runcontext.py:698` reaches through the
> engine for a descriptor the app owns; `RunContext` has no sanctioned route to it. The
> message chain is not laziness, it is the absence of a port.

## C. The kernel wires itself from the process

Three sites, not the one the audit named:

| Site | Code |
|---|---|
| `_engine/executor.py:1096` | `self._workflow_state_store = StateStore.for_project(Path.cwd())` |
| `_engine/preflight.py:116` | `self._root = Path(root) if root is not None else Path.cwd()` |
| `_engine/capabilities/runcontext.py:291` | `return self._cwd if self._cwd is not None else Path.cwd()` |

**New finding.** The audit reported `executor.py` only. All three are the kernel asking the
*operating system* a question its host should have answered, and they matter more together
than apart: a run whose `RunRequest` carries `cwd` can still land its state file somewhere
else, because `executor.py:1096` does not consult the request. The two later sites take a
`None` default, so they are one argument away from being correct; the first takes none.

This is also why the durable run layer cannot simply be added ([08](08-durable-runs.md)): it
needs one answer to *"where does this project's run state live?"*, and today there are three
places that answer it and one that answers it differently.

## D. The budgets are prose, breached, and unenforced

Measured at `e57f0c9`:

| Class | Constraint | Measured | Over by |
|---|---|---|---|
| `RunContext` (`_engine/capabilities/runcontext.py:117-898`) | ≤ 500 LOC facade (`CONSTITUTION.md`, AGENTS.md) | **782** | 1.6× |
| `FunctualizeApp` (`app/core.py:64-1328`) | ≤ 300 LOC facade | **1,265** | 4.2× |
| `JobExecutionEngine` (`executor.py:157-2557`) | "> ~500 LOC → decompose" (`CONSTITUTION.md`) | **2,401**, 55 methods | 4.8× |
| └ `_execute_lifecycle` (`executor.py:757-1085`) | — | **329** | — |

`contributor/reference/code-map.md:31` still describes `RunContext` as "~500 LOC" in
`job/context.py`. The constraint is prose, the prose is stale, the file moved, and **no test
fires on the breach**.

The overflow is *breadth, not depth*. `RunContext` is 58 one-line delegations re-exposing five
subsystems — `Invoke`, `PromptCollector`, `EventBus`, `PerfTimeline`, plugin config, plus
discovery. That is the textbook Facade-as-god-object: a facade that outgrows its budget has
stopped being a facade, and the engine has no owner left to keep it honest.

## E. The target

### E.1 `EngineHost` — a narrow port, wired once

`src/functualize/_types/protocols.py`, `@runtime_checkable Protocol` per
`.spec/CONSTITUTION.md` → *Ports* (no ABC, no forced inheritance). It declares only what the
engine needs **from outside**:

```python
@runtime_checkable
class EngineHost(Protocol):
    def get_job(self, name: str) -> RegisteredJob | None: ...
    def get_descriptor(self, name: str) -> JobDescriptor | None: ...   # kills runcontext.py:698
    @property
    def resolution_chain(self) -> ResolutionChain: ...                 # kills the two writes
    @property
    def state_root(self) -> Path: ...                                  # kills the three Path.cwd()
    @property
    def surface_stack(self) -> Sequence[Surface]: ...                  # kills surface_routing's getattr
    def resolve_gate(self, ...) -> GateResolver | None: ...
```

One `build_engine(host) -> JobExecutionEngine` in `_app/boot.py`, replacing both construction
blocks. `refresh()` re-resolves **through** the host rather than writing into the engine.

### E.2 Extract Class — the engine keeps execution, and only execution

`JobExecutionEngine` currently holds execution *and* workflow walking (`_run_workflow_prelude`,
~140 LOC) *and* dependency scheduling (`_run_dependencies`, ~112 LOC) *and* shell/sudo/redaction
resolution *and* history. Two engine-owned collaborators come out, constructed from the host:
`WorkflowOrchestrator` and `DependencyRunner`.

> **The lifecycle does not change.** `_execute_lifecycle`'s 20 steps are a Template Method
> whose order is a contract, and `tests/engine/test_lifecycle_order.py` AST-walks the method
> and checks the call order against `contributor/reference/execution-lifecycle.md`. It stays
> green at **every commit** of this work — that is the proof each move was pure, and it is
> the reason the moves can be done at all.

### E.3 Facade diets, and the budgets become tests

`RunContext` keeps the job-author core (name, config, log, invoke, prompt, status/phases,
state); the observability re-exposures (`emit`, `on_event`, `perf_*`) and discovery
re-exposures (`get_job_schema`, `list_jobs`) move to focused facades — ch14's own named
remedy, *Additional Facades*. `FunctualizeApp`'s explain / `execute_parallel` / scope plumbing
move to `_app/impl.py`, which exists for exactly this.

Then `tests/test_facade_loc_limits.py` asserts both numbers, and `code-map.md:31` is corrected
in the same commit. **The point is not the number; it is that the constraint acquires a
failure mode.**

## F. Risk, and why this feature is third

Sealing is rated **high risk** by the depth audit and this set agrees, for one reason: the
`_app` reads in `runcontext.py` and `surface_routing.py` are **load-bearing for live zones**.
Re-point them in the same commit, with `tests/tui_audit/` green.

It is placed after F1 and F2 rather than first, despite being independent in principle,
because the host is what F3's collaborators are constructed *from* — and because the two
lower-risk features establish the pattern (one authority, absence-tested) before the risky one
uses it.

## G. Sabotage checks

| Break this | This must fail |
|---|---|
| Restore any one of the five post-hoc writes | the absence test (`grep 'engine\._[a-z_]+ *='` outside `_engine/` returns empty), `test_typer_isolation.py` style |
| Re-point one `Path.cwd()` back into the kernel | the state-root test: a run with an explicit root writes its state there |
| Append 10 lines to `RunContext` | `tests/test_facade_loc_limits.py` |
| Reorder two lifecycle steps | `tests/engine/test_lifecycle_order.py` — already wired; demonstrate once |
