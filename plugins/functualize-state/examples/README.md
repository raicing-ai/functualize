# functualize-state Examples

The state domain SDK: `StateBackend` protocol, `StateNamespace` scoping, and the `InMemoryState` testing double.

| Directory | Demonstrates |
|-----------|--------------|
| [`counter/`](counter/) | Namespace-scoped key-value state across job runs, using `InMemoryState` |

```bash
uv run pytest plugins/functualize-state/examples/ -v
```

For durable storage, see [`functualize-state-sqlite/examples/`](../../functualize-state-sqlite/examples/). To implement your own backend, see [`examples/plugins/custom_state_backend/`](../../../examples/plugins/custom_state_backend/).
