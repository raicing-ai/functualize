# Tasks

## 2.1 — resolve the scan roots

- [x] Resolve `scan_roots` to absolute where the filters are built in
      `_app/boot.py`, so a relative `directories` entry excludes correctly.
- [x] Tests (`tests/discovery/test_relative_scan_roots.py`): `exclude_patterns`
      honoured for a relative entry on both paths (A14); every `require_*` too
      (A15); relative and absolute spellings admit the same set (A16).

**Reachability:** `FunctualizeApp.__init__` → `boot_standard` → filter
construction → `CachedDirectoryScanProvider` / `DirectoryScanProvider`. Break by
reverting to `Path(d)` and confirm A14 fails.

**Gate:** `uv run pytest tests/discovery/ -q`; fast suite green.

## 2.2 — the eager branch uses the provider

- [x] Register the pipeline directory provider's descriptors on the eager
      branch; stop calling `scan_and_register_headless` there.
- [x] Keep the fallback, and give it the same filters (A17).
- [x] Tests: one import per admitted module with a second provider present
      (A1), with a child project (A2), side effect fires once (A3), and the
      control with no second provider (A4).
- [x] Tests: `_registered_commands` keyed canonically (A5); `refresh()` leaves
      no phantom after a file is deleted (A6).
- [x] Tests: filters honoured (A7); both paths admit the same names (A8); an
      excluded module is **not imported**, asserted by side effect (A9).
- [x] Test: a DI-binding error in an admitted job still raises at boot (A10).
- [x] `grep -rn "scan_and_register_headless(" src/` → the eager branch is gone,
      the fallback remains (A11).
- [x] Invert `TestTheEagerPathFiltersNothing` rather than deleting it (A12).

**Reachability (cold and warm):** the eager path has no warm variant by
construction — its provider is uncached — which is itself worth asserting so a
later change cannot quietly give it one.

**Gate:** `uv run pytest tests/app/ tests/discovery/ -q`; `uv run lint-imports`.

## 2.2b — two defects the criteria did not predict

Found by the tests above rather than by the audit, and fixed here because the
feature's own goal is one scanning path:

- [x] **A newly added job module could be invisible to discovery.**
      `pkgutil.iter_modules` reads directories through `FileFinder`, which
      memoizes a listing and re-reads only when the directory mtime changes —
      so a file added in the same mtime tick was absent from the on-disk set
      entirely, while importing it directly worked and no discovery failure
      was recorded. Reproduced in-process. Fixed with
      `importlib.invalidate_caches()` in the enumeration, which is exactly
      what `refresh()` needs. **This one reaches `func` users.**
- [x] **The two providers disagreed about a grouped job's name.** The uncached
      provider carried a second extraction pass and produced the bare
      `provision` where the cached one produced `infra.provision`, so a
      grouped job reached through the pipeline could not be invoked. Both now
      delegate to `_discovery/sync.extract_module` — one extraction, which is
      the same duplication that produced the four known defects.
- [x] `_discovery/collisions.py`: the one-name-one-function rule extracted so
      both providers and the pipeline share it, rather than each carrying its
      own answer.
- [x] A8's parity test gained a grouped module — it passed while the two paths
      disagreed, which is what made the naming divergence invisible here.

## 2.3 — close

- [ ] Full suite with `--run-slow -n auto`.
- [ ] `uv run pytest examples/ -q`.
- [ ] mypy, format check, lint-imports.
- [ ] Update `.spec/STATE.md`.

**Gate:** all green (A13).

## Task Dependency Graph

```json
{"waves": [
  {"id": 0, "tasks": ["2.1"]},
  {"id": 1, "tasks": ["2.2"]},
  {"id": 2, "tasks": ["2.3"]}
]}
```
