# tasks.md — lazy-import-path-race

## Wave 0 — the proof and the seam

- [x] **1.1 Reproduction and invariant tests, red first**

New `TestWarmParallelMaterialization` class in
`tests/execution/test_lazy_materialization.py`, riding the file's existing
harness (`_write_job_module` shape, `_lazy_entry`, `_make_engine`,
`run_job`, the autouse `lazymod_` `sys.modules` cleanup):

- **AC-2 repro**: one module with jobs `alpha`/`beta`; its body writes a
  `started` marker, then blocks until a `release` file exists, then binds
  both defs. Thread A materialises `alpha` (engine.get_job); main paces on
  the started marker; thread B materialises `beta`; main waits (bounded)
  for B's outcome, writes `release`, joins both. Pre-fix, B reads the
  half-initialised module and fails `JobMaterializationError`
  deterministically; post-fix B waits at the region and succeeds. Also
  asserts `sys.path` unchanged.
- **AC-3 stress**: 30 batches, each a fresh two-job module (small in-body
  sleep), driven through real `WiredInvoke.parallel` on a real engine —
  every result `SUCCESS`, zero `JobMaterializationError`, `sys.path`
  identical at the end.
- **AC-4 preservation**: cold (attached function), warm single, warm
  repeat, and a different-module parallel batch — same outcomes and
  one-import-per-module counts as today.
- **AC-5 invariants**: `sys.path` identity across success, an import-time
  exception in the body, and a missing module.

- Files: `tests/execution/test_lazy_materialization.py`
- Gate (run at authoring time, red on `c03dfb7` before the fix):
  `uv run pytest tests/execution/test_lazy_materialization.py -q` — the
  repro and stress fail with `JobMaterializationError`; the invariant and
  preservation tests pass.

  Evidence: red run — 2 failed (the repro asserting
  `JobMaterializationError("Job 'beta': failed to import module
  'lazymod_…'")`, the stress batch raising through it), 17 passed, in
  1.25 s.

- [x] **2.1 Serialise the region**

`src/functualize/_discovery/lazy_wrapper.py`: hoist `import threading` to
module scope; define module-level `_IMPORT_LOCK = threading.RLock()` with
the Constitution argument at the definition; wrap the real-source
branch's insert → resolve → remove region (the `finally` removal inside
the primitive); synthetic-source branch stays outside; per-instance
`self._lock` and `materialize()` semantics untouched.

- Files: `src/functualize/_discovery/lazy_wrapper.py`
- Gate: `uv run pytest tests/execution/test_lazy_materialization.py -q`
  — exit 0, every test green.

  Evidence: 19 passed in 4.78 s, including the two previously red tests.

## Wave 1 — the record and the audit

- [x] **3.1 Reachability proof and the full check pass**

Production call path: warm boot `_app/boot.py:register_descriptors`
(function=None → `LazyJobFunction` per descriptor) → engine registry →
`invoke.parallel` worker (`_engine/capabilities/invoke.py` `_execute_single`
→ `_run` → `engine.get_job`) → `_engine/executor.py:_ensure_materialized`
→ `LazyJobFunction.materialize` → `_import_real_function` → **the lock
this feature adds**. Sabotage after committing: delete the `with
_IMPORT_LOCK:` line (de-indent the region), confirm the AC-2 repro fails,
restore. Then all checks: `uv run ruff check`, `uv run ruff format
--check`, `uv run mypy src/`, `uv run lint-imports` (7 kept / 0 broken),
and the step-tier selection from
`.agents/skills/test-tiers/scripts/tests-for-diff`, then the wave tier
(`tests/execution/ tests/discovery/ tests/engine/`).

- Files: none (proof and checks only)
- Gate: sabotage red / restore green on AC-2; all five checks exit 0.

  Evidence: after committing, replacing `with _IMPORT_LOCK:` with a no-op
  guard made the AC-2 repro fail in 0.32 s (`JobMaterializationError`,
  `Job 'beta'`); `git checkout --` of the committed file made all four
  warm-parallel tests pass in 4.04 s. `ruff check` and `ruff format
  --check` clean (1661 files); `mypy src/`: no issues in 393 files;
  `lint-imports`: 7 kept, 0 broken; step tier (mapper selection): 116
  passed, 7 skipped; wave tier (`tests/execution/ tests/discovery/
  tests/engine/`): 999 passed, 70 skipped.

- [x] **3.2 The durable record**

`CHANGELOG.md` → `## [Unreleased]` → `### Fixed` prose entry (hand-written,
no tracker keys); `.spec/STATUS.md` → `## Completed` entry with the
decision worth keeping, the rules that outlive the feature, and the
surviving smells.

- Files: `CHANGELOG.md`, `.spec/STATUS.md`
- Gate: both files carry the entry; `uv run ruff check` still clean.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": ["1.1", "2.1"]
    },
    {
      "id": 1,
      "tasks": ["3.1", "3.2"]
    }
  ]
}
```
