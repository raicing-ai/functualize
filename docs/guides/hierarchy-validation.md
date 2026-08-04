# Hierarchy Validation

Functualize validates hierarchical project structures at mount time to prevent two classes of problems: **version incompatibilities** between parent and child projects, and **circular dependencies** that would cause infinite recursion during discovery.

These checks run automatically during `FunctualizeApp` initialization — no changes to your application code are required.

!!! tip "Prerequisites"
    This guide assumes you're familiar with hierarchical project composition. See the [Hierarchical Projects](../hierarchy.md) guide for setup instructions and configuration options.

## Version Compatibility Checking

When a child project is mounted, the validator extracts the child's declared functualize builtin version from its `pyproject.toml` dependencies and compares it against the parent's running version.

### How Comparison Works

The validator uses **major.minor** comparison to determine compatibility:

- The child's minimum functualize builtin version (major, minor) must be **greater than or equal to** the parent's running version (major, minor)
- Patch versions are ignored in the comparison
- If either version is unknown, the check passes with a warning

```python
# Compatible: child (0, 3, 1) vs parent (0, 3, 0) — same major.minor
# Compatible: child (1, 2, 0) vs parent (1, 1, 5) — child minor is higher
# Incompatible: child (0, 2, 0) vs parent (0, 3, 0) — child minor is lower
# Incompatible: child (0, 5, 0) vs parent (1, 0, 0) — child major is lower
```

### Version Resolution

The version resolver determines a project's functualize builtin version through two sources, tried in order:

1. **`pyproject.toml`** — Parses the `[project.dependencies]` list for a functualize entry and extracts the minimum version from the specifier
2. **Installed package metadata** — Falls back to `importlib.metadata` if the pyproject.toml is missing or doesn't declare a functualize dependency

Supported specifier formats:

| Format | Example | Extracted minimum |
|--------|---------|-------------------|
| PEP 440 `>=` | `functualize>=0.3.0` | `0.3.0` |
| PEP 440 `==` | `functualize==1.0.0` | `1.0.0` |
| PEP 440 `~=` | `functualize~=0.2.0` | `0.2.0` |
| Poetry caret | `functualize^0.2.0` | `0.2.0` |
| No lower bound | `functualize!=1.0.0` | Unknown (`None`) |
| Bare name | `functualize` | Unknown (`None`) |

## Cycle Detection

The validator tracks an **ancestry chain** — the ordered sequence of project paths from the root down to the current project being validated. Before mounting each child, the validator checks whether the child's canonical path already exists in the chain.

### How It Works

1. At the root project, the ancestry chain is initialized with the root's canonical absolute path
2. For each child about to be mounted, the validator resolves the child's path to its canonical form (resolving symlinks via `os.path.realpath`)
3. If the canonical path is already in the ancestry chain, a cycle is detected
4. If the child passes validation, its path is added to the chain before recursing into its own children

### Depth Limit

The validator enforces a maximum hierarchy depth of **10 levels** (root is level 0). If a project exceeds this depth, validation fails with a `HierarchyValidationError` regardless of the strict mode setting.

This prevents runaway recursion in deeply nested or misconfigured hierarchies.

### Path Canonicalization

All paths are resolved to their canonical absolute form before comparison. This handles:

- **Symlinks** — resolved to their real target
- **Relative paths** — resolved to absolute
- **Redundant separators** — normalized (e.g., `//` → `/`)

This prevents false negatives where the same project appears under different path representations.

## Configuration

Enable strict validation by setting `strict_hierarchy_validation = true` in the `[general]` section of your `config.base.ini`:

```ini title="config.base.ini"
[general]
app_name = ops-cli
strict_hierarchy_validation = true  # (1)!

[children]
tools = ~/code/tools-project
infra = ~/code/infra-project
```

1. Default is `false` (non-strict mode). Set to `true` to halt on validation failures.

### Behavior Modes

=== "Non-strict mode (default)"

    When `strict_hierarchy_validation` is absent or set to `false`:

    - Version mismatches produce a **warning log** and the child is **skipped**
    - Cycle detection errors produce a **warning log** and the child is **skipped**
    - Remaining children continue to be processed
    - The application starts successfully with the valid children mounted

=== "Strict mode"

    When `strict_hierarchy_validation = true`:

    - All children are validated first, collecting all failures
    - If **any** validation failure occurs, a `HierarchyValidationError` is raised
    - The error contains the complete list of failures
    - Application initialization **halts** — no children are mounted

## Error Reporting

### Version Mismatch Warnings

When a version incompatibility is detected, the message includes:

- The child's namespace name
- The child's project path
- The child's declared functualize builtin version
- The parent's running functualize builtin version

**Non-strict mode output:**

```
WARNING - Validation failed for child 'tools' at /home/user/code/tools-project:
Version incompatibility for child 'tools' at /home/user/code/tools-project:
child requires functualize 0.2.0 but parent runs 0.3.0
```

**Strict mode output:**

```
Version incompatibility (strict mode): child 'tools' at
/home/user/code/tools-project requires functualize 0.2.0 but parent runs 0.3.0
```

### Cycle Error Messages

Cycle errors include the full path chain showing how the cycle forms:

```
Cycle detected: /home/user/project-a → /home/user/project-b → /home/user/project-c → /home/user/project-a
```

The last entry in the chain is the project that closes the cycle — it matches an earlier entry in the ancestry.

### Depth Exceeded Errors

```
Maximum hierarchy depth of 10 exceeded at project: /home/user/deeply/nested/project
```

### Rich Formatting

If the [Rich](https://rich.readthedocs.io/) library is available in your environment, error messages are automatically formatted with color and bold markup for better terminal readability. If Rich is not installed, messages are rendered as plain text.

## Multiple Failures

The validator processes **all** children before reporting, rather than stopping at the first failure. In non-strict mode, each failure is logged individually. In strict mode, the raised `HierarchyValidationError` contains the complete list of `ValidationFailure` objects:

```python
from functualize._discovery.hierarchy_validator import HierarchyValidationError

try:
    app = FunctualizeApp(name="ops-cli", ...)
except HierarchyValidationError as e:
    for failure in e.failures:
        print(f"{failure.child_namespace}: {failure.reason}")
        # failure.failure_type is one of:
        #   "version_incompatible", "cycle_detected", "depth_exceeded"
```

## Summary

| Scenario | Non-strict (default) | Strict mode |
|----------|---------------------|-------------|
| Version mismatch | Skip child, log warning | Collect failure, raise error after all checks |
| Cycle detected | Skip child, log warning | Collect failure, raise error after all checks |
| Depth exceeded | Skip child, log warning | Collect failure, raise error after all checks |
| Unknown version | Log warning, allow mount | Log warning, allow mount |
| All children valid | Mount all children | Mount all children |
