# Tasks

## 4.1 — the export

- [x] Re-export `StaticProvider` from `functualize.plugin`; add to `__all__`.
- [x] Test: import from the public path (A1), present in `__all__` (A2),
      a provider built from public imports only registers jobs whose
      parameters survive (A3), bound methods skip `self` (A4).
- [x] `docs/api/discovery.md`: it is no longer an internal-only symbol.

**Reachability:** `app.add_job_provider(StaticProvider([...]))` →
`ResolutionPipeline.resolve_all` → `register_descriptors`. Break by removing
the export and confirm A1 fails.

**Gate:** `uv run pytest tests/plugins/ -q`; `uv run lint-imports`; mypy.

## 4.2 — the guide

- [x] Land `docs/guides/subjects.md`, with the private-import warning removed.
- [x] Re-run its example against the current build; correct anything stale.
      **Two corrections:** the private-import footnote, and footnote 4, which
      told readers "take `str` and convert — a bare `Path` parameter is not an
      injectable type; boot rejects it with `DIValidationError`". That was true
      when the guide was drafted and is now false — `parameter-type-support`
      fixed it — so the example takes a real `Path` and the footnote names the
      supported value types instead. Verified by running the example verbatim:
      three jobs under `pg`, `self` and the injected capabilities excluded,
      `to` published as a parameter.
- [x] One bullet in `docs/guides/index.md`, one line in `mkdocs.yml` nav.

**Gate:** `uv run mkdocs build --strict` exit 0 (A7).

## 4.3 — close

- [ ] Full suite, examples, mypy, format, lint-imports.
- [ ] Update `.spec/STATE.md`.

**Gate:** all green (A8).

## Task Dependency Graph

```json
{"waves": [
  {"id": 0, "tasks": ["4.1"]},
  {"id": 1, "tasks": ["4.2"]},
  {"id": 2, "tasks": ["4.3"]}
]}
```
