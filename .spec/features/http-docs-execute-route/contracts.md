# http-docs-execute-route — contracts

No contract changes. This feature documents the existing wire contract; it does
not alter it. The contract as served, read from the source and confirmed on a
running server:

## Routes (`HttpServerCore.handle_request`)

| Method | Path | Answer |
|---|---|---|
| `GET` | `/health` | `200 {"status": "healthy"}` |
| `GET` | `/jobs` | `200 {"jobs": [{"name", "group", "docstring"}, …]}` |
| `POST` | `/jobs/<name>/execute` | runs `<name>`; `404 {"error": "Job '<name>' not found"}` when unknown |
| anything else | | `404 {"error": "Not found", "path": <path>}` |

`<name>` is the descriptor name `GET /jobs` lists: `<group>.<job>` for a grouped
job (`deploy.run`).

## Request body (`functualize.types.request_from_envelope`, surface `"http"`)

```json
{
  "arguments": {"…": "job parameters"},
  "group_option_values": {"…": "group options"},
  "scope_id": "string",
  "force": true
}
```

All four optional. `arguments` and `group_option_values` must be objects and
`scope_id` a string, or the parser raises `ValueError` naming the field.
Top-level keys outside the four are not job arguments.

## Response body (`HttpServerCore._execute_job`)

`{"status", "duration_ms", "return_value"}` plus `"error"` when the run carries
an exception. The status line comes from `functualize.types.http_status_for_status`.
