# Discovery Filtering

Functualize uses a composable filter system to determine which Python files and functions qualify as jobs. Filters are opt-in, stack additively via AND logic, and range from zero-config convention mode to strict decorator-only enforcement.

> **Note:** All discovery settings can be configured via `pyproject.toml`, `.functualize.toml`, global config, environment variables, or CLI flags. See [Configuration](config.md) for the full precedence chain.

## The AND Model

Every enabled filter must pass for a file or function to qualify. Think of filters as a series of gates — a candidate must pass through all of them:

```
File → [GlobExclude] → [FilePrefix] → [FilePostfix] → [Import] → [Marker] → [Decorator]
                                                                                    ↓
                                                                        Function → [JobPrefix] → [JobPostfix] → [JobDecorators] → Registered Job
```

- **File-level filters** determine which `.py` files are considered
- **Job-level filters** determine which functions within qualifying files become jobs
- If no `require_*` filters are configured, baseline convention mode applies

---

## Baseline Convention Mode (Zero Config)

When no filters are configured, all public functions in qualifying files become jobs:

- Files must pass `DefaultModulePreFilter` (no `_`-prefixed filename)
- Files must pass `ASTModulePreFilter` (contains at least one public function)
- All public (non-underscore-prefixed) top-level functions become jobs

This is the default for new projects — you get auto-discovery with no configuration.

```toml
# pyproject.toml — no [tool.functualize.discovery] section needed
[tool.functualize]
jobs_directories = ["jobs"]
```

> **See also:** [`examples/standalone/discovery_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/discovery_lab/) — its baseline step (no filters) demonstrates convention mode.

---

## File-Level Filters

### `require_file_prefix`

Only consider files whose stem (filename without `.py`) starts with the specified prefix.

```toml
[tool.functualize.discovery]
require_file_prefix = "job_"
```

With this setting, `jobs/job_deploy.py` qualifies but `jobs/helpers.py` does not. The check is on the **stem only** — directory path components are ignored.

### `require_file_postfix`

Only consider files whose stem ends with the specified postfix.

```toml
[tool.functualize.discovery]
require_file_postfix = "_task"
```

With this setting, `jobs/deploy_task.py` qualifies but `jobs/deploy.py` does not.

### `require_file_import`

Only consider files that import from a specified package (detected via AST parsing — no code execution).

```toml
[tool.functualize.discovery]
require_file_import = "functualize"
```

Detects all import forms:
- `import functualize`
- `from functualize import job`
- `from functualize.job import RunContext`
- Imports inside `try`/`except` blocks at module level

> **See also:** [`examples/standalone/discovery_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/discovery_lab/), step 4 of its filter matrix.

### `require_file_marker`

Only consider files that define a specific module-level variable.

```toml
[tool.functualize.discovery]
require_file_marker = "__functualize__"
```

The file must contain a top-level assignment like:

```python
__functualize__ = True  # marks this file for discovery
```

> **See also:** [`examples/standalone/discovery_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/discovery_lab/), step 5 of its filter matrix.

### `exclude_patterns`

Exclude files matching glob patterns before any other filter runs.

```toml
[tool.functualize.discovery]
exclude_patterns = [
    "**/test_*.py",
    "**/migrations/*.py",
    "**/_internal/**",
]
```

Patterns use `fnmatch` semantics against the file's path relative to the scanned directory. Supports `*`, `**`, and `?` wildcards. Maximum 50 patterns.

---

## Job-Level Filters

Job-level filters control which functions within qualifying files become jobs. They judge each *function*, where the file-level filters above judge each *file* — so a module holding one job and nine helpers contributes exactly one job.

A function these filters reject is not merely hidden from listings: it is unreachable by name too, so `func <name>` reports an unknown command rather than running something `func` refuses to list.

### `require_job_decorators`

Only register functions that carry a specific decorator.

```toml
[tool.functualize.discovery]
require_job_decorators = ["job", "workflow"]
```

Matches both bare and parameterized forms:

```python
from functualize.job import job

@job                    # ✓ matches "job"
def deploy(): ...

@job(group="infra")     # ✓ matches "job"
def migrate(): ...

def helper(): ...       # ✗ no decorator — not registered
```

Matching is on the decorator's **root name**, read from the source AST: `@job` and `@job(...)` both match `"job"`, while `@registry.job` matches `"registry"`. The AST is the source of truth because a transparent decorator (one that returns the function unchanged) leaves nothing on the imported object to inspect.

> **See also:** [`examples/standalone/discovery_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/discovery_lab/), step 6 of its filter matrix.

### `require_job_prefix`

Only register functions whose name starts with the specified prefix.

```toml
[tool.functualize.discovery]
require_job_prefix = "run_"
```

### `require_job_postfix`

Only register functions whose name ends with the specified postfix.

```toml
[tool.functualize.discovery]
require_job_postfix = "_job"
```

The full function name (including prefix/postfix) becomes the job name — nothing is stripped.

---

## Filter Ordering (Internal)

Filters are evaluated cheapest-first to minimize unnecessary work:

1. **GlobExcludePreFilter** — pattern match on path (cheapest)
2. **DefaultModulePreFilter** — skip `_`-prefixed files
3. **FilePrefixPreFilter** — filename string check
4. **FilePostfixPreFilter** — filename string check
5. **ASTModulePreFilter** — requires file read + parse
6. **ImportModulePreFilter** — requires file read + parse
7. **MarkerModulePreFilter** — requires file read + parse
8. **DecoratorModulePreFilter** — requires file read + parse

If a file fails any earlier filter, expensive AST parsing is skipped entirely.

Step 8 is an import-skip optimization for `require_job_decorators`, not the filter itself: a file with zero decorated functions cannot contribute a job, so it is never imported. Files that survive still have every public function judged individually.

The job-level filters then run over the extracted descriptors:

1. **JobPrefixFilter** — function name string check
2. **JobPostfixFilter** — function name string check
3. **JobDecoratorFilter** — decorator names recorded during extraction

These apply on *read* rather than on write, so the discovery cache stays a superset of what any one configuration admits and a changed `require_job_*` setting takes effect immediately. File-level filters decide what gets *written* to the cache, so they cannot work that way — instead the cache header fingerprints your discovery filter settings, and changing any of them discards the cache and rescans. Either way a filter change takes effect on your next command; `func builtin cache clear` is not needed.

---

## Common Combinations

### Small project (zero config)

```toml
# No discovery section needed — convention mode
[tool.functualize]
jobs_directories = ["jobs"]
```

All public functions in `jobs/*.py` become jobs.

### Medium project (import guard)

```toml
[tool.functualize.discovery]
require_file_import = "functualize"
exclude_patterns = ["**/test_*.py"]
```

Only files that import functualize are considered. Test files excluded.

### Large project (strict decorator mode)

```toml
[tool.functualize.discovery]
require_file_import = "functualize"
require_job_decorators = ["job", "workflow"]
exclude_patterns = ["**/test_*.py", "**/migrations/**"]
```

Files must import functualize AND functions must be decorated. Maximum precision.

### Naming convention project

```toml
[tool.functualize.discovery]
require_file_prefix = "job_"
require_job_prefix = "run_"
```

Only `job_*.py` files, only `run_*` functions.

> **See also:** [`examples/standalone/discovery_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/discovery_lab/), step 8 of its filter matrix, for a multi-filter example.

---

## Mode × Discovery Matrix

Shows which discovery settings apply in each execution mode:

| Setting | Mode A (single-file) | Mode B/C (project) | Library (FunctualizeApp) |
|---|---|---|---|
| `exclude_patterns` | ✓ Applied | ✓ Applied | ✓ If `discovery_config` provided |
| `require_file_prefix` | ✓ Applied | ✓ Applied | ✓ If `discovery_config` provided |
| `require_file_postfix` | ✓ Applied | ✓ Applied | ✓ If `discovery_config` provided |
| `require_file_import` | ✓ Applied | ✓ Applied | ✓ If `discovery_config` provided |
| `require_file_marker` | ✓ Applied | ✓ Applied | ✓ If `discovery_config` provided |
| `require_job_decorators` | ✓ Applied | ✓ Applied | ✓ If `discovery_config` provided |
| `require_job_prefix` | ✓ Applied | ✓ Applied | ✓ If `discovery_config` provided |
| `require_job_postfix` | ✓ Applied | ✓ Applied | ✓ If `discovery_config` provided |
| `extra_directories` | — Not used | ✓ Appended to scan dirs | ✓ If `discovery_config` provided |
| Global config reading | ✓ Automatic | ✓ Automatic | ✗ Not read (developer provides config) |
| Project config reading | ✓ Automatic | ✓ Automatic | ✗ Not read (developer provides config) |
| CLI flags | ✓ Highest priority | ✓ Highest priority | — N/A |
| Env vars | ✓ Priority 2 | ✓ Priority 2 | — N/A |

**Key distinction:** When using `FunctualizeApp` directly as a library (not via `func` CLI), global config and project config are NOT auto-read. The developer passes `discovery_config` explicitly — or gets baseline convention mode.

---

## CLI Flag Overrides

Override any discovery filter per-invocation:

```bash
# Override file import requirement
func --require-file-import mypackage deploy

# Add exclude patterns (repeatable, max 20)
func --exclude "**/test_*" --exclude "**/migrations/**" deploy

# Require specific decorators
func --require-job-decorators job --require-job-decorators workflow deploy

# Override file prefix
func --require-file-prefix job_ deploy

# Require a module-level marker variable
func --require-file-marker __functualize__ deploy

# Job-level name filters (function names, not filenames)
func --require-job-prefix run_ deploy
func --require-job-postfix _job deploy
```

Every discovery setting has a flag: `--require-file-import`,
`--require-file-prefix`, `--require-file-postfix`, `--require-file-marker`,
`--require-job-prefix`, `--require-job-postfix`, `--require-job-decorators`
(repeatable), and `--exclude` (repeatable).

CLI flags take highest precedence, overriding all other configuration sources. Flags on *different* keys do not override each other: they stack, like any other filter combination.

---

## Error Handling

| Condition | Behavior |
|---|---|
| File can't be read or has syntax errors | Filter returns False (file excluded silently) |
| Invalid glob pattern (empty string) | `ValueError` at construction time |
| `require_job_decorators = []` (empty list) | `ValueError` — at least one name required |
| `--exclude` used >20 times | Error message, non-zero exit |

See [Configuration](config.md) for config-level error handling.
