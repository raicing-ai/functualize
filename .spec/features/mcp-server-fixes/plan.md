# Plan — mcp-server-fixes

## Technical approach

### T1 — F1 + F1b: `_build_tool_function` codegen (one function, one fix)

File: `plugins/functualize-mcp/src/functualize_mcp/_server.py` (module-level
helper at :154).

Root cause: the parameterized branch compiles `async def {job_name}(...)`
where `job_name` is the full functualize name (`probe.echo`). The
no-parameters branch (:178-186) already does the right thing — a real closure
whose `__name__`/`__qualname__`/`__doc__` are then set to the dotted job name.
FastMCP derives the tool name from `fn.__name__` (verified against fastmcp
4.0.3 `function_parsing.py`: `fn_name = getattr(fn, "__name__", None)`), and
dotted tool names are legal (mcp SDK SEP-986 validation allows
`[A-Za-z0-9._-]`).

Fix in the parameterized branch:
1. Derive a *Python-safe identifier* for the `exec`:
   `safe_name = re.sub(r"[^0-9A-Za-z_]", "_", job_name)`; prefix `_` when the
   result is empty or starts with a digit. Each call owns its `exec_ns`, so
   two dotted names mapping to the same `safe_name` cannot collide.
2. Build `fn_source` with `{safe_name}` and WITHOUT the docstring
   interpolation (the F1b source-injection hazard).
3. After `exec`, return `exec_ns[safe_name]` with
   `fn.__name__ = job_name`, `fn.__qualname__ = job_name`,
   `fn.__doc__ = tool_def.description or ...` — byte-identical in effect to
   the no-params branch.

Requires `import re` in `_server.py`.

### T2 — F2: suppress FastMCP update check and banner

File: same `_server.py`, `MCPServer.__init__` (:54).

FastMCP runs `check_for_newer_version()` + banner at `server.run()`; both are
gated by pydantic-settings (`fastmcp.settings`, env prefix `FASTMCP_` —
verified: `Settings.check_for_updates`, `Settings.show_server_banner`).
Operator env vars take precedence over code defaults in pydantic-settings, so
plugin code must set the fields only when the env vars are absent:

```python
import os
import fastmcp  # module (FastMCP class import at top is not enough)

if "FASTMCP_CHECK_FOR_UPDATES" not in os.environ:
    fastmcp.settings.check_for_updates = "off"
if "FASTMCP_SHOW_SERVER_BANNER" not in os.environ:
    fastmcp.settings.show_server_banner = False
```

`MCPServer.__init__` runs before any `run()`; settings are read at banner
time, so mutation in `__init__` is sufficient. Settings validate on
assignment (`validate_assignment=True`), plain attribute set is fine.

No dedicated unit test for the settings (they are third-party behavior); the
capability test asserts the observable contract: no `pypi.org` request and no
banner in the spawned server's captured output.

### T3 — F3: bound fastmcp

File: `plugins/functualize-mcp/pyproject.toml:21`. Change
`"fastmcp>=0.1.0"` → `"fastmcp>=3.4.0,<5.0.0"`. The lower bound admits
the repo-locked 3.4.2, so a constrained environment or an older lock can
stay on it; the upper bound excludes future majors. A fresh resolve picks
the newest allowed (4.0.3), so both endpoints are live combinations. Both 3.4.2 and 4.0.3 verified for the
mechanisms the fix relies on (dotted-name registration via fn.__name__;
`settings.check_for_updates`/`show_server_banner` + version-check "off"
gate).

### T4 — F4: tests

New files under `plugins/functualize-mcp/tests/`:

- `test_server.py` — unit + registration:
  - `test_build_tool_function_grouped_name_with_params` — dotted name +
    typed field: no raise; `fn.__name__ == "probe.echo"`; `await fn(text="x")`
    executes via FakeApp and returns the envelope dict.
  - `test_build_tool_function_hostile_description` — description containing
    `'''` and backslashes registers and keeps the description.
  - registration: add the built fn to a bare `FastMCP()`, assert tool name in
    server's tool list is `probe.echo` and schema carries `text`.
  - no-params grouped regression: `probe.ping` still fine.
- `test_live_serve.py` — capability (B5.2/B5.3): temp project with a
  `JOB_GROUP` module containing a no-arg job, a typed-arg job, an internal
  job, and a hostile-description job; spawn `func mcp serve` (located via
  `shutil.which("func")`) with cwd=tmp, XDG env isolated to tmp; connect an
  mcp SDK stdio client; assert `list_tools` has dotted names, internal one
  absent, typed schema present; call the typed job and assert envelope;
  assert server output has no `pypi.org` GET and no banner. Sync test using
  `asyncio.run` (no pytest-asyncio marker dependency).

Fixture reuse: `tests/conftest.py` `FakeApp`/`FakeDescriptor` extended only if
needed (FakeDescriptor already supports `name`+`parameters`).

### T5 — examples

New `plugins/functualize-mcp/examples/grouped_tools/`:
- `jobs.py` — `JOB_GROUP = "probe"`; `ping` (no args), `echo(text: str)`
  (typed), `secret` (`visibility="internal"`), `quote` whose docstring
  contains `'''` (F1b case).
- `test_grouped_tools.py` — live harness (same subprocess+MCP-client
  mechanism as the capability test) asserting the four contracts: dotted
  tool names served, typed schema survives, internal hidden, call returns
  envelope, hostile description does not break registration.
- Update `examples/README.md` table + a "Serving grouped jobs" note.

### T6 — docs

`docs/guides/mcp.md`: note that grouped jobs serve under their dotted full
name and that server boots do not perform FastMCP update checks (no egress)
unless `FASTMCP_CHECK_FOR_UPDATES` is set.

## Risks

| Risk | Mitigation |
|---|---|
| fastmcp name derivation changes in 4.x | F3 bound keeps the tested major; registration test pins the contract |
| Subprocess test flakiness (boot timing, ports) | stdio transport only (no ports); readiness via client connect retry with timeout |
| `func` console script absent in test env | `shutil.which("func")` + skip-if-missing; root workspace installs it (verified in probe venv) |
| Real user config leaking into subprocess tests | XDG_* env isolation to tmp in both live tests |

## Files

| File | Action |
|---|---|
| `plugins/functualize-mcp/src/functualize_mcp/_server.py` | edit (F1, F1b, F2) |
| `plugins/functualize-mcp/pyproject.toml` | edit (F3) |
| `plugins/functualize-mcp/tests/test_server.py` | add (F4 unit) |
| `plugins/functualize-mcp/tests/test_live_serve.py` | add (F4 capability) |
| `plugins/functualize-mcp/examples/grouped_tools/jobs.py` | add |
| `plugins/functualize-mcp/examples/grouped_tools/test_grouped_tools.py` | add |
| `plugins/functualize-mcp/examples/README.md` | edit |
| `docs/guides/mcp.md` | edit (small note) |
| `.spec/STATE.md`, `.spec/STATUS.md` | session state (gitignored) / durable record |
