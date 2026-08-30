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

The build only re-runs when its source files change. The fingerprint includes the
file hashes and the job's resolved config, plus any arguments **the caller
passed** — the same job with different arguments gets different fingerprints.
Framework-injected parameters (`Log`, `Shell`, `Sources`, …) are excluded: they
are not part of the call's meaning, and a live object's `repr` is not stable
between processes.

Two behaviours worth knowing before you rely on this:

- **A declared output that is missing forces a run.** `generates` is part of the
  freshness question, not decoration — a job is not up to date if the artifact
  it promised to produce is not there.
- **Declared inputs that resolve to *nothing* refuse the run** (exit **3**),
  rather than reporting "0 sources unchanged, up to date". A stage cannot
  certify success having verified nothing. Declaring *no* sources is different
  and is unaffected.

### Reading the inputs you declared

The glob you declare is expanded on every run to decide freshness. Read the
result rather than restating it:

```python
from functualize.job import Fingerprint, Sources, job

@job(cache=Fingerprint(sources=["src/**/*.yaml"], generates=["out/parsed.json"]))
def parse(sources: Sources) -> None:
    for path in sources.keys():           # project-relative POSIX paths
        text = Path(path).read_text()
    entry = sources["src/app.yaml"]        # {"mtime": float, "size": int, "sha256": str}
```

Restating the glob in the body is how the freshness check and the work drift
apart. `sources.declared` tells "declared no sources" apart from "declared
sources that matched nothing"; `sources.generates` carries the declared outputs.
See [ADR-012](https://github.com/raicing-ai/functualize/blob/master/contributor/adr/012-resolved-sources.md).

### With guards

```python
from functualize.job.decorators import job, Guards

@job(guards=Guards(platforms=["linux", "darwin"], preconditions=["docker_running"]))
def deploy_docker(sh: Shell):
    sh(["docker", "compose", "up", "-d"])
```

Guards are checked before dependencies. The pipeline is: **platforms →
preconditions → status → fingerprint**. If Docker isn't running the job
**refuses** immediately — `RunStatus.REFUSED`, exit **3** — rather than failing
after an opaque error from the shell. Exit 3 is distinct from exit 1 on purpose:
nothing ran and nothing raised, so a caller can tell "I declined to start" from
"the body threw".

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

`func build` emits NDJSON; `jq` processes it. The exit code table propagates
through the pipeline:

| Code | Meaning |
|---|---|
| 0 | success — **and skipped**: a guard saying "nothing to do" did what was asked |
| 1 | the job body raised |
| 2 | usage or config error |
| 3 | **refused** — a declared precondition for running was not met: a `Precondition` failed, or `Fingerprint(sources=…)` resolved to no files |
| 4 | stale-check failure (`--check`) |
| 5 | blocked awaiting gate input — ran successfully and is resumable |

3 and 5 are deliberately different: a workflow paused at a gate *ran* and can be
resumed; a refusal never started. The same code for both would force every
caller to parse stderr.

## See Also

- [Shell Capability Guide](shell.md) — running external commands with lifecycle management
- [Workflows Guide](workflows.md) — multi-step DAGs with gates and conditional branching
