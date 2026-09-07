# Tasks

## 5.1 — the default rendering

- [x] Failures panel in the rich renderer, above the jobs table (A1, A2).
- [x] Tests: shown when present, absent when not (A3), all three kinds (A4),
      warm boot (A12).

**Reachability:** `func builtin info` → `full_report` → the rich renderer.
Break by removing the panel and confirm A1 fails.

**Gate:** `uv run pytest tests/cli/ -q`.

## 5.2 — self doctor

- [x] `job-discovery` reports failures with `!!` and downgrades the status
      (A5, A6).
- [x] Tests for both, plus a healthy project still `ok`.

**Gate:** `uv run pytest tests/_cli/ -q`.

## 5.3 — the unknown-command hint

- [x] Attribute a typed name to a failed file by parsing its source, without
      importing (A7, A8).
- [x] Generic note when unattributable (A9); unchanged output with no failures
      (A10).

**Gate:** `uv run pytest tests/cli/ -q`.

## 5.4 — the warning line

- [x] One formatted line, no logger name, no internal path (A11).

**Gate:** `uv run pytest tests/discovery/ -q`.

## 5.3b — two things the criteria did not anticipate

- [x] **The hint reaches `func` and the adapter's fallback chain, not a
      project's own `main.py`.** That surface invokes click in standalone
      mode, so an unrecognized name is rendered by click's own `UsageError`
      before either reporter runs. One implementation is shared
      (`explain_missing_job`), the test is marked `surfaces("func")`, and the
      gap is recorded in STATUS — an assertion relaxed enough to pass on both
      surfaces passed *vacuously* on the second, matching the warning line
      rather than the explanation.
- [x] **A8 moved from the CLI to the helper.** Through the CLI it is not
      observable: every boot legitimately retries the failed import, which is
      what keeps the report alive on a warm boot, so an import-time marker
      file appears either way. The helper takes the failure list directly, so
      the question has an answer there.
- [x] The generic note says "discovery problem", not "failed to load": three
      kinds share the list and only one is a load failure.

## 5.5 — close

- [ ] Full suite, examples, mypy, format, lint-imports, mkdocs --strict.
- [ ] Update `.spec/STATE.md`.

**Gate:** all green (A13).

## Task Dependency Graph

```json
{"waves": [
  {"id": 0, "tasks": ["5.1", "5.2"]},
  {"id": 1, "tasks": ["5.3", "5.4"]},
  {"id": 2, "tasks": ["5.5"]}
]}
```
