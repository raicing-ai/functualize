# http-docs-execute-route — the Usage Modes guide documents the HTTP route the server serves

## Problem

`docs/guides/modes.md` § *Adapter Mode › HTTP Adapter* told readers to run

```bash
curl -X POST http://localhost:8080/jobs/deploy/run \
  -H "Content-Type: application/json" \
  -d '{"target": "production", "env": "prod"}'
```

Against a running `HttpAdapter` that request answers
`404 {"error": "Not found", "path": "/jobs/deploy/run"}`. The router
(`plugins/adapters/functualize-http/src/functualize_http/__init__.py`,
`HttpServerCore.handle_request`) serves exactly three routes: `GET /health`,
`GET /jobs`, and `POST /jobs/<name>/execute`. The body is parsed by
`functualize.types.request_from_envelope`, which reads the job's parameters from
a nested `arguments` object, beside `group_option_values`, `scope_id` and `force`.
A flat body sent to the real route leaves the job's parameters unset
(`400 Missing required argument 'target'` for a required one).

The same section never said how the server is started beyond Python. The plugin
also defines `HttpServerPlugin`, which registers a `serve` command, but the
package's `functualize.plugins` entry point loads `HttpAdapter`, so `func serve`
answers `Error: Unknown command 'serve'.` (exit 1) with the plugin installed.

## Scope

Documentation only. No file under `src/` or `plugins/**/src/` changes. Making
`func serve` exist is a code change and is out of scope; the guide states that
HTTP is started from Python.

## Acceptance criteria

- **AC-1** The HTTP Adapter section of `docs/guides/modes.md` prints
  `POST /jobs/<name>/execute`, and no `/run` route.
- **AC-2** It prints the `arguments` envelope and names all four fields the
  parser reads (`arguments`, `group_option_values`, `scope_id`, `force`).
- **AC-3** Every `curl` and every request body the section prints was sent to a
  running `HttpAdapter` and answered as the section says; the response the
  section prints is one the server returned.
- **AC-4** The section says plainly that installing `functualize-http` adds no
  `func serve` command.
- **AC-5** `mkdocs build --strict` passes and the section's links resolve.
- **AC-6** `CHANGELOG.md` `[Unreleased]` carries a hand-written entry.

## Out of scope (recorded, not fixed here)

- `func serve` / `HttpServerPlugin` wiring (a code change).
- The plugin's own README still documents `HttpServerPlugin` "as a CLI plugin",
  and `plugins/adapters/functualize-http/examples/http_service/README.md` sends a
  flat body to `/execute`. Both are the plugin's docs, owned by the plugin
  test-standard work (docs asserted against the router).
- Refusing unknown top-level envelope keys, live socket outcome tests, the
  status-code table, `scope_id` resume over HTTP.
