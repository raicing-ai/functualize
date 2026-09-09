# Plan — engine-sealed-construction

---

## 1. The approach in one line

**Declare what the engine needs, wire it once, delete every way to wire it twice — then take
out what was never execution, and make the size limits fail.**

## 2. The order is the risk management

The three audit steps this feature merges have very different risk, and the ordering exists to
put the dangerous part in the middle, where it is surrounded by green suites:

```
W0  EngineHost protocol                        (declaration only — nothing uses it)
W1  build_engine(host); both boot paths call it (construction collapses; writes remain)
W2  the five writes and the shared dict die     (the seal)
W3  the _app reads re-point                     ← THE RISK. Live zones.
W4  Path.cwd() leaves the kernel
W5  WorkflowOrchestrator out
W6  DependencyRunner out
W7  RunContext diet + FunctualizeApp diet
W8  the LOC test, and code-map.md corrected
W9  checkpoint
```

W3 is deliberately **after** the seal and **before** the extractions: after, so the host
already exists and is proven; before, so the extractions do not have to move code that is
still reading through `_app`.

## 3. Files to change

### New

```
src/functualize/_engine/workflow_orchestrator.py
src/functualize/_engine/dependency_runner.py
src/functualize/_engine/capabilities/observability_facade.py
src/functualize/_engine/capabilities/discovery_facade.py
tests/test_facade_loc_limits.py
tests/engine/test_engine_is_sealed.py
tests/app/test_state_root_from_host.py
```

### Modified

```
src/functualize/_types/protocols.py            EngineHost
src/functualize/_app/boot.py                   build_engine; 4 writes + 2 mirrors deleted
src/functualize/app/core.py                    refresh() re-resolves; :514 deleted; the diet
src/functualize/_app/impl.py                   receives explain / parallel / scope plumbing
src/functualize/_engine/executor.py            host injection; Path.cwd out; 2 methods out
src/functualize/_engine/preflight.py           root from the host
src/functualize/_engine/capabilities/runcontext.py   5 _app reads → host; the diet
src/functualize/_engine/surface_routing.py     6 getattr reads → host
src/functualize/_engine/capabilities/live.py   host.live_zone()
src/functualize/_engine/capabilities/tty.py    host
src/functualize/_engine/capabilities/stdout.py host
src/functualize/_engine/capabilities/invoke.py host
contributor/reference/code-map.md              line 31
```

## 4. Risks

- **R-a · Live zones break, and the TUI is where it shows.** The `_app` reads in
  `runcontext.py` and `surface_routing.py` resolve a live zone for a running job.
  *Mitigation:* re-point them **in one commit** (W3), with `tests/tui_audit/` as the gate. Do
  not split by file — a half-migrated read set is the failure mode.

- **R-b · The Extract Class moves change the lifecycle by accident.** `_run_workflow_prelude`
  is called from inside `_execute_lifecycle`. *Mitigation:*
  `tests/engine/test_lifecycle_order.py` AST-walks the method and checks call order against
  the doc; it must be green at **every commit**, and W5/W6 are sequences of pure Move-Method
  commits rather than one rewrite.

- **R-c · `func why` is orphaned.** `app/core.py:725-823` walks `engine.materialize_job` and
  `_declared_dep_names` — a second verdict path that any pre-flight move can strand
  (`RAD.6`, C-9). *Mitigation:* it is on the modified list, its own tests run in W7's gate,
  and AC-13 names it.

- **R-d · The `RunContext` diet breaks job authors silently.** Removing a delegation is a
  runtime `AttributeError` at their call site, not ours. *Mitigation:* pre-release; the
  release note carries the old → new mapping; `pytest examples/` runs in the gate because the
  examples are job-authored code.

- **R-e · The LOC test becomes a nuisance and gets weakened.** A limit that fails often gets
  raised rather than respected. *Mitigation:* land it **after** the diets, when both classes
  are comfortably under, so its first state is green with headroom — and have it print the
  current count, so a breach reads as information rather than an obstacle.

- **R-f · Boot gets slower.** A protocol indirection on a hot path. *Mitigation:* the host's
  members are properties over already-constructed objects, no new I/O; `boot_static`'s < 5 ms
  budget test is in the gate (AC-14), and collapsing two construction blocks into one should
  make it marginally faster.

- **R-g · `registered_jobs()` copies a large dict per call.** The shared mirror existed for a
  reason — the engine reads it often. *Mitigation:* return a `MappingProxyType` over the
  registry's map, not a copy: read-only without a copy cost. Measure it in W2 rather than
  assuming.

## 5. What this plan does not do

It does not touch the lifecycle, the request, the outcome module, or `app/utils.py`. If this
feature has changed what any job does, something has gone wrong — every change here is either
a construction move or a facade move, and both are supposed to be invisible from outside.
