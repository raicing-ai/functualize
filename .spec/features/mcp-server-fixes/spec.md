# Feature spec — mcp-server-fixes

**Status:** Specify phase · **Branch:** `fix/mcp-server-fixes` · **Base:** master `c0c921f`
**Origin:** NOOA <-> functualize integration probe (`~/code/raicing-ai/research/nooa-functualize-integration/01-probe-transcript.md`, findings F1-F4; fix scope: `02-functualize-fix-scope.md`)

## Problem statement

`func mcp serve` (functualize-mcp 0.2.3, bug still present at 0.3.0) fails or
misbehaves in four ways discovered by the live NOOA integration probe:

1. **F1 — grouped jobs with parameters crash the server.** A job whose full
   name is dotted (`JOB_GROUP = "probe"` → `probe.echo`) is turned into a
   Python function whose name is the dotted job name, compiled with `exec()`.
   `async def probe.echo(...)` is not valid Python, so the server dies during
   tool registration and serves nothing. Ungrouped jobs and grouped jobs
   *without* parameters work — only grouped jobs with a parameterized schema
   crash. Verified live: `SyntaxError: expected '('`, verbatim in
   `f1-grouped-crash.log` (research dir).
2. **F1b (latent, same function) — the tool description is interpolated into
   the exec'd source** inside `'''...'''`. A job description containing `'''`
   breaks compilation the same way. Descriptions are job docstrings — user
   content.
3. **F2 — every server boot phones home and prints a banner.** FastMCP runs a
   PyPI update check (`GET https://pypi.org/pypi/fastmcp/json`) and prints an
   ASCII banner when the server starts. Automation that spawns a server per
   call (the NOOA client does: one process per tool call) pays one network
   egress + banner per call. Sandboxed/offline deployments break on egress.
4. **F3 — the fastmcp dependency is unbounded** (`fastmcp>=0.1.0`). The probe
   resolved fastmcp 4.0.3, which already carries compatibility shims for the
   mcp SDK v2 rename; any future major can land silently.

Process gaps discovered alongside:

5. **F4 — no test exercises a live serve.** The plugin's tests use fake
   descriptors/apps and never start a server. F1 shipped because of it; the
   no-parameters branch was fixed upstream (master) but the parameterized
   branch was not — both regressions are invisible to the current suite.
6. **The examples directory has no grouped-job scenario.** `examples/`
   documents the visibility contract only (`weather_tools/`); nothing shows a
   grouped project being served, which is the configuration F1 breaks.

## Scope

- In scope: `plugins/functualize-mcp` source fixes (F1, F1b, F2), dependency
  bound (F3), tests (F4), examples scenarios, and the plugin's docs where they
  describe the served tool surface.
- Out of scope: `src/functualize/**` engine changes; NOOA-side changes (its
  dynamic tool factory skips dotted tool names — recorded as a NOOA issue,
  decision: functualize keeps protocol-legal dotted names); new MCP features
  (auth, per-call scope, management tools); upstream functualize asks.

## Behavior (WHAT)

### B1 — Grouped jobs with parameters serve over MCP (F1)

- **B1.1** `func mcp serve` (stdio) in a project whose jobs live under
  `JOB_GROUP` and take typed parameters registers every `visibility="external"`
  job as an MCP tool and stays up to serve calls. No traceback, no partial
  registration.
- **B1.2** The MCP tool name for a grouped job is its full functualize name —
  `probe.echo`, not `probe_echo` or `echo` — matching `func mcp schema` and
  `func mcp tools`, which already print dotted names. (Dotted names are legal
  MCP tool names per SEP-986: `[A-Za-z0-9._-]`.)
- **B1.3** A client that lists tools sees the grouped tool with its typed
  parameter schema (`text: string` for the probe's `echo`) exactly as it does
  for an ungrouped job.
- **B1.4** Calling the grouped tool executes the job and returns the
  functualize result envelope (`{"status","return_value","duration_ms"}`),
  identical to ungrouped jobs.
- **B1.5** `visibility="internal"` grouped jobs stay hidden (unchanged
  behavior, must not regress).

### B2 — Tool descriptions cannot break codegen (F1b)

- **B2.1** A job whose docstring/`extra_description` contains triple single
  quotes, backslashes, or other source-hostile text still registers and
  serves. The description appears as the tool's description to clients.

### B3 — Server boots do not phone home or banner (F2)

- **B3.1** Starting the server makes no network request to `pypi.org`.
- **B3.2** Starting the server prints no FastMCP ASCII banner; functualize's
  own logs remain the output contract.
- **B3.3** Operators can still opt into FastMCP's defaults with the
  documented `FASTMCP_*` environment variables; plugin defaults must not
  override an explicit operator setting.

### B4 — fastmcp is bounded (F3)

- **B4.1** `functualize-mcp`'s dependency declares an upper bound excluding
  untested future majors: `fastmcp>=3.4.0,<5.0.0` covers the repo-locked
  3.4.2 and the probe-verified 4.0.3 (the fix's mechanisms — dotted
  fn.__name__ registration, FASTMCP_* settings — verified on both).

### B5 — Regressions are caught (F4)

- **B5.1** A unit test builds the tool function for a dotted grouped job name
  with parameters: no raise; returned function's name is the dotted job name;
  invoking it executes through the app.
- **B5.2** A capability test starts a real server (subprocess, stdio) over a
  project with a grouped parameterized job, connects an MCP client, lists
  tools, and calls the tool end-to-end. This is the test that keeps F1 dead.
- **B5.3** The capability test asserts the grouped tool's parameter schema and
  result envelope.

### B6 — Examples demonstrate the fixed surface

- **B6.1** A new example project under `plugins/functualize-mcp/examples/`
  shows grouped jobs being served over MCP, with jobs exercising: no-arg,
  typed-arg, `visibility="internal"`, and a job whose description contains
  triple single quotes (the F1b case).
- **B6.2** The example carries a test harness that runs against the real
  served surface (same mechanism as B5.2), and the examples README documents
  it and links the scenario.

## Acceptance criteria (executable)

| # | Criterion | Command |
|---|---|---|
| AC1 | F1 reproducer green: serve a grouped parameterized project and call the job over MCP | `uv run pytest plugins/functualize-mcp/tests/ -q` and `uv run pytest plugins/functualize-mcp/examples/ -q` — includes the grouped scenario |
| AC2 | Dotted tool name preserved | capability test asserts tool name `probe.echo`-style in the client's `list_tools` |
| AC3 | No pypi.org request on boot | capability test asserts no `pypi.org` in server stderr/logs (and no banner line) |
| AC4 | fastmcp pinned | `grep fastmcp plugins/functualize-mcp/pyproject.toml` shows `<5` bound |
| AC5 | ruff clean on touched paths | `uv run ruff check plugins/functualize-mcp/src plugins/functualize-mcp/tests plugins/functualize-mcp/examples` |
| AC6 | Root fast tests unaffected | `uv run pytest -x -q --no-header` (root suite does not collect plugin tests) |
