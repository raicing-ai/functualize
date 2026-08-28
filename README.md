# Functualize

[![CI](https://github.com/raicing-ai/functualize/actions/workflows/ci.yml/badge.svg)](https://github.com/raicing-ai/functualize/actions/workflows/ci.yml)
[![Docs](https://github.com/raicing-ai/functualize/actions/workflows/docs.yml/badge.svg)](https://github.com/raicing-ai/functualize/actions/workflows/docs.yml)
[![Python Versions](https://img.shields.io/pypi/pyversions/functualize)](https://pypi.org/project/functualize/)
[![PyPI version](https://badge.fury.io/py/functualize.svg)](https://pypi.org/project/functualize/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/raicing-ai/functualize/blob/master/LICENSE)
[![Typing: Typed](https://img.shields.io/badge/typing-typed-blue.svg)](https://peps.python.org/pep-0561/)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()

> Drop-in CLI framework for Python — auto-discovery, dependency injection, layered config, workflow graphs, and a plugin ecosystem.

A reusable Python CLI framework with auto-discovery, structured execution context, layered configuration, workflow graphs, and a plugin ecosystem.

## Why Functualize?

Most CLI frameworks give you argument parsing and stop there. Functualize provides the full application lifecycle:

- **No boilerplate discovery** — drop a file in a directory and it becomes a command
- **Dependency injection** — declare what your job needs via type annotations, the framework wires it
- **Config without ceremony** — layered resolution means the same job works locally, in CI, and in production
- **Workflow orchestration** — DAGs with conditional edges and gates, not just sequential scripts
- **Pluggable everything** — swap state backends, add adapters (HTTP, Lambda, MCP), extend via entry points

If you're building internal tooling, deployment pipelines, or any multi-step automation that outgrows a shell script, Functualize gives you structure without locking you into a monolith.

## Features

- **Auto-discovery** — Drop job files into a directory and they're automatically registered as CLI commands. Six configurable filters control what qualifies.
- **Job Groups** — `JOB_GROUP` organizes commands into hierarchies (`func infra deploy`). `GroupOptions` declare flags shared by every job under a group.
- **`@job` decorator** — Declare metadata, visibility, dependencies, caching, and matrix parameterization on any job function.
- **Structured RunContext** — Capability-based execution: `Log`, `Invoke`, `Prompt`, `Perf`, `State`, plus `FromJob` for declarative dependency injection and `FromStep` for binding a gate tool to an earlier step's result.
- **Layered Configuration** — Resolution chain with preset strategies (classic, twelve-factor, env-only, remote-first) and `.env` file support.
- **Declarative Job Config** — Pydantic models drive CLI options, config resolution, and TUI form fields.
- **Workflow Graphs** — DAGs with `Step(func)`, `Gate(name, awaits=Model, strategy=...)`, and `Edge`. Gates block for human or AI input; `--prompt-gates` resolves them inline, `--scope-id` resumes blocked scopes.
- **Domain SDK Architecture** — Pluggable capability domains (state, AI, tasks, interactivity) with swappable provider backends.
- **Plugin System** — Extend via Python entry points: lifecycle hooks, CLI commands, dynamic jobs, adapter plugins, and format providers.
- **Built-in commands** — `func builtin parallel` (concurrent jobs), `func builtin history` (run log), `func builtin env` (config as env vars), `func builtin shell-init` (shell completions), `func builtin workflow` (inspect and resume gates).
- **Pinned exit codes** — Stable, documented codes: `0` success · `1` job raised · `2` usage/config error · `3` refused pre-flight · `4` stale check · `5` blocked awaiting gate input.
- **Standalone Mode** — Run single-file jobs with `func file.py function`, or make them self-executing with PEP 723 shebang scripts (`#!/usr/bin/env -S func`).
- **Inline TUI** — Bare `func` opens a smart command shell under your prompt: SmartBar readiness colors, autocomplete, and config panels showing where every value comes from (via `functualize[cli]`).
- **Scaffold Generator** — Bootstrap new projects, jobs, plugins, and TUI screens with `func builtin scaffold`.
- **Testing Utilities** — `TestRunContext`, `CapturingLog`, `MockInvoke`, and other test doubles for unit testing jobs in isolation.

## Installation

Install the `func` CLI globally:

```bash
# With uv (recommended — isolated install, auto-manages PATH)
uv tool install "functualize[cli]"

# Or with pipx
pipx install "functualize[cli]"

# Or with pip (into current environment)
pip install "functualize[cli]"
```

Verify:

```bash
func builtin version
# Or use the longer alias:
functualize builtin version
```

Both `func` and `functualize` are the same command — use whichever you prefer.

> **Adding to a project** (as a library dependency): use `uv add functualize` or `pip install functualize` inside your project instead. The core library has no CLI dependencies — add `functualize[cli]` only if your project uses the `func` CLI or TUI.

### How `func` finds jobs

The CLI operates in two modes:

| Command | Mode | Description |
|---------|------|-------------|
| `func file.py [function]` | Single-file | Run a specific file directly |
| `func <job_name>` | CWD discovery | Find and run a job by name from the current directory |
| `func` (no args) | Discovery | List all discovered jobs |

#### What makes a `.py` file invocable?

A Python file qualifies as a job module when **both** conditions are met:

1. **Filename is not underscore-prefixed** — files like `_helpers.py` or `__main__.py` are skipped
2. **Contains at least one public top-level function** — checked via AST parsing (fast, no import needed)

Once a qualifying file is imported, every **public function** (non-underscore-prefixed, defined in that module) becomes a registered job command. Imported functions, classes, and private `_helper()` functions are ignored.

In **single-file mode** (`func file.py [function]`), the file is imported directly — the same public-function rule applies. If you omit the function name, `func` lists all available functions in the file.

#### Executable scripts (PEP 723)

A script can declare its own entry point and its own dependencies inline, then be run like any other program:

```python
#!/usr/bin/env -S func
# /// script
# dependencies = ["httpx"]
#
# [tool.functualize]
# job = "fetch"
# ///

import httpx


def fetch(url: str, timeout: float = 5.0) -> None:
    print(httpx.get(url, timeout=timeout).text)
```

```bash
chmod +x fetch.py
./fetch.py https://example.com --timeout 2
```

`url` has no default, so it is a positional argument; `timeout` has one, so it is `--timeout`. Same rule as every other job — `./fetch.py --help` shows the resulting usage line.

Two things are doing work here:

- **`[tool.functualize] job`** names the function the file runs. Without it, `func` reads the first argument as a *function name* — fine when you are exploring a file (`func fetch.py fetch`), wrong for a script, where `./fetch.py https://example.com` would look for a function called `https://example.com`. Declaring the job means the file **is** that job, and everything on the command line belongs to it.
- **`dependencies`** is standard PEP 723. If any are missing from the current environment, `func` re-runs the script through `uv run` with them installed. No virtualenv to create, no `requirements.txt` to keep in sync.

`env -S` is what splits `func` from the filename; a plain `#!/usr/bin/env func` also works, since there is nothing to split.

#### CWD discovery

In **CWD discovery mode**, `func` locates job directories in this order:

1. **Explicit config** — `pyproject.toml` `[tool.functualize].jobs_directories`, a `.functualize.toml`, or the global config (`~/.config/functualize/config.toml`)
2. **Convention directories** — a `.functualize/jobs` (plus `lib` and `plugins`) directory, when present
3. **CWD scan** — by default only the current directory itself is scanned for qualifying `.py` files. Opt in to a deeper scan with `func --discovery-depth N` (0–5 levels) or persist it in config:

```toml
# pyproject.toml (optional — scan subdirectories for jobs)
[tool.functualize.discovery]
scan_depth = 2
```

Skipped directories: `.venv`, `__pycache__`, `.git`, `node_modules`, `dist`, `build`, and any dot-prefixed directory.

Skipped files: `test_*.py`, `*_test.py`, `conftest.py`, `setup.py`, and `__init__.py`.

```toml
# pyproject.toml (optional — explicit job directories)
[tool.functualize]
jobs_directories = ["src/myapp/jobs", "scripts"]
```

## Quick Start

Functualize scales from a single script to a full framework project. Start simple, graduate when you need more.

### Step 1: Run a Python script

Write a function, run it with `func`. No project setup, no config files.

```python
# weather.py
from functualize.job import RunContext

def forecast(rc: RunContext):
    """Check today's weather forecast."""
    rc.log("Fetching forecast...")
    rc.log("Tomorrow: 24°C, sunny")
```

```bash
# Run a function directly
func weather.py forecast
```

> Runnable code: [`examples/quickstart/step1_basic/`](examples/quickstart/step1_basic/)

### Step 2: Add typed configuration

Same domain, but now with validated parameters. Pydantic models become CLI options automatically:

```python
# weather.py
from pydantic import BaseModel, Field
from functualize.job import RunContext

class ForecastConfig(BaseModel):
    city: str = Field(description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")
    api_url: str = Field(default="https://weather.example.com", description="Weather API endpoint")

def forecast(config: ForecastConfig, rc: RunContext) -> str:
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    rc.log(f"Using API: {config.api_url}")
    result = f"{config.city}: 24°C, sunny for the next {config.days} days"
    rc.log(result)
    return result
```

Config fields resolve from multiple sources (highest priority first):

```bash
# 1. CLI flags
func weather.py forecast --city Tokyo --days 5 --api-url https://api.prod.example.com

# 2. Environment variables (JOBNAME_FIELD convention)
export FORECAST_API_URL=https://api.staging.example.com
func weather.py forecast --city Tokyo

# 3. Config file (if a config.base.toml exists in the directory)
# [forecast]
# api_url = https://weather.example.com
# days = 3
```

**Auto-discovery:** When you have multiple job files, put them in a `jobs/` directory and point `func` at it once in `pyproject.toml`:

```
myproject/
├── pyproject.toml
└── jobs/
    ├── weather.py
    └── deploy.py
```

```toml
# pyproject.toml
[tool.functualize]
jobs_directories = ["jobs"]
```

```bash
cd myproject
func              # Lists all discovered jobs
func forecast     # Runs the forecast job directly (no filename needed)
```

> No `pyproject.toml`? A one-off `func --discovery-depth 1` scans one directory level below the CWD instead.

> Runnable code: [`examples/quickstart/step2_config/`](examples/quickstart/step2_config/)

### Step 3: Invoke jobs with phase tracking

Jobs can invoke other jobs with `rc.invoke()`. Track progress with `rc.track_phase()`:

```python
# weather.py
from pydantic import BaseModel, Field
from functualize.job import RunContext
from functualize.types import RunStatus

class ForecastConfig(BaseModel):
    city: str = Field(description="City to check")
    days: int = Field(default=3, ge=1, le=7, description="Days to forecast")
    api_url: str = Field(default="https://weather.example.com", description="Weather API endpoint")

def forecast(config: ForecastConfig, rc: RunContext) -> str:
    rc.log(f"Fetching {config.days}-day forecast for {config.city}...")
    return f"{config.city}: 24°C, sunny for the next {config.days} days"

def alert(config: ForecastConfig, rc: RunContext):
    """Check forecast and send alerts if needed."""
    rc.log("Checking alert conditions...")
    rc.log("No severe weather — all clear")

def morning_report(config: ForecastConfig, rc: RunContext):
    """Run the full morning weather pipeline."""
    rc.track_phase("forecast", "Fetching forecast", RunStatus.RUNNING)
    rc.invoke("forecast", city=config.city, days=config.days)
    rc.track_phase("forecast", "Forecast retrieved", RunStatus.SUCCESS)

    rc.track_phase("alerts", "Checking alerts", RunStatus.RUNNING)
    rc.invoke("alert", city=config.city)
    rc.track_phase("alerts", "Alerts checked", RunStatus.SUCCESS)

    rc.log("Morning report complete")
```

```bash
func weather.py morning_report --city Tokyo --days 5
```

Install the flow-viz plugin to see a live execution tree — zero code changes to your jobs:

```bash
pip install "functualize[cli]" functualize-flow-viz
```

```
⏳ morning_report
├─ ✓ forecast — Forecast retrieved (0.1s)
├─ ✓ alerts — Alerts checked (0.1s)
└─ ✓ morning_report (0.3s)
```

The plugin subscribes to `invoke_start`, `invoke_end`, and `phase_change` events automatically — rendering phase status, durations, and nested invocations without touching job code.

> Runnable code: [`examples/quickstart/step3_invoke/`](examples/quickstart/step3_invoke/)

### Step 4: Browse and run jobs interactively

As your `jobs/` directory grows, stop memorizing names and flags. Run bare `func` in a terminal and the **inline TUI** opens — a smart command shell rendered under your prompt (not fullscreen):

```bash
cd myproject
func
```

- **SmartBar readiness** — the command bar's border tells you the state at a glance: grey (no job) → yellow **PENDING** (required args missing) → green **READY** (executable) → red **INVALID**
- **Tab** — autocomplete job names, flags, and values (enum choices complete after a trailing space)
- **Ctrl+Enter** — execute in place; log output streams below the bar, and the shell scrollback stays intact
- **Ctrl+R** — the config panel ring: every config field with its effective value *and where it came from* (CLI flag, env var, config file, or default)
- **Ctrl+E** — the general ring: browse all discovered jobs and TUI settings

Requires the CLI extra (`pip install "functualize[cli]"`). Inline rendering works on Linux/macOS; on Windows, Textual falls back to a fullscreen driver. See the [Inline TUI reference](https://raicing-ai.github.io/functualize/cli/inline-tui/) for the complete keybinding tables.

> Runnable code: [`examples/quickstart/step4_tui/`](examples/quickstart/step4_tui/)

### Step 5: Add AI with structured output

If you haven't already, install the CLI extras first:

```bash
pip install "functualize[cli]"
```

Then install the AI domain SDK:

```bash
pip install functualize-ai-pydantic
```

> `functualize-ai-pydantic` pulls in `functualize-ai` (the protocol) automatically. When only one AI provider is installed, it's auto-selected — no config needed.

Set your API key (the PydanticAI provider uses LiteLLM, which supports OpenAI, Anthropic, and others):

```bash
export OPENAI_API_KEY=sk-...
# Or: export ANTHROPIC_API_KEY=sk-ant-...
```

Now add an AI-powered job that uses `rc.invoke()` to call other jobs properly:

```python
# weather.py (add to the same file)
from functualize_ai import AI

class TravelPlan(BaseModel):
    destination: str
    best_days: list[str]
    packing_tips: list[str]

def travel_plan(config: ForecastConfig, ai: AI, rc: RunContext):
    """AI generates a structured travel plan from weather data."""
    # Use invoke to get forecast (goes through lifecycle, hooks, plugins)
    result = rc.invoke("forecast", city=config.city, days=config.days)
    plan = ai.complete(
        f"Create a travel plan for {config.city} based on: {result.return_value}",
        response_model=TravelPlan,
    )
    rc.log(f"Best days: {', '.join(plan.best_days)}")
    rc.log(f"Pack: {', '.join(plan.packing_tips)}")
```

```bash
func weather.py travel_plan --city Tokyo --days 5
```

> Runnable code (works without API keys via `MockAI`): [`examples/quickstart/step5_ai/`](examples/quickstart/step5_ai/)

### Step 6: Expose jobs to AI agents via MCP

Make your jobs callable by external AI agents (Claude, Cursor, Goose) using the MCP protocol:

```bash
pip install "functualize[cli]" functualize-mcp
```

Mark jobs for external visibility with `@job`:

```python
from functualize.job.decorators import job

@job(
    extra_description="Get a weather forecast for a city",
    visibility="external",
    tags=["weather", "safe"],
)
def forecast(config: ForecastConfig, rc: RunContext) -> str:
    ...

@job(
    extra_description="Generate an AI travel plan based on weather data",
    visibility="external",
    tags=["weather", "ai"],
)
def travel_plan(config: ForecastConfig, ai: AI, rc: RunContext):
    ...
```

Serve your jobs as MCP tools:

```bash
func mcp serve
```

**Using with Claude Code:** Add the MCP server to your Claude config:

```json
{
  "mcpServers": {
    "weather": {
      "command": "func",
      "args": ["mcp", "serve"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

Now Claude can discover and call `forecast` and `travel_plan` directly, passing structured config and receiving typed results. Jobs with `visibility="internal"` are hidden from MCP.

> Runnable code: [`examples/quickstart/step6_mcp/`](examples/quickstart/step6_mcp/) — full tool-surface reference in [`plugins/functualize-mcp/examples/`](plugins/functualize-mcp/examples/)

### Step 7: Workflow checkpoints for AI agents

Use declarative workflows with gates to create bounded, multi-turn flows that AI agents can drive:

```python
# weather.py
from functualize.workflow import workflow, Step, Gate, Edge, END
from pydantic import BaseModel, Field

class TripPreferences(BaseModel):
    budget: str = Field(description="Budget level: budget, mid-range, luxury")
    interests: list[str] = Field(description="Travel interests")

@workflow(
    steps=[
        Step(forecast),
        Gate(name="preferences", awaits=TripPreferences,
             tools=["run_job"], strategy="ai_outbound"),
        Step(travel_plan),
    ],
    edges=[
        Edge(source="forecast", target="preferences"),
        Edge(source="preferences", target="travel_plan"),
        Edge(source="travel_plan", target=END),
    ],
)
def trip_planner(config: ForecastConfig, rc: RunContext) -> str:
    """Multi-step trip planning that pauses for AI input."""
    rc.log(f"Itinerary for {config.city} complete.")
    return f"Itinerary ready for {config.city}"
```

The graph is validated at decoration time. Jobs are registered as `Step(func)`; pause points are `Gate(name=..., awaits=Model)`. The decorated function's body is the epilogue — it runs once after the walk reaches `END`.

**Three gate interaction modes:**

| Mode | Flag / Strategy | Behavior |
|------|----------------|----------|
| **Blocked + Resume** | (default) | Walk stops at gate (exit 5). Deposit input via `func builtin workflow resume`, resume via `func --scope-id <id> trip-planner`. Best for scripts, CI, and MCP agents. |
| **Interactive Prompt** | `--prompt-gates` or `strategy="prompt"` | Gate prompts inline on a TTY. Walk completes in one invocation. Falls through to block when piped. |
| **AI Agent** | `strategy="ai_outbound"` | Gate blocks for external AI deliberation via MCP. Agent discovers, inspects state, and deposits input via `resume_gate` tool. |

```bash
# Blocked (default) — two-step: deposit input, then resume
func trip-planner --city Tokyo
# → exit 5: "Blocked: gate 'preferences' in scope 'abc123'"
func builtin workflow resume abc123 preferences --input '{"budget":"mid-range"}'
func --scope-id abc123 trip-planner --city Tokyo

# Interactive — one invocation, gates prompt inline
func --prompt-gates trip-planner --city Tokyo
# → forecast runs → "Budget level?" → "Interests?" → travel-plan runs → exit 0

# AI agent — serve via MCP, agent drives the gate
func mcp serve
# → Claude discovers, inspects state, calls resume_gate, resumes scope
```

When served via MCP (`func mcp serve`), `functualize-mcp` exposes workflow tools that let an AI agent drive paused workflows:

1. **Discover** — `list_active_workflows()` shows paused or running workflows
2. **Inspect state** — `get_workflow_state(id)` shows the current step, pending input model, and available tools
3. **Resume** — `resume_gate(id, {"budget": "mid-range", "interests": ["food", "culture"]})` validates the input against `TripPreferences` and advances the workflow
4. **Continue multi-turn** — each gate creates a natural checkpoint where the agent reflects and decides

This creates bounded AI workflows — the agent operates within defined steps rather than open-ended execution.

> Runnable code: [`examples/quickstart/step7_workflow/`](examples/quickstart/step7_workflow/) — full workflow walkthrough in [`plugins/functualize-mcp/examples/`](plugins/functualize-mcp/examples/)

### Step 8: Scaffold and distribute as a CLI

When your jobs grow into a real project, scaffold and install it as a standalone command:

```bash
func builtin scaffold init weather-app
cd weather-app
uv sync
```

This generates:

```
weather-app/
├── pyproject.toml        # [project.scripts] entry point
├── README.md
├── config.base.toml
├── config.dev.toml
├── config.prod.toml
└── src/weather_app/
    ├── __init__.py
    ├── main.py           # FunctualizeApp wiring
    └── jobs/
        ├── __init__.py
        └── sample_job.py
```

Move your weather jobs into `src/weather_app/jobs/weather.py`. The `pyproject.toml` declares a CLI entry point:

```toml
[project.scripts]
weather-app = "weather_app.main:run"
```

Install it as a global command (no `uv run` prefix needed):

```bash
# Install globally with uv tool (isolated, on PATH)
uv tool install -e .

# Now callable directly
weather-app forecast --city Tokyo --days 5
weather-app travel-plan --city Paris
```

Or with pip:

```bash
pip install -e .
weather-app --help
```

MCP works in project mode too — add `functualize-mcp` as a dependency in your `pyproject.toml`, and the plugin is auto-discovered at boot via entry points:

```bash
weather-app mcp serve
```

The MCP plugin registers its commands (`mcp serve`, `mcp start`, `mcp stop`, `mcp tools`, `mcp list`, `mcp schema`) automatically when installed. Your project's CLI exposes them alongside your job commands.

> Walkthrough: [`examples/quickstart/step8_scaffold/`](examples/quickstart/step8_scaffold/) — the finished project lives in [`examples/project/weather_app/`](examples/project/weather_app/)

For the full progression guide (directory mode, library mode, adapter mode), see the [Modes documentation](https://raicing-ai.github.io/functualize/guides/modes/).

## Layered Configuration

Every `JobConfig` field resolves from multiple sources automatically. Same job, different environments — zero code changes:

```python
# jobs/sync.py
from pydantic import BaseModel, Field
from functualize.job import RunContext

class SyncConfig(BaseModel):
    api_url: str = Field(description="Target API endpoint")
    batch_size: int = Field(default=100, description="Records per batch")
    timeout: int = Field(default=30, description="Request timeout in seconds")

def data_sync(config: SyncConfig, rc: RunContext):
    rc.log(f"Syncing from {config.api_url} (batch={config.batch_size})")
```

Three ways to provide config — they layer with clear priority. The job is
`data-sync`: names are canonical lowercase-hyphenated, derived from the Python
function name (`def data_sync`). Environment variables use underscores because
shells cannot export a hyphen, and a config section is accepted either way:

```bash
# 1. CLI flags (highest priority)
func data-sync --batch-size 2000

# 2. Environment variables (JOBNAME_FIELD convention)
export DATA_SYNC_BATCH_SIZE=500
export DATA_SYNC_API_URL=https://api.prod.example.com

# 3. Config files (base + environment overlay)
# config.base.toml
# [data_sync]
# api_url = "https://api.example.com"
# batch_size = 100
```

Resolution order: **Runtime override → CLI → Env vars → Config file → Model defaults** (an override is a value `rc.config.set()` deposits mid-run). The same job works locally, in Docker, and in production without any code changes — just swap the config source.

Config files use a **base + environment overlay** pattern. The active environment — `FUNCTUALIZE_ENV`, else `ENVIRONMENT`, else `ENV`, defaulting to `dev` — determines which overlay is merged on top of the base (matched case-insensitively):

```toml
# config.base.toml — always loaded
[data_sync]
api_url = "https://api.example.com"
batch_size = 100

# config.prod.toml — merged on top when ENVIRONMENT=prod
[data_sync]
api_url = "https://api.prod.example.com"
batch_size = 500
```

```bash
# Local dev (default) — uses config.base.toml + config.dev.toml
func data-sync

# Production — uses config.base.toml + config.prod.toml overlay
ENVIRONMENT=prod func data-sync
```

| Preset | Strategy | Best for |
|--------|----------|----------|
| `classic()` | CLI → Env → Config files → Defaults | Local dev, desktop tools |
| `twelve_factor()` | CLI → Env → Defaults | Docker, Kubernetes |
| `env_only(dotenv=True)` | CLI → Env → Defaults | Serverless, minimal setups |
| `remote_first()` | CLI → Env → Files → Defaults — **remote resolution is not wired**; see below | — |

> **`remote_first()` does not resolve anything remotely.** The preset exists and is
> exported, but nothing in the shipped package constructs a `RemoteSource`, and
> `remote_first()` returns `config_resolution_chain=None` — which boot turns into the
> classic chain `[CliSource, EnvSource, FileSource, DefaultSource]`. It is `classic()`
> with a different file pattern and `dotenv=False`. Pick it for Vault or AWS Secrets
> Manager and your credentials come from a local file or the environment instead, with
> nothing to say so.

Presets are selected in your project's `main.py` when constructing `FunctualizeApp`:

```python
from functualize.app import FunctualizeApp, JobSources, twelve_factor

app = FunctualizeApp(
    name="weather-app",
    job_sources=JobSources(directories=["weather_app.jobs"]),
    config_sources=twelve_factor(),  # Env-only for Docker/K8s
)
```

> **Note:** When using `func` CLI in single-file mode, the default preset (`classic()`) is always used — presets only apply to scaffolded projects with a `main.py`.

### Environment Variables and `.env` Files

Functualize reads environment variables from `os.environ` during config resolution. A `.env` file can inject values into `os.environ` before resolution runs — controlled by `ConfigSources.dotenv` / `dotenv_path` for apps, and by the resolved CLI config plus `--dotenv-file` / `--no-dotenv` for the `func` CLI:

```bash
# Explicit .env loading — injects into os.environ before config resolution
myapp --dotenv-file .env data_sync

# App boot honors ConfigSources.dotenv (the dataclass default is True):
# a ./.env in the working directory is loaded at boot. Use
# ConfigSources(dotenv=False) or the twelve_factor() preset to disable.
myapp data_sync
```

**Key points:**

- The `ENVIRONMENT` variable (from shell or `.env`) controls which config overlay file is selected. If your `.env` sets `ENVIRONMENT=prod`, the app loads `config.prod.toml` on top of `config.base.toml`
- Shell environment variables always take precedence over `.env` file values (python-dotenv does not override existing vars by default)
- The effective resolution priority: **CLI flags > Shell env vars > `.env` file values > Config files > Model defaults**
- Only the current working directory's `.env` (or an explicit `dotenv_path`) is considered — there is no upward directory scan, so a `.env` in a parent directory is never silently picked up
- The `func` CLI defaults to `dotenv = false`; opt in per project via `[tool.functualize] dotenv = true`, `FUNCTUALIZE_DOTENV=true`, or `--dotenv-file`

Because `.env` is loaded into `os.environ` **before** the config system reads it, `.env` can influence both the config values (via `JOBNAME_FIELD` env vars) and which config files are loaded (via the `ENVIRONMENT` variable).

> **Reproducibility tip:** Automatic `.env` loading can cause hard-to-debug differences between environments. For CI and production, use `twelve_factor()` / `ConfigSources(dotenv=False)` (or `--no-dotenv` on the CLI) so environment variables come only from the orchestrator.

## Extending with Plugins

Plugins are standalone packages that extend any Functualize app via Python entry points. Install one and it's active immediately — no code changes in the host app.

### Writing a plugin

A plugin is a class with metadata attributes and a `__call__(app)` method:

```python
# src/functualize_metrics/__init__.py
class MetricsPlugin:
    name = "metrics"
    version = "1.0.0"
    description = "Emit job execution metrics to StatsD"

    def __call__(self, app) -> None:
        """Called at boot — hook into lifecycle events."""

        @app.before_job
        def on_start(job_name, config):
            statsd.increment(f"job.{job_name}.started")

        @app.on_job_success
        def on_success(job_name, result, duration):
            statsd.timing(f"job.{job_name}.duration", duration)

        @app.on_job_failure
        def on_failure(job_name, error):
            statsd.increment(f"job.{job_name}.failed")
```

Register via entry point in `pyproject.toml`:

```toml
[project.entry-points."functualize.plugins"]
metrics = "functualize_metrics:MetricsPlugin"
```

Once installed (`pip install functualize-metrics`), the plugin is auto-discovered at boot. Every job in every Functualize app gets metrics automatically.

### Registering CLI commands from a plugin

Plugins can add sub-commands to the host CLI:

```python
class DBPlugin:
    name = "db-tools"
    version = "1.0.0"
    description = "Database management commands"

    def __call__(self, app) -> None:
        def migrate(target: str = "head"):
            """Run database migrations."""
            print(f"Migrating to {target}")

        def seed(count: int = 100):
            """Seed sample data."""
            print(f"Seeding {count} records")

        app.register_plugin_command("migrate", migrate, group="db", help_text="Run migrations")
        app.register_plugin_command("seed", seed, group="db", help_text="Seed data")
```

This creates `my-app db migrate` and `my-app db seed` commands.

### Registering dynamic jobs

Plugins can register jobs that become invocable via `rc.invoke()` and visible in the CLI:

```python
class HealthPlugin:
    name = "health-monitor"
    version = "1.0.0"
    description = "Registers a health check job"

    def __call__(self, app) -> None:
        def check_health(config, rc):
            """Check endpoint health."""
            import httpx
            resp = httpx.get(config.endpoint, timeout=config.timeout)
            rc.log(f"Status: {resp.status_code}")

        app.register_dynamic_job(
            name="health-check",
            function=check_health,
            config_class=HealthCheckConfig,
            group="monitoring",
        )
```

Dynamic jobs are fully functional — invocable via `rc.invoke("health-check")`, visible in the TUI, and trigger lifecycle hooks.

### Public API

| Package | Purpose |
|---------|---------|
| `functualize.app` | `FunctualizeApp` constructor, config presets, adapters |
| `functualize.job` | `RunContext`, capabilities (`Log`, `Invoke`, `Prompt`, `Perf`, `State`), `@job` decorator |
| `functualize.plugin` | `EventBus`, `JobProvider`, `AdapterPlugin` |
| `functualize.types` | `JobResult`, `JobDescriptor`, enums |
| `functualize.workflow` | `@workflow`, `Step`, `Gate`, `Edge`, `ConditionalEdge`, `END` |
| `functualize.testing` | `TestRunContext`, `CapturingLog`, `MockInvoke` |

See the [full plugin and extension docs](https://raicing-ai.github.io/functualize/guides/plugins/) for lifecycle hooks, middleware, event bus, custom providers, and more.

## Plugin Ecosystem

Install the full plugin ecosystem with a single command:

```bash
pip install "functualize[all]"
```

| Plugin | Purpose |
|--------|---------|
| `functualize-ai` | Provider-agnostic LLM interaction with budget enforcement and tool scoping |
| `functualize-ai-pydantic` | PydanticAI-backed AI provider with LiteLLM routing and structured output |
| `functualize-flow-viz` | Live inline execution tree visualization with step status and durations |
| `functualize-http` | HTTP delivery adapter exposing jobs as API endpoints via stdlib asyncio |
| `functualize-inline` | Textual-based inline terminal widgets for prompts, selections, and progress |
| `functualize-lambda` | AWS Lambda delivery adapter for serverless job execution |
| `functualize-mcp` | Model Context Protocol adapter exposing jobs as tools to AI agents |
| `functualize-state` | State domain SDK with protocols for key-value persistence and execution tracking |
| `functualize-state-sqlite` | SQLite-backed state persistence and execution history in WAL mode |
| `functualize-tasks` | Task management domain SDK with status tracking and event emission |
| `functualize-tasks-local` | Local state-backed task storage provider for the tasks domain |

Every plugin ships runnable examples in its own folder: [`plugins/<name>/examples/`](https://github.com/raicing-ai/functualize/tree/master/plugins).

For plugin quality tiers and publishing guidelines, see [plugins/PUBLISHING.md](https://github.com/raicing-ai/functualize/blob/master/plugins/PUBLISHING.md).

## Requirements

- Python 3.11+

## Development

```bash
# Clone and install
git clone https://github.com/raicing-ai/functualize.git
cd functualize

# Install tooling (mise manages python + uv versions)
mise install

# Sync dependencies (creates .venv, installs all workspace packages)
uv sync

# Run fast tests (unit only, skips property-based tests)
uv run pytest

# Run full test suite including property-based tests
uv run pytest --run-slow

# Run full suite exactly as CI does (the ci profile draws 200 examples, not 100)
HYPOTHESIS_PROFILE=ci uv run pytest --run-slow --cov=functualize -n auto

# Lint and format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type check
uv run mypy src/

# Architecture enforcement (import-linter)
uv run lint-imports

# Run all pre-commit hooks
uv run pre-commit run --all-files
```

See [CONTRIBUTING.md](https://github.com/raicing-ai/functualize/blob/master/CONTRIBUTING.md) for the full development guide.

## Documentation

```bash
# Install docs dependencies
uv sync --group docs

# Live preview
uv run mkdocs serve

# Build (strict mode catches broken links)
uv run mkdocs build --strict
```

Docs deploy automatically to GitHub Pages on push to `main`.

## Contributing

Contributions are welcome! Please read our [Contributing Guide](https://github.com/raicing-ai/functualize/blob/master/CONTRIBUTING.md) before submitting a PR.

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Make your changes with tests
4. Ensure CI checks pass (lint, type check, tests, import-linter)
5. Open a Pull Request against `master` (the PR title becomes the squash commit — use a [Conventional Commit](https://www.conventionalcommits.org/) subject)

## Changelog

See [CHANGELOG.md](https://github.com/raicing-ai/functualize/blob/master/CHANGELOG.md) for release history and migration notes.

## Security

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## License

[MIT](https://github.com/raicing-ai/functualize/blob/master/LICENSE) © Mohammad Hakim Adiprasetya
