---
name: doc-verify
description: >
  Verify that documentation code blocks (commands, expected output) are correct
  by running them in isolated environments. Scenarios reference the exact doc
  file, line range, and code block being tested, enabling agents to detect drift
  and humans to see exactly what is verified. NOT for writing automated CI tests
  — those remain in the pytest suite.
---

# Doc-V: Documentation Verification via Scenarios

You are maintaining a pact between the docs and the code. Every N months,
someone changes a CLI flag, a default value, or a workflow step, and the docs
go stale. This skill runs the commands documented in `docs/*.md` against real
environments and reports which ones still match reality.

## Hard rules

1. **Scenarios test what users read.** Each scenario maps to a specific doc
   page, line range, and code block. If a doc changes, the scenario fails
   until updated. This is the feature, not a bug.
2. **Never import scenario files from pytest.** They live in `examples/docs/`
   and are run by `run-scenario`, not collected by the test suite.
3. **Never install system packages on the host.** All destructive/install tests
   run in containers. PTY tests use the pyte probe (already validated).
4. **Report, don't fix.** When a scenario fails, describe the drift — exact
   expected vs actual. Do not silently update the scenario to match the new
   behavior. That decision belongs to a human.
5. **A skipped scenario is an unverified doc page, never a pass.** `--engine`
   and `--skip-pty` mark non-matching steps `skip`, and a scenario whose steps
   all skip rolls up to `skip`. That is exit **3**. Do not reach for
   `--allow-skips` to make a run green — reach for it only when the narrowing
   is the point (per-PR CI is the one standing case, and it says so in
   `ci.yml`). Where each engine must actually run:

   | Engine | Runs where |
   |---|---|
   | `shell` | per-PR CI (`ci.yml` `doc-verify` job) |
   | `docker` | release gate Phase 4 only — no automated job exists yet |
   | `pty` | local / release gate only — never automated CI (`CLAUDE.md:11`) |

6. **Before believing a doc-verify failure, prove the harness works.** Run
   `a-core-builtins` first — it exercises the plumbing and nothing else. A run
   that reports many failures at once is far more likely to be one broken
   precondition than a documentation set that went stale all at the same
   moment. This audit's first run reported **twelve** doc failures that were a
   single missing `PATH` entry.

---

## Preconditions — both of these, every time

Neither is optional and neither announces itself: get either wrong and the
harness reports environment noise in the vocabulary of documentation drift.

**1. `.venv/bin` must be on `PATH`.** Shell steps invoke `func` as a plain
command. Without the virtualenv on `PATH` every step exits **127** and each one
is reported as a failed documentation assertion.

```bash
PATH="$PWD/.venv/bin:$PATH" python .agents/skills/doc-verify/scripts/run-scenario ...
```

**2. Run from the repository root.** A shell step's `cwd` is resolved
*process-relative*: `run-scenario:132` does `Path(step["cwd"])` with no `ROOT`
join, unlike the pty engine at `:283`, which does `ROOT / step["cwd"]`. A
scenario declaring `cwd = "examples/standalone/secrets_lab"` therefore resolves
only when `run-scenario` is invoked from the root. Started anywhere else, the
directory is not found and the steps fail for a reason that has nothing to do
with the doc they cite.

**A third, for anyone running the suite locally**: `uv sync --all-packages`,
`uv sync --all-extras` and `uv sync --group docs` each prune what the others
install. Each CI job has its own environment so each flag is right there, but a
local run needs all three at once —
`uv sync --all-packages --all-extras --group docs` — or scenarios fail on
missing packages and report it as documentation drift.

The proof that both are satisfied:

```bash
PATH="$PWD/.venv/bin:$PATH" python .agents/skills/doc-verify/scripts/run-scenario \
    examples/docs/scenarios/a-core-builtins.toml
```

It must report `Passed 1`. If it does not, stop — nothing else in the run means
anything yet.

---

## Phase 0 — Quick Reference

| Question | Answer |
|---|---|
| Where do scenarios live? | `examples/docs/scenarios/*.toml` |
| How do I run one? | `python .agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/name.toml` |
| How do I run them all? | `python .agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/` |
| What format? | TOML (see [templates/scenario.toml](templates/scenario.toml)) |
| How do I create a new one? | Copy template, fill in `[source]` block, write steps |
| How do I know what to verify? | See [references/doc-audit.md](references/doc-audit.md) |
| What engines are available? | `shell`, `docker`, `pty` (TUI/CLI interaction) |
| What happens on failure? | Runner exits **1** for a failed step, **2** for a scenario it could not load, **3** when a scenario ran zero steps; writes `.err` diff, prints report. Any non-zero means the run is not clean — gating on `== 2` alone passes every real documentation failure |
| A scenario "skipped" everything? | That is exit **3**, not a pass. `--engine`/`--skip-pty` filter steps out; a scenario left with none verified nothing. The report's **NOT VERIFIED** table names each one and the tier that owes it. Pass `--allow-skips` only to narrow a run deliberately |

---

## Phase 1 — Audit: What needs verifying?

Read [references/doc-audit.md](references/doc-audit.md), then survey the docs
for verifiable code blocks. A block is **verifiable** if it:

1. Contains a shell command (`bash`, `sh`, `console`, `shell` fence)
2. Has deterministic output (no `curl` to external APIs, no random IDs)
3. Can be isolated enough to not affect the host

**Skip**: code blocks that are purely illustrative, reference-only snippets,
Python code (those go in pytest), or configuration file examples.

For each candidate, produce a `source` reference:

```toml
[source]
file = "docs/getting-started/installation.md"
lines = "22-24"
description = "pip install functualize, then verify with --version"
```

When you find a candidate, also note **dependencies**: does this block need
a wheel to be built first? A specific Python version? Network access?

---

## Phase 2 — Create a scenario

1. Copy [templates/scenario.toml](templates/scenario.toml) to
   `examples/docs/scenarios/<descriptive-name>.toml`

2. Fill in the `[source]` block with the exact doc file, line range, and
   description. This is the traceability anchor — if the doc moves, the
   scenario fails until the source reference is updated.

3. Choose your steps. Each step is a `[[steps]]` array entry.

### Step types

| Type | Engine | When to use |
|---|---|---|
| `shell` | `shell` | Simple command, output can be captured as text |
| `docker` | `docker` | Installation, destructive ops, fresh environment |
| `pty` | `pty` | TUI interaction, TTY-dependent output, interactive prompts |

### Shell step
```toml
[[steps]]
engine = "shell"
description = "Show help text"
command = "func --help"
expected = { stdout_contains = "Usage:", exit_code = 0 }
timeout = 5
```

### Docker step
```toml
[[steps]]
engine = "docker"
description = "Install from wheel in clean container"
image = "python:3.11-slim"
build_wheel = true            # builds dist/*.whl first, mounts into container
command = "pip install /dist/*.whl && functualize --version"
expected = { stdout_contains = "functualize", exit_code = 0 }
timeout = 120
```

### PTY step (TUI/CLI interaction)
```toml
[[steps]]
engine = "pty"
description = "TUI SmartBar recognizes 'ping' and shows green bar"
cwd = "examples/standalone/showcase"
command = "uv run func"
cols = 100
rows = 30
actions = [
  { type = "wait", text = "Type a command", timeout = 20 },
  { type = "send", keys = "ping" },
  { type = "wait", text = "● Ready" },
  { type = "snap", label = "ping-recognized" },
]
```

### Multi-step (sequence inside a step)
```toml
[[steps]]
engine = "shell"
description = "Scaffold, add job, run it"
steps = [
  { command = "cd /tmp/test && func scaffold myapp", expected = { exit_code = 0 } },
  { command = "cd /tmp/test/myapp && func sample run", expected = { stdout_contains = "hello-world", exit_code = 0 } },
]
```

### Expected assertions

| Field | Type | Meaning |
|---|---|---|
| `exit_code` | int | Exact exit code expected |
| `stdout_contains` | str | Substring must appear in stdout |
| `stderr_contains` | str | Substring must appear in stderr |
| `stdout_regex` | str | stdout must match this regex |
| `stderr_empty` | bool | stderr must be empty |
| `stdout_not_contains` | str | Substring must NOT appear in stdout |

At least one assertion is required per step. Combine as needed.

### Environment variables
```toml
[[steps]]
engine = "shell"
command = "func forecast --city Tokyo"
env = { ENVIRONMENT = "prod", FORECAST_API_URL = "https://api.staging.example.com" }
expected = { exit_code = 0 }
```

### Dependencies between scenarios
```toml
requires = ["installation"]   # this scenario needs the installation scenario to have built the wheel
```

4. After filling in the scenario, run it locally to verify it passes:

```bash
python .agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/my-scenario.toml
```

If it fails, the runner prints a unified diff (expected vs actual). Fix the
scenario or, if the doc is wrong, flag it in the report.

---

## Phase 3 — Run a scenario (or all of them)

### Run one
```bash
python .agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/installation.toml
```

### Run all
```bash
python .agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/
```

### Run all matching a pattern
```bash
python .agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/ --match "tui-*"
```

### Run with specific engine override
```bash
python .agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/ --engine docker
```

Options:
- `--timeout N` — default timeout for steps that declare none (seconds, default
  120). It is a default, not an override: a step declaring its own `timeout` wins,
  so a run cannot be shortened from the command line.
- `--engine X` — force engine (`shell`, `docker`, `pty`)
- `--match GLOB` — only run scenarios matching glob pattern
- `--keep-containers` — don't remove Docker containers after test (for debugging)
- `--json FILE` — write JSON report to FILE
- `--skip-pty` — skip PTY steps (useful in non-TTY environments like CI)

---

## Phase 4 — Report formats

### Interim report (agent mid-work)

When an agent is running multiple scenarios and needs to report progress,
emit a structured interim report. This is **generated by the runner** when
run with `--report interim`:

```yaml
# Written to /tmp/doc-verify-interim.yaml
run_id: "ses_abc123_2026-07-25T14:30:00"
status: "partial"           # partial | complete
total_scenarios: 12
completed: 5
passed: 4
failed: 1
skipped: 0

scenarios:
  - name: "installation"
    source: "docs/getting-started/installation.md:22-24"
    status: "pass"
    duration: 12.3
    engine: "docker"

  - name: "quickstart-mode1"
    source: "docs/getting-started/quickstart.md:17-28"
    status: "fail"
    duration: 5.1
    engine: "shell"
    failure:
      step: 2
      expected: "stdout_contains: Starting deployment"
      actual: "(empty stdout)"
      diff: |
        --- expected
        +++ actual
        @@ -1 +0,0 @@
        -Starting deployment

  - name: "tui-smartbar"
    source: "docs/cli/inline-tui.md:14-24"
    status: "running"
    engine: "pty"

remaining:
  - "config-layers"
  - "scaffold-init"
  - "mcp-serve"
  # ... etc
```

### Final report (human-readable)

After all scenarios complete, produce this markdown report:

```markdown
# Doc Verification Report — 2026-07-25 14:35

## Summary

| | Count |
|---|---|
| Total scenarios | 12 |
| Passed | 10 |
| Failed | 1 |
| Skipped | 1 |
| Duration | 4m 23s |

## By doc page

| Doc | Scenarios | Status |
|---|---|---|
| `docs/getting-started/installation.md` | 3 | ✅ All pass |
| `docs/getting-started/quickstart.md` | 2 | ❌ 1 failed |
| `docs/cli/inline-tui.md` | 1 | ✅ Pass |
| `docs/guides/configuration.md` | 2 | ✅ All pass |
| `docs/guides/modes.md` | 2 | ⏭️ 1 skipped |
| `docs/cli/scaffold.md` | 1 | ✅ Pass |
| `docs/guides/mcp.md` | 1 | ⏭️ 1 skipped |

## Failures

### ❌ `quickstart-mode1` — `docs/getting-started/quickstart.md:17-28`

**Step 2**: `func jobs.py deploy`
- **Expected**: stdout contains "Starting deployment"
- **Actual**: `Error: No module named 'functualize'`
- **Likely cause**: Doc says `pip install functualize` first (line 13),
  but the scenario runs in a clean container. The installation step (line 13-15)
  must be part of the scenario, or the scenario should declare it as a dependency.
- **Fix**: Add `src/dependency` block to the doc or split the scenario into
  installation + usage phases.

## Skipped

| Scenario | Reason |
|---|---|
| `mcp-serve` | Requires MCP client (anthropic key not configured) |

## Drift warnings

| Doc page | Line | Issue |
|---|---|---|
| `docs/guides/configuration.md` | 87 | Code block says `config.base.ini` but file is now `config.base.toml` |
```

### Key: always check for drift

After running scenarios, look at the gap between "what the doc says" and "what
the code does." Report drift even for scenarios that pass (misleading docs that
happen to still work). The runner cannot detect this — you must compare:

- Doc command → actual CLI flag names
- Doc expected output → actual output format
- Doc file paths → actual file paths in the repo
- Doc option defaults → actual defaults in code

---

## Cross-reference: Tools this skill uses

| Tool | File | Purpose |
|---|---|---|
| Scenario runner | `scripts/run-scenario` | Parses TOML, orchestrates engines, asserts, reports |
| PTY probe | `.agents/skills/observe-tui/scripts/tui_probe.py` | TUI/CLI screen capture and key driving |
| Docker/Podman | System `docker` or `podman` | Ephemeral container environments |
| Python docker-py | `import docker` | Programmatic container management |

## Dependencies

- Python 3.11+ (stdlib `tomllib` for TOML parsing)
- `docker` or `podman` for container-based steps
- `pyte` + `ptyprocess` for PTY steps (pulled via `uv run --with pyte`)
- `docker-py` (already installed, `pip install docker` if missing)

All other dependencies are stdlib.

## Templates and references

| File | Purpose |
|---|---|
| [templates/scenario.toml](templates/scenario.toml) | Copy this to create new scenarios |
| [references/format-spec.md](references/format-spec.md) | Complete format reference for scenario authors |
| [references/doc-audit.md](references/doc-audit.md) | How to audit docs for verifiable code blocks |
