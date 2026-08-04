# Task Runner — `@job`, Dependencies, and Fingerprints

The task runner turns your job functions into build-tool-style targets: declare dependencies, guard execution with preconditions, cache results with fingerprints, and retry on failure.

## Quick Start

### Basic `@job` decorator

```python
from functualize.job.decorators import job
from functualize.job import Log

@job(doc="Deploy the application.")
def deploy(log: Log):
    log("Deploying...")
```

### With dependencies

```python
from functualize.job.decorators import job, Deps

@job(deps=Deps("lint", "test"))
def build(sh: Shell, log: Log):
    log("Building after lint and test pass...")
    sh(["uv", "build"])
```

Deps run first, in dependency order. By default, if any dep fails, downstream jobs are skipped (`Deps.policy="fail-fast"`). Use `Deps(policy="keep-going")` for Make-style `-k` behavior.

### With fingerprint caching

```python
from functualize.job.decorators import job, Fingerprint

@job(cache=Fingerprint(sources=["src/**/*.py", "pyproject.toml"]))
def build(sh: Shell):
    sh(["uv", "build"])
```

The build only re-runs when its source files change. The fingerprint includes both the file hashes and the resolved config/args — the same job with different arguments gets different fingerprints.

### With guards

```python
from functualize.job.decorators import job, Guards

@job(guards=Guards(platforms=["linux", "darwin"], preconditions=["docker_running"]))
def deploy_docker(sh: Shell):
    sh(["docker", "compose", "up", "-d"])
```

Guards are checked before dependencies. The pipeline is: **platforms → preconditions → status → fingerprint**. If Docker isn't running, the job fails immediately rather than after an opaque error from the shell.

## Value Objects Reference

All operational concerns are grouped into typed value objects:

### Deps

```python
Deps("lint", "test", policy="fail-fast")
```

- `policy="fail-fast"` (default): stop on first failure
- `policy="keep-going"`: run everything not downstream of a failure (like `make -k`)

### Fingerprint

```python
Fingerprint(sources=["src/**/*.py", "pyproject.toml"], method="sha256")
```

- `sources`: glob patterns. Hashed with resolved config/args for the composite key.
- `method`: hash algorithm.
- `key`: explicit override (bypasses file hashing).

### Guards

```python
Guards(platforms=["linux"], preconditions=["docker_running", "k8s_connected"])
```

- `platforms`: `sys.platform` prefix match.
- `preconditions`: registered checks (session-cached).
- `status`: named status checks.

### Exec

```python
Exec(timeout=300, retry=Retry(attempts=3), run="when_changed")
```

- `run`: `"always"` (default), `"once"` (deduplicates within a session), `"when_changed"` (deduplicates only with identical resolved args).
- `timeout`: best-effort. Enforceable for shell commands; advisory for pure Python.
- `retry`: `Retry(attempts, backoff, on=(Exception, ...))`.

## Inspecting Why a Job Will Run

```bash
$ func builtin why build

build
  platforms  ✓ linux
  preconditions  docker: ✓
  fingerprint  src/**/*.py: 3 files changed (a.py, b.py, c.py)
  deps  lint ✓ fresh · test ✗ stale → will run first
```

Use `func builtin why` to see guard results, fingerprint freshness, and which dependencies will re-run. On any job run, `--explain` prints the same verdict without executing.

## State Management

The state store (`.functualize/state.json`) holds fingerprints, guard results, and execution history:

```bash
func builtin state clear    # Clear runtime state (fingerprints, history, preconditions)
func cache clear            # Clear discovery cache (job metadata)
```

These are independent — `state clear` doesn't touch the cache; `cache clear` doesn't touch state.

## Parallel Execution

```bash
func builtin parallel lint test typecheck --output grouped
```

Runs jobs concurrently with a bounded thread pool. Output modes:

| Mode | Behavior |
|------|----------|
| `interleaved` | Streams mixed output in real time |
| `grouped` | Buffers per-job output, emits on completion with CI group markers |
| `prefixed` | Each line prefixed with `[job_name]` |

## Pipeline Mode

Jobs with a `Stdout` capability act as Unix pipeline stages:

```bash
func build --output ndjson | jq '.targets'
```

`func build` emits NDJSON; `jq` processes it. The exit code table propagates through the pipeline.

## See Also

- [Shell Capability Guide](shell.md) — running external commands with lifecycle management
- [Workflows Guide](workflows.md) — multi-step DAGs with gates and conditional branching
