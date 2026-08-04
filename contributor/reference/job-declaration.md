# Job Declaration — `@job` Decorator Reference

**Audience:** contributors working on the discovery/execution pipeline.
**Status:** shipped (stages S0–S5), pending S6 gate.

## 1. Why `@job`

Convention-only discovery (every public function is a job) has three problems:

1. **No opt-out.** Private helpers, test utilities, and internal plumbing are all registered.
   Underscore-prefixing is a naming convention, not a constraint.
2. **Fragmented metadata.** Operational concerns (`deps`, `cache`, `timeout`, `retry`) were
   scattered across separate decorators (`@job_metadata`) and module-level variables
   (`JOB_GROUP`), with no single place to read what a job needs.
3. **No operational vocabulary.** Build tools have a shared language for dependency ordering,
   fingerprinting, guards, and retry. Convention-only had none.

`@job` addresses all three: explicit opt-in, grouped value objects for operational concerns,
and a vocabulary drawn from build-tool practice.

## 2. Usage

### Bare decorator

```python
from functualize.job.decorators import job

@job
def hello(log: Log): ...
```

In **non-strict mode** (default), `@job` is optional — public functions are still discovered.
In **strict mode** (`[discovery] require_job_decorators = ["job"]`), only `@job`-decorated
functions are registered. Strict mode is a permanent opt-in; convention discovery is the
default indefinitely.

### Full keyword arguments

```python
from functualize.job.decorators import job, Deps, Fingerprint, Guards, Exec, Retry

@job(
    name="my-rename",
    group="infra.aws",
    deps=Deps("lint", "test", policy="fail-fast"),
    cache=Fingerprint(sources=["src/**/*.py", "pyproject.toml"], method="sha256"),
    guards=Guards(platforms=["linux"], preconditions=["docker_running"]),
    exec=Exec(timeout=300, retry=Retry(attempts=3), run="when_changed"),
    doc="Provision infrastructure on AWS.",
    tags=["infra", "production"],
)
def provision(sh: Shell, config: ProvisionConfig): ...
```

### Grouped value objects

Operational kwargs are grouped into five typed objects:

| Object | Fields | Defaults |
|--------|--------|----------|
| `Deps` | `*names`, `policy` | `policy="fail-fast"` |
| `Fingerprint` | `sources`, `method`, `key` | `method="sha256"` |
| `Guards` | `platforms`, `preconditions`, `status` | all `None` |
| `Exec` | `timeout`, `retry`, `platforms`, `run`, `silent` | `run="always"` |
| `Retry` | `attempts`, `backoff`, `on` | `attempts=3`, `backoff=2.0` |

## 3. Value Objects Reference

### Deps

```python
Deps(*names: str, policy: Literal["fail-fast", "keep-going"] = "fail-fast")
```

- `names`: job references (same rules as `DepRef` — callable or string, resolved at discovery).
  Unknown names are a boot error.
- `policy`: `"fail-fast"` stops scheduling when any dep fails; `"keep-going"` is Make's `-k` —
  run everything not transitively downstream of a failure.

### Fingerprint

```python
Fingerprint(sources: list[str] | None = None, method: str = "sha256", key: str | None = None)
```

- `sources`: glob patterns for source files. Hashed with the resolved config/args to
  produce a composite fingerprint key (`<job>::<args_hash>::<method>`).
- `method`: hash algorithm.
- `key`: explicit override (bypasses file hashing).

Fingerprints live in the **runtime state store** (`.functualize/state.json`), NOT the
discovery cache. The key includes the resolved config/args hash, so the same job with
different arguments gets different fingerprints.

### Guards

```python
Guards(platforms: tuple[str, ...] | None = None, preconditions: list[str] | None = None, status: list[str] | None = None)
```

Guard pipeline precedence: **platforms → preconditions → status → fingerprint**.

- `platforms`: `sys.platform` prefix match (e.g. `"linux"`, `"darwin"`, `"win"`).
- `preconditions`: registered precondition names (session-cached in the state store).
- `status`: named status checks (TBD).
- `fingerprint`: checked after status (truthy guard ANDs with staleness — R10a).

Three outcome states: neutral-skip, satisfied-skip, error. Plus `BLOCKED(awaiting=Model)`
for gates.

### Exec

```python
Exec(timeout: float | None = None, retry: Retry | None = None, platforms: tuple[str, ...] | None = None,
     run: Literal["always", "once", "when_changed"] = "always", silent: bool = False)
```

- `run`: `"always"` (default), `"once"` (dedupes within a session), `"when_changed"` (
  dedupes only with identical resolved args — `build(target="wheel")` ≠ `build(target="sdist")`).
- `timeout`: best-effort. Enforceable for `Shell` calls (subprocess killed); advisory for
  pure Python (thread runs to completion in background).

### Retry

```python
Retry(attempts: int = 3, backoff: float = 2.0, on: tuple[type[Exception], ...] = (Exception,))
```

## 4. Discovery Integration

`@job` sets `__functualize_job__` dunder on the decorated function. Discovery:

1. AST scan identifies qualifying modules
2. On import, checks `__functualize_job__` to decide registration
3. In strict mode, functions without `__functualize_job__` are skipped
4. Cache serializes `JobDescriptor` with all `@job` metadata

The `JobDescriptor` carries `group`, `deps`, `fingerprint`, `guards`, `exec`, `retry`,
`tags`, `doc` — all from the decorator. Discovery cache is **import-free** (rows built
from cache without importing job modules).

## 5. Strict Mode

```toml
[discovery]
require_job_decorators = ["job"]
```

- **What it enforces:** only `@job`-decorated functions are registered.
  Non-decorated public functions produce a "forgot @job" warning (error under strict mode).
- **Permanent opt-in** — convention discovery is the default indefinitely.
- **Module-granular today** (the filter applies per module; function-granular enforcement
  ships with Phase 1).

## 6. Plugin Extensibility

Plugins ship their own typed decorators that attach namespaced dunders:

```python
@job(deps=Deps("lint"))
@rate_limit("10/minute")            # sets __functualize_ext_rate_limit__
def deploy(sh: Shell): ...
```

Discovery merges all `__functualize_ext_*` attributes into
`JobDescriptor.metadata["plugins"]`. Rules:

- Identity-preserving (decorators do not change the function's identity)
- Namespaced dunders (`__functualize_ext_<plugin_name>__`)
- JSON-serializable values
- Order-independent
- Boot-time validatable

Boot **warns** when `__functualize_ext_*` has no matching loaded plugin; errors under
`strict_plugins = true`.

## 7. Relationship with `@workflow`

`@workflow` is narrowed to **topology only** — it declares sequencing, routing, and pause
points *between* jobs. The full vocabulary is five names: `Step`, `Gate`, `Edge`,
`ConditionalEdge`, `END`.

- `@job` supplies identity, grouping, and AI metadata.
- `@workflow` contributes only `__workflow_def__`.
- Both compile into the **same internal graph representation** (one engine rule).
- Workflows chain and nest as ordinary jobs: `Deps(wf)`, `FromJob[wf]`, `Step(wf)`.

See [`workflow-walker.md`](./workflow-walker.md) for the full walker semantics.
