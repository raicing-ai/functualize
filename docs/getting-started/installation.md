# Installation

## Requirements

Functualize requires **Python 3.11** or higher.

```bash
python --version
# Python 3.11.x or higher
```

## Install Functualize

=== "CLI (uv, recommended)"

    ```bash
    uv tool install "functualize[cli]"
    ```

=== "CLI (pip)"

    ```bash
    pip install "functualize[cli]"
    ```

=== "Library only (uv)"

    ```bash
    uv add functualize
    ```

=== "Library only (pip)"

    ```bash
    pip install functualize
    ```

Use the **CLI** variants to get the `func` command and TUI (includes Click, Rich, Textual). Use the **Library only** variants when embedding functualize in a project that doesn't need the CLI — the core engine has zero CLI dependencies at runtime.

!!! tip "Minimal install for serverless/library use"

    If you're embedding functualize in a Lambda, HTTP service, or library (no CLI needed), install the bare package:

    ```bash
    pip install functualize  # core only — no CLI deps
    ```

    The core engine (`functualize.app`, `functualize.job`) has zero CLI dependencies at runtime — Click, Rich, and Textual are only imported when you install `[cli]` and use the `func` CLI or inline TUI.

## Verify Installation

```bash
func --version
```

## What's Installed

| Command | Purpose |
|---------|---------|
| `func` | The primary CLI — run jobs, scaffold projects, manage cache |
| `functualize` | Alias for `func` (same entry point) |

## Next Steps

Head to the [Quickstart](quickstart.md) to run your first job — no project setup required.
