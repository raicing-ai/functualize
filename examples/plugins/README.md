# Plugin Examples

Examples of creating custom plugins and adapters for the functualize ecosystem. Each example is a self-contained Python package demonstrating a specific extension point.

## Examples

| Directory | Description |
|-----------|-------------|
| `custom_state_backend/` | Implement the `StateBackend` protocol (Redis-like storage) — a packaged domain provider |
| `custom_adapter/` | Implement the `AdapterPlugin` protocol (webhook delivery) — a packaged delivery plugin |
| `file_based_plugin/` | Zero packaging: a single `.py` file in `.functualize/plugins/`, discovered at boot |

Examples of *using* the first-party plugins live in each plugin's own folder: `plugins/<name>/examples/` (e.g. [`plugins/functualize-mcp/examples/`](../../plugins/functualize-mcp/examples/)).

## Plugin Architecture

Functualize uses a protocol-based plugin system. You implement a protocol and register via entry points:

```python
# Your plugin implements a protocol
class MyBackend:
    def get(self, key: str, default=None): ...
    def set(self, key: str, value): ...
    def delete(self, key: str): ...
    def keys(self, prefix: str = "") -> list[str]: ...
```

```toml
# Register via pyproject.toml entry point
[project.entry-points."functualize.state_providers"]
my-backend = "my_plugin:MyPlugin"
```

## Extension Points

All plugins register under `functualize.plugins` for discovery. Categorization is
determined by the plugin's metadata attributes (`adapter_type`, `plugin_type`).

| Protocol | Category Attribute | Domain |
|----------|-------------------|--------|
| `StateBackend` | `plugin_type = "state_provider"` | Persistence |
| `AIProvider` | `plugin_type = "ai_provider"` | AI/LLM |
| `TaskProvider` | `plugin_type = "tasks_provider"` | Task management |
| `InputProvider` / `OutputRenderer` | `plugin_type = "interactivity"` | User I/O |
| `AdapterPlugin` | `adapter_type = "<name>"` | Delivery surfaces |

## Scaffold a New Plugin

Use the CLI to generate plugin boilerplate:

```bash
func builtin scaffold add plugin --domain state --name redis
func builtin scaffold add plugin --domain ai --name anthropic
```

## Tests

```bash
uv run pytest examples/plugins/ -v
```
