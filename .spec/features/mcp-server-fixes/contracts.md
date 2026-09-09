# Contracts — mcp-server-fixes

External interfaces this feature touches. Internal types are out of scope here.

## MCP tool surface (client-visible, unchanged in shape)

| Contract | Value |
|---|---|
| Tool name for grouped job | full functualize name: `probe.echo` (dotted, SEP-986-legal) |
| Tool name for ungrouped job | job name: `echo` |
| Input schema | JSON Schema object from the job's config fields; typed params appear as properties, `required` from schema |
| Result | functualize envelope serialized as JSON text: `{"status","return_value","duration_ms"}` (client receives text) |
| Visibility | `@job(visibility="internal")` jobs never registered; unannotated convention jobs not registered |

This is the *current* contract — the feature fixes the server so the contract
actually holds for grouped parameterized jobs, and pins it with tests.

## FastMCP settings (operator-facing)

| Setting | Plugin default | Operator override |
|---|---|---|
| `check_for_updates` | `"off"` (no PyPI GET) | `FASTMCP_CHECK_FOR_UPDATES` env var, set before import wins |
| `show_server_banner` | `False` | `FASTMCP_SHOW_SERVER_BANNER` env var, set before import wins |

Plugin must set defaults only when the operator has not set the env var
(pydantic-settings precedence: env var > code default; plugin code must check
env first or set only if unset).

## Dependency bound

`functualize-mcp` pyproject declares `fastmcp>=3.4.0,<5.0.0` (lower bound
admits the repo-locked 3.4.2; upper bound rejects future majors; both 3.4.2
and 4.0.3 verified for the mechanisms the fixes rely on).

## Executed call path (what the capability tests exercise)

```
MCP client (mcp SDK) ──stdio──> func mcp serve (subprocess)
                                  app discovery: JOB_GROUP module, typed jobs
                                  MCPServer._register_tools
                                    _build_tool_function(job_name, tool_def, app)
                                    FastMCP.add_tool(fn)         # fn.__name__ = dotted name
                                  tool call -> _execute_job -> app.execute(job_name, kwargs)
                                  envelope dict -> FastMCP text result
```
