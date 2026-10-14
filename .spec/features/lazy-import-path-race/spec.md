# spec.md — lazy-import-path-race

## Problem

Two jobs that live in the same module, invoked concurrently through
`invoke.parallel` on a **warm** cache, must both materialise. Today one of
them can fail with `JobMaterializationError`: the lazy-import wrapper
(`_discovery/lazy_wrapper.py:_import_real_function`) mutates the
process-wide `sys.path` — insert, import, remove — with no process-wide
guard, while `LazyJobFunction._lock` (lazy_wrapper.py:137) is per-instance
and guards only its own proxy's memoisation. Two jobs of the same module
are two proxies with two locks, so nothing serialises their shared
`sys.path` traffic.

Verified against `c03dfb72` (current `master`; the field reports were
triaged on `4e816a0f` and the code is unchanged in between — the insert at
lazy_wrapper.py:71 and the remove at :97 are byte-identical):

1. **Path yank.** Thread A inserts `module_dir`, imports, and removes it in
   a `finally`. Thread B checked `module_dir not in sys.path` while A's
   entry was still present (`path_added = False`), then A's `finally`
   removes the directory before B's `importlib.import_module` has finished
   resolving against it → `ModuleNotFoundError` → `JobMaterializationError`.
2. **Partial module.** CPython inserts a module into `sys.modules`
   *before* executing its body. Thread A starts importing the shared
   module and is still executing its body; thread B's
   `sys.modules.get(module_path)` finds the half-initialised module, the
   `__file__` matches, so B takes `module = existing` — and the job B
   wants is not bound yet (A's body has not reached that `def`) →
   `AttributeError` → `JobMaterializationError`.

Facet 2 needs no timing luck at all: it fires whenever B enters the region
while A's import is in flight, which a warm-cache `invoke.parallel` batch
of two same-module jobs does on first use.

One root cause, three filed reports (triaged as still outstanding):
FOSS-1 (origin), FOSS-62, FOSS-101.

## Scope

**In.** `_discovery/lazy_wrapper.py`'s `sys.path` region and its tests.
The `EntryPointProvider._materialize` caller stays correct by
construction: entry-point descriptors carry `source_file =
"<entry_point>"`, so they take the synthetic branch that never touches
`sys.path` (providers.py:828-831 calls `_import_real_function` with such
descriptors only).

**Out.** The `invoke.parallel` *result* semantics (a failed child not
failing the parent) — separate issue, already landed separately. The
warm-cache *staleness* (what makes the cache warm here, not the race).
The same-shape regions in `_discovery/registry.py` (239/274, 295/335),
`_discovery/sync.py` (159/188) and `_cli/main.py:503`: registry and sync
run on the cold scan path, where no engine worker threads exist yet; none
of them is reachable concurrently with lazy materialisation today. Folding
them in would widen the blast radius of this fix beyond the filed defect.

## Acceptance criteria

- **AC-1** The insert → import → remove region of
  `_import_real_function` is serialised across the whole process: a
  module-level mutual-exclusion primitive (re-entrant, so a job module
  whose import nests another lazy materialisation on the same thread
  cannot self-deadlock), with no thread able to import while another
  removes the directory and no removal before the last importer is
  finished.
- **AC-2** A deterministic reproduction exists that fails with
  `JobMaterializationError` before the fix and passes after it — paced by
  explicit interleaving (marker files), not by retry loops or timing luck.
- **AC-3** A stress test runs many warm-cache `invoke.parallel` batches of
  two same-module jobs (a fresh module per batch, so every batch exercises
  first-import concurrency) and observes zero `JobMaterializationError`.
- **AC-4** Cold start (descriptor-attached function), warm single-job
  batches, warm repeat batches and different-module batches behave exactly
  as today: same results, same one-import-per-module count.
- **AC-5** `sys.path` is left exactly as found — asserted on the success
  path and the failure path (import-time exception and missing module),
  and after the stress run.
- **AC-6** The Constitution's Forbidden Pattern "global mutable state /
  module-level singletons" is answered in writing (plan.md § The lock and
  the Constitution, and a comment at the primitive's definition): the
  primitive is mutual exclusion over an interpreter-global resource, not
  data state; an instance-scoped owner that spans *every* caller does not
  exist, and the spec says why.
- **AC-7** `uv run lint-imports` stays at 7 kept / 0 broken; `ruff
  check`, `ruff format --check`, `mypy src/` and the tier-mapped pytest
  selection pass.

## Behaviour contract

Nothing observable changes for callers. `LazyJobFunction.materialize()`
keeps its signature, its idempotence, its per-instance double-checked
locking, and its `JobMaterializationError` chaining. The only behaviour
delta: concurrent first materialisation of jobs sharing a module (or a
directory) no longer produces spurious `JobMaterializationError`.
