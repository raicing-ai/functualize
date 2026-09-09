# Tasks — mcp-server-fixes

## 1.1 Fix `_build_tool_function` codegen for dotted grouped names (F1 + F1b)

- [F] `plugins/functualize-mcp/src/functualize_mcp/_server.py`
- **Change:** in the parameterized branch of `_build_tool_function` (module
  helper starting :154, `fn_source` at :201): derive a Python-safe identifier
  from `job_name` (`re.sub(r"[^0-9A-Za-z_]","_", job_name)`, prefix `_` if
  empty/digit-leading), build `fn_source` with the safe name and WITHOUT the
  `'''{description}'''` interpolation, `exec`, then set
  `fn.__name__/__qualname__ = job_name` and `fn.__doc__ = description`
  (mirroring the no-params branch at :180-183). Add `import re` if absent.
- **Acceptance:**
  1. `uv run python -c "from functualize_mcp._server import _build_tool_function; import inspect"` imports clean.
  2. Existing unit behavior unchanged: no-params branch untouched.
- **Wiring:** production path `MCPServer._register_tools` -> `_register_single_tool`
  -> `_build_tool_function` -> `FastMCP.add_tool`; removing the fix makes the
  live test in wave 2 fail at registration.

## 1.2 Suppress FastMCP update check and banner on serve (F2)

- [F] `plugins/functualize-mcp/src/functualize_mcp/_server.py`
- **Change:** in `MCPServer.__init__` (before any run): unless
  `FASTMCP_CHECK_FOR_UPDATES` is in `os.environ`, set
  `fastmcp.settings.check_for_updates = "off"`; unless
  `FASTMCP_SHOW_SERVER_BANNER` is in `os.environ`, set
  `fastmcp.settings.show_server_banner = False`. Import `fastmcp` module and
  `os`.
- **Acceptance:**
  1. `uv run python -c "from functualize_mcp._server import MCPServer; print('ok')"` imports.
- **Wiring:** every `func mcp serve` boot; live test asserts no `pypi.org`
  line and no `FastMCP 4` banner in captured server output.

## 2.1 Bound the fastmcp dependency (F3)

- [F] `plugins/functualize-mcp/pyproject.toml`
- **Change:** `"fastmcp>=0.1.0"` -> `"fastmcp>=3.4.0,<5.0.0"`.
- **Acceptance:**
  1. `uv run python -c "import importlib.metadata as m; print(m.version('fastmcp'))"` still resolves (4.x) after `uv sync`.
  2. `grep -n 'fastmcp' plugins/functualize-mcp/pyproject.toml` shows the bound.

## 3.1 Unit + registration tests for grouped/hostile tool functions (F4)

- [F] `plugins/functualize-mcp/tests/test_server.py` (new)
- **Change:** tests per plan T4: dotted name with params builds + executes
  (name preserved); hostile description (`'''`, backslashes) builds with
  description preserved; registration on a bare `FastMCP()` exposes tool
  `probe.echo` with the typed schema; no-params grouped path still builds.
- **Acceptance:**
  1. `uv run pytest plugins/functualize-mcp/tests/test_server.py -q` green.
  2. Revert 1.1 -> `test_build_tool_function_grouped_name_with_params` fails
     with `SyntaxError` (proves the test guards the fix).

## 3.2 Live capability test — grouped project served over stdio (F4, B5)

- [F] `plugins/functualize-mcp/tests/test_live_serve.py` (new)
- **Change:** subprocess test per plan T4: temp project with `JOB_GROUP`
  module (`ping`, `echo(text: str)`, `secret` internal, hostile-docstring
  job); spawn `func mcp serve` (cwd=tmp, XDG isolated); mcp stdio client
  (sync wrapper around asyncio); assert dotted tool names present, internal
  absent, typed schema present, call `echo` returns envelope JSON with
  `return_value`; assert no `pypi.org` and no banner in server output.
- **Acceptance:**
  1. `uv run pytest plugins/functualize-mcp/tests/test_live_serve.py -q` green.
  2. This test FAILS on unpatched 0.2.3 `_server.py` (probe-verified F1 crash)
     — the regression guard.

## 4.1 Grouped-tools example with live harness (B6)

- [F] `plugins/functualize-mcp/examples/grouped_tools/jobs.py` (new),
  `plugins/functualize-mcp/examples/grouped_tools/test_grouped_tools.py`
  (new), `plugins/functualize-mcp/examples/README.md`
- **Change:** example project per plan T5 + README table row and "Serving
  grouped jobs" note.
- **Acceptance:**
  1. `uv run pytest plugins/functualize-mcp/examples/ -v` green (both
     weather_tools and grouped_tools collected).

## 5.1 Docs + verify checkpoint

- [F] `docs/guides/mcp.md`, `.spec/STATE.md`, `.spec/STATUS.md`
- **Change:** mcp.md note (grouped jobs serve under dotted full name; no
  update check/banner unless `FASTMCP_*` set). Run verification:
  `uv run ruff check plugins/functualize-mcp/`, `uv run ruff format
  plugins/functualize-mcp/`, full plugin tests, examples tests, root fast
  tests `uv run pytest -x -q --no-header`; live manual serve of the example.
- **Acceptance:**
  1. ruff clean; plugin + examples suites green; root fast suite green.
  2. Manual: `cd examples/grouped_tools && func mcp tools` lists dotted tools
     without server boot crash.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["3.1", "3.2"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["5.1"] }
  ]
}
```
