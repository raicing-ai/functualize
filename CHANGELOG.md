# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Performance

- **Boot scans installed entry points once instead of seven times.** Constructing
  a `FunctualizeApp` asks seven questions of the same package metadata — plugins,
  domains, the ai/state/tasks provider groups, and the format and remote config
  provider groups — and `importlib.metadata.entry_points()` walks every installed
  distribution on each call, because the group argument filters the result rather
  than narrowing the scan. The seven now share one snapshot taken on first use.
  Measured over 16 interleaved runs on a 215-distribution environment: median
  construction **111.9 ms to 73.3 ms, a 34% reduction**, paid back on every
  surface — CLI, TUI, MCP, and direct run alike. A process that needs to observe
  a newly installed distribution can drop the snapshot with
  `functualize._primitives.entry_points.clear_entry_point_cache()`.

### Fixed

- **A namespaced job was unreachable by the only name it published.**
  `NamespaceTransform` canonicalized the prefix when *writing* names but matched
  the raw spelling when *reading* them, so `NamespaceTransform("my_ns")` listed
  `my-ns.job` and then answered lookups only for `my_ns.job` — the one name it
  advertised was the one name it refused. Matching is now on the canonical
  prefix, with the raw spelling still accepted, so either spelling resolves and
  the published name works. A single-word prefix was already canonical, which is
  why the failure only appeared once a prefix needed normalizing.
- **A multi-word `JOB_GROUP` failed registration outright.**
  `qualified_name` validates the group it is handed as a Python identifier — by
  design, since a non-identifier `JOB_GROUP` is an authoring mistake — but
  `registry.py` and `sync.py` normalized the group *before* passing it, and a
  hyphenated segment is never an identifier. The result was that
  `JOB_GROUP = "data_ops"`, this changelog's own documented example, raised
  `ValueError` at registration. Both call sites now pass the raw group and keep
  the normalized form only for the descriptor's `group` field.
  `NamespaceTransform` was already correct here. Single-word groups such as
  `infra` and `deploy` worked throughout, which is why the fixtures missed it.
- **Config discovery no longer stats every file between the CWD and `$HOME`.**
  `discover_config_path` tested `is_file()` — a syscall — before the two pure
  string predicates that reject almost every entry. Since the walk covers every
  entry of every ancestor directory, a boot from a directory under a busy `/tmp`
  paid roughly 17,000 stats before concluding there was no config file. The
  predicates are pure, so reordering them cannot change which directory is
  chosen.
- `rc.log(...)` now emits through the job's own `Log` capability — the same
  instance an injected `log: Log` parameter receives — instead of writing
  straight to its stdlib logger. A job that logs both ways can no longer end
  up with two different sinks, and anything wrapping `Log` sees both routes.
  A job that never asks for `Log` has no instance to route to, so `rc.log()`
  falls back to the `functualize.job.<name>` logger exactly as before.
  `TestRunContext.captured_logs()` therefore observes `rc.log(...)`; the 0.1.0
  known limitation is lifted.

### Changed

- An invalid `level` passed to `rc.log(...)` now raises `ValueError` (the error
  the `Log` capability already raised) rather than `AttributeError`, and raises
  it before any log callback runs. Levels that stdlib logging accepts but the
  `Log` capability never did — `exception`, `warn`, `fatal` — are rejected
  consistently now instead of depending on which sink was behind the call.
  `CapturingLog` validates levels the same way, so a level production would
  refuse can no longer pass silently in a test.

## [0.1.0] - 2026-08-04

First public release. Functualize turns plain Python functions into jobs that run
from a CLI, an interactive TUI, an MCP server, or another job — without the
function knowing which.

### Jobs and execution

- **Auto-discovery** of job functions by directory scan, with per-function
  qualification rules (`require_job_prefix`, `require_job_postfix`,
  `require_job_decorators`, `require_file_marker`) settable by config file,
  environment variable, or CLI flag. A filtered-out job is unreachable by name,
  not merely hidden from listings.
- **Dependency injection by type annotation** (FastAPI / pytest-fixture style).
  Capabilities: `Log`, `Invoke`, `Prompt`, `Perf`, `Shell`, `State`, `Stdout`,
  `TTY`, `Live`, plus `JobConfigView` and `RunContext` itself.
- **`FromJob`** — declare a parameter as another job's return value. The
  annotation is both the dependency edge and the injection, so there is no second
  place to keep in sync. `FromJob(..., run=False)` reads a recorded value without
  causing work.
- **`@job(...)` declarations**: `Deps`, `Fingerprint`, `Guards`, `Exec`, `Retry`,
  `Precondition`. Fingerprints and guards give skip-if-fresh behavior, and
  `func builtin why <job>` explains any verdict — including a return value with
  no serializable form, which still caches but cannot feed a `FromJob` dependent.
- **Lazy boot is the default.** Warm boot imports zero job modules; invoking a job
  imports exactly that one module. Two consequences worth knowing: a job module's
  import-time side effects run at first invocation rather than at boot, and
  DI-binding errors for warm-cached jobs surface at first use rather than at boot.
  `JobSources(lazy=False)` restores fully eager boot.

### Naming

- **Job and group names are canonical lowercase-hyphenated.** `def data_sync`
  registers, displays, and is invoked as `data-sync`; a grouped
  `JOB_GROUP = "data_ops"` job becomes `data-ops.run-etl`. Python identifiers
  cannot contain hyphens and command names conventionally do, so the same job
  otherwise has two spellings and each consumer picks one.
- **Typing the Python spelling still works** — `func data_sync`,
  `rc.invoke("data_sync")`, and `Deps("data_sync")` all reach `data-sync`. That is
  normalization onto the one real name, not an alias.
- Environment variables keep underscores (`DATA_SYNC_BATCH_SIZE`), since no shell
  can export a hyphen, and config sections are read either way (`[data_sync]` and
  `[data-sync]`).
- Two functions that normalize to one name are rejected at registration instead of
  one silently replacing the other.

### CLI

- `func` / `functualize` entry points, click-native, with single-file, group, and
  CWD-discovery modes. Importing `functualize.app` or `functualize.job` loads no
  CLI dependency.
- **Global flags go before the group name** — `func --log-level DEBUG infra deploy`,
  matching the git idiom. A global flag placed after a group is a clear error with
  a hint, not a silent no-op. Options after the job name belong to the job.
- **First-party commands live under `builtin`**, so no first-party name is a name a
  job cannot have: `cache`, `state`, `config`, `domains`, `scaffold`, `workflow`,
  `parallel`, `history`, `env`, `shell-init`, `why`, `version`, `info`.
- **Group options** — `class DeployOptions(GroupOptions, group="deploy")` declares
  flags every job beneath the group accepts, typed *before* the group segment that
  owns them (`func deploy --env prod web run`). Position is what separates a
  group's flag from the job's own. They resolve as
  `flag > DEPLOY__ENV > [deploy] > default`, identically for `app.execute()` and
  `rc.invoke()`, and appear in MCP tool schemas.
- **Pinned exit codes**: `0` success · `1` the job raised · `2` usage/config error ·
  `3` refused pre-flight · `4` stale check · `5` blocked awaiting gate input. A
  broken pipe (`func generate | head`) exits `0` quietly.
- **Explicit stdout.** A job writes through the injected `Stdout` capability
  (`out.emit` / `out.write`); a return value is programmatic — for `FromJob` and
  callers — and is never auto-printed. `--output json|ndjson|raw|none` selects the
  emit format.
- `sh(...)` splits its channels: the command echo (`$ git status`) goes to stderr
  like `log()`, and `sh(..., stream=True)` sends the command's own output to
  stdout, so `func build | grep …` sees the build output rather than the echo.
- **Executable scripts (PEP 723)** — a script with `#!/usr/bin/env -S func` and a
  `[tool.functualize] job = "…"` table runs as a program, handing its arguments to
  the declared job. `dependencies` in the same block resolve through `uv run`.
- **`func builtin shell-init <bash|zsh|fish>`** emits a static completion script
  containing no `func` call, so TAB has no Python start-up cost.

### Configuration

- Layered resolution (CLI → env → files → remote → defaults) with the presets
  `classic()`, `twelve_factor()`, `env_only()`, and `remote_first()`.
- One Pydantic model per job drives CLI options, TUI form fields, and runtime
  validation.
- **Environment overlays** — `config.base.*` merges beneath the active
  environment's `config.<env>.*`, resolved as
  `FUNCTUALIZE_ENV` > `ENVIRONMENT` > `ENV` > `DEV`. Precedence is
  directory-major, band-minor: the nearest directory wins overall, and within a
  directory the overlay beats base, so the project > parents > global ladder holds.
- `FunctualizeApp.config_files(job_name=None)` reports every discovered file with
  its environment slot, role, merge precedence, and own values. Inactive and
  unparsable files are included on purpose, so a file that plainly exists but is
  not taking effect can be explained rather than omitted.
- **Missing required config is prompted for** on an interactive surface, masked for
  secret fields. Off one (a pipe, CI, MCP) it is a field-level error naming the
  field and the environment variable that sets it, exit 2 — never a hang on a
  prompt nothing can answer.
- Boot-time `.env` loading via `dotenv` / `dotenv_path` (or `FUNCTUALIZE_DOTENV` /
  `FUNCTUALIZE_DOTENV_PATH`), loaded with `override=False` so shell values win.

### Workflows

- `@workflow(steps=..., edges=...)` graphs with conditional edges and **gates** that
  pause for human, AI, or programmatic resolution.
- Persisted scopes are inspectable and resumable from the CLI
  (`func builtin workflow list | state | resume | cancel`, with `--format table|json`)
  and over MCP, through one shared code path so the two surfaces cannot drift.
- A job that is both a dependency and a workflow node runs once per scope, and a
  step whose `Deps` names a node the graph orders *after* it is rejected at boot as
  the contradiction it is.
- A gate inside a nested workflow blocks its parent rather than failing it; the
  child scope is stable across re-entry (`<parent-scope>::<step-name>`).

### Surfaces and TUI

- A job declares where it renders directly in its signature. `tty: TTY` grants
  terminal ownership for a job-owned UI and is refused pre-flight in non-terminal
  contexts (piped, CI, MCP) with an actionable message. `tty: TTY | None` is a
  preference, so one unmodified job renders as a full-screen app or a live view
  depending on the surface. `live: Live` is an always-injected, degrading
  live-display channel.
- **Inline TUI** — SmartBar command input with autocomplete and readiness colors,
  config inspection and editing panels, a job browser, live execution monitoring,
  and a detail view that stages edits (`i`) and removals (`d`) against any writable
  source and writes them atomically (`Ctrl+S`).
- Settings are real and live in the real config files — the same layers
  `resolve_cli_config` merges, so there is no parallel settings file the rest of
  `func` ignores. Invalid values fall through to the next layer instead of breaking
  the TUI.
- Displays co-locate with jobs and are discovered through the job cache.
  `DisplayProvider.refresh()` runs on a worker with a per-provider timeout, so a
  display doing I/O cannot freeze the interface.
- Selecting a `tty: TTY` job in the shell hands the terminal over and relaunches the
  shell afterward.

### Plugins and integrations

- Entry-point plugin system plus zero-packaging `.functualize/plugins/*.py`
  discovery. The `[all]` extra ships 11 first-party plugins: domain SDKs (ai,
  interactivity, state, tasks), implementations (ai-pydantic, inline, state-sqlite,
  tasks-local), delivery adapters (http, lambda, mcp), and flow visualization.
- **MCP** — jobs are exposed as tools with structured group metadata
  (`{"namespace": ["infra", "aws"], "kind": "job"}`), and plugin-declared workflows
  report their real steps and edges. A `requires_tty` job is omitted rather than
  offered and then failed.
- Lifecycle hooks (`HookRegistry`) and observation events (`EventBus`), strictly
  non-overlapping. The event vocabulary is a documented stability contract; framework
  events reach the EventBus only and are filtered out of the surface fan-out.

### Tooling

- `func builtin scaffold init` generates projects, jobs, plugins, screens, and domains.
- `func builtin parallel <job…>` runs jobs concurrently. `--timeout N` bounds the
  batch and `--output interleaved|grouped|prefixed` chooses how concurrent output is
  presented (`grouped` emits GitHub Actions `::group::` / `::error::` markers). The
  per-job summary goes to stderr and the verdict to the exit code, so
  `func builtin parallel a b | jq` sees only what the jobs emitted.
- `func builtin history` shows recent runs newest-first across job runs and shell
  commands. Arguments are stored only as a hash, never in the clear.
- `func builtin env <job>` exports a job's resolved config for tools that are not
  functualize, in print form (`eval $(func builtin env deploy)`) or exec form
  (`func builtin env deploy -- kubectl apply …`, propagating the exit code). Secret
  fields are masked in the print form and omitted from the exec environment unless
  `--include-secrets` is given.

### Testing

- First-class test doubles in `functualize.testing`: `TestRunContext`,
  `CapturingLog`, `MockInvoke`, `AutoPrompt`, `NoopPerf`. Each double subclasses
  the capability it stands in for, so it satisfies the DI registry's type check
  and can be injected anywhere the real capability is accepted.

### Known limitations

- `TestRunContext.captured_logs()` does not observe `rc.log(...)`.
  `RunContext.log()` writes directly to its stdlib logger and never consults the
  DI registry, so messages emitted that way are not recorded and the call returns
  an empty list. Assert on log output by passing the double to the job directly
  (`log = CapturingLog(); my_job(config, log); assert (...) in log.calls`), which
  is the style the scaffolded job template demonstrates. Routing `RunContext.log`
  through the injected `Log` is deferred to a later release.
  *(Fixed after 0.1.0 — see Unreleased.)*

[Unreleased]: https://github.com/raicing-ai/functualize/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/raicing-ai/functualize/releases/tag/v0.1.0
