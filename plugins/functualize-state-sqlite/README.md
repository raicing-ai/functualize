# functualize-state-sqlite

> **Status: Published** — Independently installable from PyPI.

SQLite-backed state persistence and execution tracking plugin for functualize. Implements the `StateBackend` and `ExecutionStore` protocols from `functualize-state`, providing durable key-value storage and full execution history using a local SQLite database in WAL mode. Zero external dependencies beyond the Python standard library's `sqlite3` module.

## Installation

```bash
pip install functualize-state-sqlite
```

## Quick Start

```python
from functualize_state_sqlite import SQLiteStateBackend

# Use as a context manager for automatic cleanup
with SQLiteStateBackend(db_path="my_app.db") as backend:
    backend.set("deploy_count", 42)
    backend.set("last_env", "staging")

    count = backend.get("deploy_count")
    print(f"Deployments: {count}")

    keys = backend.keys(prefix="deploy")
    print(f"Keys: {keys}")
```

## Features

- **Persistent key-value state** — JSON-encoded values stored in SQLite with automatic schema initialization
- **WAL mode for concurrency** — concurrent read access without blocking writes, suitable for multi-process environments
- **Execution tracking** — full session and execution history with nested invocation support and phase recording
- **Namespace-scoped state** — `SQLiteStateStore` provides per-job namespace isolation within workflow scopes
- **Context manager support** — all backends support `with` statements for automatic connection cleanup
- **Zero external dependencies** — uses only Python's built-in `sqlite3` module
- **Automatic schema migrations** — database schema is created and migrated transparently on first access

## API Reference

Public classes exported by this plugin:

- `SQLiteStateBackend` — Implements the `StateBackend` protocol with `get()`, `set()`, `delete()`, and `keys()` methods for persistent key-value storage using a dedicated `kv_state` table.
- `SQLiteExecutionStore` — Implements the `ExecutionStore` protocol for recording and querying execution records and phase tracking. Methods include `insert_execution()`, `update_execution()`, `get_session_executions()`, `insert_phase()`, and `get_execution_phases()`.
- `SQLiteStatePlugin` — Plugin that registers `SQLiteStateBackend` and `SQLiteExecutionStore` with the DI registry at boot time. Hooks into `APP_READY` and `ON_SCOPE_CREATED` lifecycle events.
- `ExecutionStatePlugin` — Full lifecycle plugin that tracks job executions automatically. Hooks into `BEFORE_JOB`, `AFTER_SUCCESS`, `AFTER_FAILURE`, `INVOKE_START`, `INVOKE_END`, and `ON_SCOPE_CREATED` for comprehensive execution history.

Internal classes (available via direct import but not part of the public protocol surface):

- `SQLiteBackend` — Low-level connection manager with WAL mode, schema initialization, and query helpers for sessions, executions, steps, and namespaced state.
- `SQLiteStateStore` — `StateStoreProtocol` implementation scoped to a `(scope_id, job_namespace)` pair, with `get()`, `set()`, `delete()`, `keys()`, `to_dict()`, `clear()`, and cross-job access via `get_job_state()`.
- `ExecutionTracker` — High-level session management and execution recording with automatic session resume based on TTL, and AI context summary generation via `to_ai_context()`.

## Development

Run plugin tests:

```bash
uv run pytest plugins/functualize-state-sqlite/tests/ -v
```

Build the package:

```bash
uv build --package functualize-state-sqlite
```
