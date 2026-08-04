# functualize-state

> **Status: Published** — Independently installable from PyPI.

State Domain SDK for functualize providing well-defined protocols for key-value state persistence and execution tracking. Enables custom storage backend implementations (SQLite, Redis, DynamoDB, etc.) without coupling your application to any specific database.

## Installation

```bash
pip install functualize-state
```

## Quick Start

```python
from functualize_state import InMemoryState, StateNamespace

# Create a backend (use InMemoryState for testing, or implement StateBackend)
backend = InMemoryState()

# Use namespaces to isolate keys by concern
ns = StateNamespace(backend, prefix="deploy:")
ns.set("version", "1.2.0")
ns.set("status", "pending")

print(ns.get("version"))  # "1.2.0"
print(ns.keys())          # ["version", "status"]
```

## Features

- **Backend-agnostic protocols** — `StateBackend` and `ExecutionStore` define the interface; bring your own storage implementation
- **Namespace isolation** — `StateNamespace` provides prefix-scoped views over any backend, preventing key collisions between components
- **Execution tracking** — Record job executions, phases, and session metadata with structured `ExecutionRecord` and `PhaseRecord` types
- **Event-driven observability** — Built-in event constants (`STATE_EXECUTION_STARTED`, `STATE_EXECUTION_COMPLETED`, `STATE_PHASE_CHANGED`) for lifecycle hooks
- **Test-friendly** — Ships `InMemoryState`, a dict-backed backend for fast, deterministic unit tests
- **Fully typed** — PEP 561 compliant with `py.typed` marker; all protocols are `@runtime_checkable`

## API Reference

### Protocols

- `StateBackend` — Key-value state operations protocol (`get`, `set`, `delete`, `keys`)
- `ExecutionStore` — Execution record persistence protocol (`insert_execution`, `update_execution`, `get_session_executions`, `insert_phase`, `get_execution_phases`)

### Classes

- `StateNamespace` — Prefix-scoped view over a `StateBackend` for isolated key access
- `InMemoryState` — Dict-backed `StateBackend` implementation for testing
- `DomainMetadata` — Self-describing metadata dataclass for the state domain SDK

### Data Types

- `ExecutionRecord` — Frozen dataclass representing a single job execution (id, job name, session, status, timing, result)
- `PhaseRecord` — Frozen dataclass representing a phase within an execution
- `SessionRecord` — Frozen dataclass representing a session with metadata

### Errors

- `StateNotAvailable` — Raised when a state backend is not available
- `KeyNotFoundError` — Raised when a requested key is not found

### Event Constants

- `STATE_EXECUTION_STARTED` — Fired when an execution begins
- `STATE_EXECUTION_COMPLETED` — Fired when an execution finishes
- `STATE_PHASE_CHANGED` — Fired when a phase transition occurs

### Module-Level

- `domain_metadata` — Pre-configured `DomainMetadata` instance for the state domain

## Development

Run plugin tests:

```bash
uv run pytest plugins/functualize-state/tests/ -v
```
