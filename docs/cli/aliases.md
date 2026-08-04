# Aliases

Aliases let you define short names for frequently-used jobs. Define them in the `[aliases]` section of your [global config](global-config-directory.md).

## Defining Aliases

```toml
# ~/.config/functualize/config.toml
[aliases]
d = "deploy"
m = "migrate"
sync = "data_sync"
prod-deploy = "deploy_production"
```

Once defined, use the alias anywhere you'd use the full job name:

```bash
func d          # equivalent to: func deploy
func m          # equivalent to: func migrate
func sync       # equivalent to: func data-sync
```

---

## Naming Constraints

Alias names must follow these rules:

| Rule | Constraint |
|---|---|
| Pattern | `^[a-zA-Z][a-zA-Z0-9_-]*$` |
| Start | Must begin with a letter (a-z, A-Z) |
| Body | Letters, digits, underscores, hyphens |
| Max length | 32 characters |

Alias values (the job name being aliased) have a max length of 128 characters.

### Valid Names

```toml
[aliases]
d = "deploy"                    # single letter
deploy-prod = "deploy_production"  # hyphens allowed
run_tests = "test_suite"        # underscores allowed
myJob2 = "my_job_v2"           # digits in body
```

### Invalid Names (Skipped with Warning)

```toml
[aliases]
2fast = "deploy"               # ✗ starts with digit
-prefix = "deploy"             # ✗ starts with hyphen
"has spaces" = "deploy"        # ✗ contains spaces
a-very-long-alias-name-that-exceeds-the-limit = "deploy"  # ✗ >32 chars
```

Invalid aliases produce a warning to stderr and are skipped — they don't prevent the CLI from running.

---

## How Aliases Resolve

Alias resolution happens via the [FallbackCommand chain](modes.md). When you type a command that doesn't match any registered Click command or discovered job name:

1. The CLI checks if the first argument is an alias key
2. If it matches, the aliased job name is substituted
3. The job is executed as if you typed the full name

```
func d → FallbackCommand chain → AliasFallback matches "d" → executes "deploy"
```

---

## Limits

| Setting | Maximum |
|---|---|
| Total aliases | 200 |
| Alias key length | 32 characters |
| Alias value length | 128 characters |

---

## Priority and Conflicts

- Aliases are loaded from the global config only
- If an alias name conflicts with a registered command (e.g., aliasing `d` when a job named `d` exists), the **registered command wins** — the alias is not consulted
- Aliases are only checked as a fallback when no command matches directly

---

## Examples

### Common Patterns

```toml
[aliases]
# Short forms for frequent jobs
d = "deploy"
t = "test_all"
b = "build"

# Environment-specific
prod = "deploy_production"
stg = "deploy_staging"

# Workflow shortcuts
fresh = "reset_and_seed"
ci = "continuous_integration"
```

### Using with Discovery Filters

Aliases work with any discovery configuration. The aliased name must match an actual discovered job:

```toml
# config.toml
[discovery]
require_job_decorators = ["job"]

[aliases]
d = "deploy"   # "deploy" must be a @job-decorated function
```

If the aliased job doesn't exist (e.g., the file wasn't discovered or the function doesn't match filters), you'll get a standard "job not found" error.
