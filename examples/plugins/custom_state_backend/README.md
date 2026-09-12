# Custom Substrate — Plugin Example

Bring your own storage. This plugin implements `StoreSubstrate` — the one seam
that decides *where functualize keeps its own bookkeeping* — and installs it at
boot. Every store follows, because there is one place that decides and one
object handed to all of them.

The implementation here is a dict, so it is gone when the process is. The
**shape** is what transfers: it is the same shape `functualize-state-sqlite`
fills with a database.

## What This Demonstrates

- Implementing the six-member `StoreSubstrate` port
- The two distinctions the stores depend on: *nothing stored* is not *an empty
  document*, and `clear` is not `delete`
- Compare-and-swap (`write(..., expect=)`) beside `lock`, so a substrate that
  cannot lock — a remote object store — still has a way to be safe
- Installing the substrate at `APP_READY`, and why not later
- Entry point configuration in `pyproject.toml`
- Protocol compliance verified with `isinstance()`

## Why this is not a `StateBackend`

It used to be. `contributor/adr/022` records why the key-value domain was
retired: a backend-agnostic key-value protocol can only offer the **intersection
of every backend**, which is worth least exactly where having a real database is
worth most. The MCP history tools were the proof — `get_job_history` could not
ask for "recent executions", so it probed four method names and took whichever
the installed backend happened to have.

A substrate is asked for a *document*, not for a key. What a scope is, what a
step record looks like, and which document refuses an unreadable read are
decisions about **meaning**, and they stay on the stores.

## Plugin Structure

```
custom_state_backend/
├── README.md
├── pyproject.toml
├── src/functualize_state_memory/
│   ├── __init__.py
│   ├── _backend.py         # StoreSubstrate implementation
│   └── _plugin.py          # Plugin boot class
└── tests/
    └── test_backend.py
```

## Entry Point Registration

```toml
[project.entry-points."functualize.state_providers"]
memory = "functualize_state_memory:MemoryStatePlugin"
```

## Installing the substrate

```python
class MemoryStatePlugin:
    def __call__(self, app):
        from functualize._events.hooks import HookEvent

        app.hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)

    def _on_app_ready(self, app):
        app.substrate = MemorySubstrate()
```

`APP_READY` and not later: the engine resolves its substrate lazily, on the
first store access, and installing after that is **refused** rather than
half-applied. Some of a run's documents in one backend and some in another is
the state this seam exists to make unreachable.

## Run the tests

```bash
uv run pytest examples/plugins/custom_state_backend/
```
