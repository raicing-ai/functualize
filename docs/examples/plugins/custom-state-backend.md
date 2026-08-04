# Custom State Backend — Plugin Example

Implement the `StateBackend` protocol to create a custom storage backend. This example builds an in-memory backend with TTL (time-to-live) key expiration.

## Source

[`examples/plugins/custom_state_backend/`](https://github.com/raicing-ai/functualize/tree/master/examples/plugins/custom_state_backend)

## The Protocol

Your backend must satisfy the `StateBackend` protocol:

```python
from functualize_state import StateBackend

class MyBackend:
    def get(self, key: str, default=None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def delete(self, key: str) -> None: ...
    def keys(self, prefix: str = "") -> list[str]: ...

assert isinstance(MyBackend(), StateBackend)  # Protocol check
```

## Plugin Boot Class

Register your backend with FunctualizeApp's DI registry:

```python
class MyPlugin:
    name = "state-my-backend"
    domain = "state"

    def __call__(self, app):
        backend = MyBackend()
        app.provide(StateBackend, backend)
```

## Entry Point Registration

```toml
[project.entry-points."functualize.state_providers"]
my-backend = "my_package:MyPlugin"
```

## Key Concepts

- **Protocol compliance** — `isinstance(backend, StateBackend)` validates at import time
- **`StateNamespace`** — Works with any backend for prefix-scoped key isolation
- **DI registration** — `app.provide(StateBackend, instance)` makes it available to all jobs
- **Entry points** — Auto-discovery without manual configuration

## Related

- [Custom Adapter Example](custom-adapter.md)
- [Plugins Guide](../../guides/plugins.md)
- [Scaffold CLI](../../cli/scaffold.md)
