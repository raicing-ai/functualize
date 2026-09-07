# Tasks

Gates are run at authoring time, with each task's file scope equal to its
gate's hit set. Reachability precedes `[x]`: name the production call path and
verify it by breaking the call.

## 1.1 — the collision record and its message

- [x] Add a constructor for a job-name-collision `DiscoveryFailure` in
      `_types/discovery_report.py`, so both detection sites emit an identical
      message. Names both claimants (module + Python name), the canonical name,
      and which one is unavailable.
- [x] Unit test: the record's four fields, and `as_dict()` round-trip.

**Gate:** `uv run pytest tests/discovery/test_discovery_failures.py -q` green;
`uv run ruff check src/ tests/`; `uv run mypy src/`.

## 1.2 — retain both claimants, and index once

Revised after probing: the cached provider collapses a collision before
registration sees it, and the loser was never persisted. See `plan.md`.

- [ ] Key retained entries by `source_file::python_name` in
      `_discovery/cached_provider.py`, so both claimants survive a scan and a
      cache write.
- [ ] Bump `CACHE_VERSION` 19 → 20 in `_primitives/cache_format.py`.
- [ ] Add `_reindex_by_name()` as the **sole** writer of the name index: last
      claimant wins, displaced claimants recorded through the discovery-failure
      collector. Call it after scan, after cache load, and after refresh.
- [ ] Add a way to record a prebuilt finding to `_types/discovery_report.py`
      (the existing entry point takes an exception; a collision has none).
- [ ] Tests: shape A and shape B on the default path — one job, one collision,
      **surviving function asserted by identity** (A1–A4).
- [ ] Test: a clean project reports no collisions, job list unchanged (A10).

**Reachability (cold and warm, per `contributor/guides/wiring-discipline.md`):**
cold — `FunctualizeApp.__init__` → `boot_standard` → `resolve_and_register_jobs`
→ `_register_jobs_lazy` → `CachedDirectoryScanProvider.list_jobs` → scan →
`_reindex_by_name`. Warm — same chain, cache load → `_reindex_by_name`. Break
each by making the reindex a plain dict assignment and confirm A1 fails cold
*and* A6 fails warm.

**Gate:** `uv run pytest tests/discovery/ -q` green; fast suite green.

## 1.3 — the eager path stops raising

- [ ] Remove the `ValueError` from `_discovery/registry.py`; record through the
      builder from 1.1.
- [ ] Rewrite the tests that pin the raise to pin the reported outcome —
      inverted, not deleted, so the old behavior stays on the record.
- [ ] Tests: eager shape A reports and skips (A7); eager shape B registers one
      entry, not two (A8); both paths agree on the job-name set (A9).

**Gate:** `uv run pytest tests/discovery/ tests/app/ -q` green.

## 1.4 — the guard for uncached providers, and the report surface

- [ ] `register_descriptors` (`_app/boot.py`): same rule for descriptors from a
      provider the cache does not front (`StaticProvider`, a plugin's own).
- [ ] Test: identical function object registered twice stays silent (A11).
- [ ] Tests: `builtin info --json` publishes the collision with
      `error_type: "JobNameCollision"` (A5); the same invocation repeated with
      no cache clear still reports it (A6); `func --help` and `builtin info`
      both work with a collision present (A12).

**Gate:** `uv run pytest tests/cli/ tests/app/ -q` green; `uv run lint-imports`
zero violations.

## 1.5 — close

- [ ] Full suite: `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q`.
- [ ] `uv run pytest examples/ -q`.
- [ ] `uv run mypy src/`, `uv run ruff format --check src/ tests/`,
      `uv run lint-imports`.
- [ ] Update `.spec/STATE.md`.

**Gate:** all of the above green (A13).

## Task Dependency Graph

```json
{"waves": [
  {"id": 0, "tasks": ["1.1"]},
  {"id": 1, "tasks": ["1.2"]},
  {"id": 2, "tasks": ["1.3", "1.4"]},
  {"id": 3, "tasks": ["1.5"]}
]}
```
