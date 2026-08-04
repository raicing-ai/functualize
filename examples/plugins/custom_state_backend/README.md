# Custom State Backend — Plugin Example

Demonstrates implementing the `StateBackend` protocol to create a custom storage backend. This example builds a Redis-like in-memory backend with TTL support.

## What This Demonstrates

- Implementing the `StateBackend` protocol from `functualize-state`
- Using `StateNamespace` for prefix isolation
- Plugin boot class with DI registration
- Entry point configuration in `pyproject.toml`
- Protocol compliance verification with `isinstance()`
- Testing the plugin against the protocol contract

## Plugin Structure

```
custom_state_backend/
├── README.md
├── pyproject.toml
├── src/functualize_state_memory/
│   ├── __init__.py
│   ├── _backend.py         # StateBackend implementation
│   └── _plugin.py          # Plugin boot class
└── tests/
    └── test_backend.py
```

## Entry Point Registration

```toml
[project.entry-points."functualize.state_providers"]
memory-ttl = "functualize_state_memory:MemoryTTLPlugin"
```

## Usage

Once installed, the plugin is auto-discovered:

```python
# functualize finds it via entry points
app = FunctualizeApp("my-app")
# The memory-ttl backend is now available as a state provider
```
