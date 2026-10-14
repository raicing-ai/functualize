# plan.md — lazy-import-path-race

Shape gate: this issue's `Shape state = not-required` (maintainer-set,
observed live on the issue this session) — no shape page exists to align
with, which is the one state the gate accepts for a fix with no new
user-visible surface.

## BEFORE

```
_engine/capabilities/invoke.py (_ParallelBatch)
  └─ threads: _execute_single → _run → engine.get_job
       │  (peer layer: _engine ──uses──> _types; never imports _discovery)
       ▼
_engine/executor.py  get_job → _ensure_materialized
       │  entry.function.materialize()      [1 proxy per job]
       ▼
_discovery/lazy_wrapper.py
  LazyJobFunction.materialize  ──holds──> self._lock   (PER-INSTANCE)
       └─ _import_real_function
            sys.path.insert(module_dir)     ─────────┐
            importlib.import_module / re-exec        │ UNGUARDED,
            sys.modules.get → partial module ────────┼─ process-global
            finally: sys.path.remove(module_dir) ────┘
                    ▲
  sys.path, sys.modules — interpreter-global, owned by nobody
```

Two jobs of one module = two proxies = two locks = no serialization of
their `sys.path` traffic. Facet 1 (path yank): A's `finally` removes the
directory while B resolves against it. Facet 2 (partial module): CPython
publishes the module to `sys.modules` before its body runs, so B's
`sys.modules.get` returns a half-initialised module whose `__file__`
matches, and the `getattr` for B's job fails because A's body has not
reached that `def`.

## AFTER

```
_engine/capabilities/invoke.py (_ParallelBatch)          [unchanged]
  └─ threads → engine.get_job → _ensure_materialized      [unchanged]
       ▼
_discovery/lazy_wrapper.py
  LazyJobFunction.materialize  ──holds──> self._lock      [unchanged:
       │                                                   memoisation only]
       └─ _import_real_function
            real-source branch:
              with _IMPORT_LOCK (module-level RLock):     [NEW — sole change]
                  insert → resolve → remove, one region, whole process
            synthetic-source branch (<entry_point>/<dynamic>):
              plain import, outside the lock               [unchanged]
```

Layers and dependency directions are untouched: the change lives entirely
inside one `_discovery` module, imports nothing new beyond stdlib
`threading` (already imported in this file), crosses no import-linter
boundary, and adds no wiring.

## Skills consulted

- `.claude/skills/python-design-patterns` (repo-shipped): KISS — one
  primitive, one region; no refcount map, no owner object, no new module.
- `design-patterns-refactoring` (user-level, Refactoring.Guru catalogue):
  the BEFORE smell is **Mutable Data / Global Data** (a dispensable shared
  resource mutated from several places with no coordinating owner). The
  catalogue's standard remedies (encapsulate variable, move the mutation
  into one place) land exactly on "one lock, one region".

## The lock and the Constitution (AC-6)

Forbidden Patterns bans "global mutable state / module-level singletons —
reason: breaks testability and DI". A module-level `RLock` is neither of
the things that reason is about:

- **It is not state.** It holds no data and has no observable value; its
  entire behaviour is mutual exclusion. Nothing reads it, resets it
  between tests, or branches on it — so the testability half of the rule
  cannot fail.
- **It is not a resolvable dependency.** Nothing resolves it through the
  DI registry, so the DI half cannot fail either.
- **The resource it guards is already interpreter-global.** `sys.path`
  and `sys.modules` belong to no app, engine, or proxy; CPython's own
  import machinery holds module-level locks for exactly this reason. A
  guard narrower than the resource it guards is not a design, it is the
  bug this feature fixes.

The instance-scoped alternative was examined and rejected on reach, not
on taste: proxies are created per-descriptor in `_app/boot.py`
(`register_descriptors`) with no shared owner; `EntryPointProvider.
_materialize` and tests call `_import_real_function` with no proxy in
sight; a lock injected at boot would serialise boot-created proxies while
missing every other caller, and the resource would stay exposed. The one
owner that spans all callers of a process-global resource is the module
that mutates it.

Re-entrant (`RLock`) deliberately: a job module whose import nests
another lazy materialisation on the same thread (the collision re-exec
path executes arbitrary module code inside the region) must not
self-deadlock. Lock order is fixed — proxy lock (per-instance, outer)
then `_IMPORT_LOCK` (inner) or `_IMPORT_LOCK` alone — so no cycle exists.

## Technical approach

1. Tests first, red against `master`: deterministic interleaving repro
   (started/release marker files pace the two threads; fails through
   facet 2), stress run of warm-cache parallel batches (fresh module per
   batch, small in-body sleep), `sys.path` identity on success and both
   failure shapes, and the behavior-preservation batch set (cold, warm
   single, warm repeat, different-module).
2. `lazy_wrapper.py`: hoist `import threading` to module scope, define
   `_IMPORT_LOCK` with the argument above at its definition, and wrap
   only the real-source branch's insert→import→remove region.
3. Green, then all gates; sabotage proof after committing.

## Files to change

- `src/functualize/_discovery/lazy_wrapper.py` — the lock + region wrap.
- `tests/execution/test_lazy_materialization.py` — new test class, rides
  the file's existing `_write_job_module` / `_lazy_entry` / `_make_engine`
  harness and its `lazymod_` `sys.modules` cleanup fixture.
- `CHANGELOG.md` — `### Fixed` entry under `## [Unreleased]`.
- `.spec/STATUS.md` — durable half under `## Completed`.

## Risks

- **Serialised first-import across different modules** (throughput, not
  correctness): imports happen once per module per process; the cost is
  bounded by module import time and paid only on first materialisation.
- **Test brittleness via marker-file polling**: bounded waits with
  deadlines everywhere; the repro's failure mode does not depend on
  timing luck — the module body provably blocks while B reads it.
- **Uncovered adjacent regions**: `_discovery/registry.py` and
  `_discovery/sync.py` carry the same insert/remove shape on the cold
  scan path, where no worker threads exist today. Left out of scope (see
  spec.md); folding them in later means taking the same lock there.

## Surviving smells

- **Mutable Data (Global Data)** — `sys.path` itself. The lock removes
  the *race*, not the *global*; the global is the interpreter's, not
  ours, and no local refactor can dissolve it. Accepted as-is; needs no
  maintainer review beyond this plan.
- Serialised different-module first-imports (a deliberate throughput
  ceiling, not a catalogue smell): accepted for the once-per-module
  reason above; flagged here so a future profile that disagrees knows
  where the ceiling is and why it was chosen.

No other smells are introduced: one module touched, one primitive added,
no new coupling, no god-object growth (the wrapper stays well under every
ceiling), no middle man, no shotgun surgery.
