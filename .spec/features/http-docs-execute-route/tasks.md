# http-docs-execute-route — tasks

## T1 — correct the HTTP Adapter section of the Usage Modes guide

- [x] Files: `docs/guides/modes.md`
- Covers AC-1, AC-2, AC-4.
- Gate: `rg -n 'jobs/[^ ]*/run\b' docs/guides/modes.md` finds nothing;
  `rg -n '/execute|"arguments"|group_option_values|scope_id|"force"|func serve' docs/guides/modes.md`
  finds each.
- Call path documented: `HttpAdapter.run` → `HttpServerCore.start` →
  `_handle_connection` → `handle_request` → `_execute_job` →
  `request_from_envelope` → `PluginHost.execute`.

## T2 — execute every request the section prints

- [x] Files: none in the repository (evidence in the PR body).
- Covers AC-3.
- Gate: a live `HttpAdapter` on a local port answers the printed `curl`
  `200 Success`, the printed envelope `200 Success` with `force` turning a
  `Skipped` into `Success` for identical arguments, and the BEFORE request
  `404`.

## T3 — build the docs

- [x] Files: none.
- Covers AC-5.
- Gate: `uv run mkdocs build --strict` exits 0; the built page carries
  `id="example"` and the link to `examples/project/http-service/`.

## T4 — changelog and durable record

- [x] Files: `CHANGELOG.md`, `.spec/STATUS.md`
- Covers AC-6.
- Gate: `[Unreleased]` carries the entry; `.spec/STATUS.md` § *Completed*
  carries the decision and the open items.

## T5 — clear the branch artifacts (last commit, deletion only)

- [ ] Files: `.spec/features/http-docs-execute-route/**`
- Gate: the commit deletes only that tree, after the feature push validated.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": "W1", "tasks": ["T1"]},
    {"id": "W2", "tasks": ["T2", "T3", "T4"]},
    {"id": "W3", "tasks": ["T5"]}
  ]
}
```
