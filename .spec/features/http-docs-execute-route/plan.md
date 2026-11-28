# http-docs-execute-route — plan

## Alignment

Documentation-only correction with no new user-visible surface: the HTTP wire
contract already exists and is unchanged; the guide is brought into line with
it. No shape intent is attached to the covering issue and `Shape state` is not
set on it; the docs-only path (`Shape state = not-required`) is the one this
change claims, and setting that property is the maintainer's call, not this
branch's.

## Architecture

The region is one documentation page and the code it describes. Nothing in the
code moves; the only arrow that changes is which route the page points at.

```
BEFORE
docs/guides/modes.md  (docs, published by mkdocs)
  └─ prints ──► POST /jobs/deploy/run  {flat body}  ──► 404 (no such route)

plugins/adapters/functualize-http/src/functualize_http/__init__.py   (plugin)
  HttpServerCore.handle_request ── routes ──► /health, /jobs, /jobs/<name>/execute
  HttpServerCore._execute_job   ── imports ─► functualize.types.request_from_envelope
                                                (src/functualize/_types/run_request.py, _types layer)
  entry point functualize.plugins:http ──► HttpAdapter        (no `serve` command)
  HttpServerPlugin (registers `serve`) ◄── nothing loads it

AFTER
docs/guides/modes.md
  └─ prints ──► POST /jobs/<name>/execute  {"arguments": …, group_option_values, scope_id, force}
               └─ states: started from Python; no `func serve`
  (code region identical to BEFORE)
```

No module boundary is crossed and no import-linter contract is touched: the
diff is `docs/`, `CHANGELOG.md`, `.spec/`.

Design skills: none loaded, because no code changes. The session's listing
offers the user-level `design-patterns-refactoring` skill (the Refactoring.Guru
catalogue) and the in-repo `python-design-patterns`; the smell names below are
that catalogue's names (*Dead Code*, *Comments*, *Duplicate Code*).

Smells the BEFORE carries, by catalogue name:

- **Dead code** — `HttpServerPlugin` in `functualize_http/__init__.py`: no entry
  point loads it, so its `serve` command is unreachable through `func`.
- **Comments** (documentation that disagrees with the code) — the guide's route
  and flat body; the same drift lives in the plugin README and its example
  README.
- **Duplicate code** in the docs — the envelope is explained in the plugin
  README, the parser docstring, and now the guide. The guide's copy is short
  and points at the example project rather than restating the README.

## Technical approach

1. Rewrite the HTTP Adapter section's request example: route table, the job
   name rule, one runnable `curl` against the directory-mode example's
   `deploy.run`, the response it returned, the full envelope and a field table.
2. State that there is no `func serve`.
3. Run every printed request against a live `HttpAdapter`; build mkdocs strict.
4. Add the `[Unreleased]` entry; record the durable half in `.spec/STATUS.md`.

## Files to change

- `docs/guides/modes.md`
- `CHANGELOG.md`
- `.spec/STATUS.md`
- `.spec/features/http-docs-execute-route/**` (removed before merge)

## Risks

- The envelope's handling of unknown top-level keys may change (a refusal is
  planned for the Lambda surface through the shared parser). The guide says
  only that such keys are never job arguments, which stays true either way.
- No doc-verify scenario covers HTTP, so this page can drift again until the
  plugin's docs are asserted against the router.

## Surviving smells

- **Dead code** — `HttpServerPlugin` (`plugins/adapters/functualize-http/src/functualize_http/__init__.py`).
  Survives because removing or wiring it is a code change outside this
  docs-only row; the guide works around it by stating there is no `func serve`.
  Needs maintainer review: yes — expose `func serve` or delete the class.
- **Comments** (stale docs) — the plugin README's "As a CLI Plugin" section and
  the example README's flat-body `curl`. Out of this row's file scope; recorded
  for the plugin's docs work. Needs maintainer review: no.
- **Duplicate code** (the envelope described in three places). Accepted: the
  guide is a different audience from the plugin README. Needs maintainer
  review: no.
