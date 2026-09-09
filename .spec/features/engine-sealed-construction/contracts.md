# Contracts — engine-sealed-construction

External interfaces only.

---

## 1. `functualize._types.protocols` — the port

```python
@runtime_checkable
class EngineHost(Protocol):
    """Everything the engine needs from outside itself, wired once."""

    def get_job(self, name: str) -> RegisteredJob | None: ...
    def get_descriptor(self, name: str) -> JobDescriptor | None: ...   # kills runcontext.py:698
    def registered_jobs(self) -> Mapping[str, RegisteredJob]: ...      # replaces the shared dict

    @property
    def resolution_chain(self) -> ResolutionChain: ...                 # kills 2 writes
    @property
    def state_root(self) -> Path: ...                                  # kills 3 Path.cwd() sites
    @property
    def max_invoke_depth(self) -> int: ...                             # kills boot.py:1586
    @property
    def surface_stack(self) -> Sequence[Surface]: ...                  # kills surface_routing's getattr
    @property
    def event_bus(self) -> EventBus: ...                               # kills runcontext.py:428

    def resolve_gate(self, ...) -> GateResolver | None: ...
    def live_zone(self) -> LiveZone | None: ...                        # live.py:135, tty.py:132
```

`@runtime_checkable Protocol`, never an ABC — `.spec/CONSTITUTION.md` → *Ports*. Dependencies
point inward: the engine consumes the host; the host knows nothing of the engine.

`registered_jobs()` returns a **read-only mapping**. `add_registry_mirror` and the shared
private dict are removed — the engine asks, rather than being handed something it can mutate.

## 2. `functualize._app.boot` — one builder

```python
def build_engine(host: EngineHost) -> JobExecutionEngine: ...
```

Replaces the two near-identical construction blocks (`boot.py:270-288`, `:482-500`). Both boot
paths call it. Everything the engine needs is a constructor argument or a host method.

### Removed

```python
app._execution_engine._app = app                      # boot.py:286, :498
app._execution_engine._resolution_chain = …           # boot.py:701
app._execution_engine._max_invoke_depth = depth       # boot.py:1586
engine._resolution_chain = self._resolution_chain     # core.py:514
app._execution_engine.add_registry_mirror(...)        # boot.py:288, :500
JobExecutionEngine.add_registry_mirror                # executor.py:232
```

## 3. `functualize.app` — `refresh()`

`FunctualizeApp.refresh()` keeps its signature and its behaviour. It no longer writes
`engine._resolution_chain`; the engine reads `host.resolution_chain` when it needs it, so a
refresh is visible to the engine without anyone reaching in.

## 4. `functualize.job` — `RunContext` after the diet

`RunContext` keeps the job-author core:

```
name · config · log · invoke · prompt · status/phases · state · sources · freshness · cwd
```

**Moved off `RunContext`** — *Additional Facades*, ch14's own remedy:

| Moved | To |
|---|---|
| `emit`, `on_event` | an observability facade, reachable as `rc.events` |
| `perf_mark`, `perf_*` | the same facade, `rc.events.perf_*` |
| `get_job_schema`, `list_jobs` | a discovery facade, `rc.discovery` |

**Breaking for job authors** who use those re-exposures — pre-release, one release note. The
methods do not disappear; they move one attribute deeper, and the release note gives the
mapping.

## 5. `functualize._engine` — two collaborators

```python
class WorkflowOrchestrator:   # was executor.py::_run_workflow_prelude  (:1186, ~140 LOC)
    def __init__(self, host: EngineHost, ...): ...

class DependencyRunner:       # was executor.py::_run_dependencies      (:1741, ~112 LOC)
    def __init__(self, host: EngineHost, ...): ...
```

Internal — no public re-export. They are engine-owned collaborators, not peers and not a new
layer.

## 6. Unchanged

- `_execute_lifecycle` and its 20 steps, in order.
- `JobExecutionEngine.run(request)` — F1's entry.
- Every capability's `CapabilitySpec` and the ADR-014 import-time invariant.
- `JobResult`, `RunStatus`, every exit code.
- `boot_static`'s < 5 ms budget and the ~3 ms pre-boot routing budget.
