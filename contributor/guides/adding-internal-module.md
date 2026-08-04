# Guide: Adding a New Internal Module

When you need to add new implementation code to an internal layer.

## Steps

### 1. Identify the correct layer

| If your code... | It belongs in... |
|-----------------|-----------------|
| Is a pure data type (dataclass, enum, protocol) | `_types/` |
| Is a zero-dep utility (no framework knowledge) | `_primitives/` |
| Emits or subscribes to events | `_events/` |
| Finds/caches job descriptors | `_discovery/` |
| Resolves configuration values | `_config/` |
| Executes job functions | `_engine/` |
| Loads/manages plugins | `_plugins/` |
| Wires peer layers together | `_app/` |
| Is CLI-specific delivery | `_cli/` |

### 2. Check allowed imports

Before writing code, verify your layer's import budget (see `reference/layer-rules.md`):

- Peer layers (`_discovery`, `_config`, `_engine`, `_plugins`) can only import from `_types/`, `_primitives/`, `_events/`
- They CANNOT import from each other

### 3. If you need something from another peer layer

Don't import it directly. Instead:

1. Define a Protocol in `_types/protocols.py`
2. Have the other layer implement it (it already does structurally, or you add the methods)
3. Have `_app/boot.py` inject the concrete instance via constructor parameter

Example: `_engine/` needs to look up a job's config defaults.

```python
# _types/protocols.py
class ConfigDefaults(Protocol):
    def get_defaults(self, job_name: str) -> dict[str, Any]: ...

# _engine/executor.py
class JobExecutionEngine:
    def __init__(self, config_defaults: ConfigDefaults, ...): ...

# _app/boot.py (composition root wires it)
from functualize._config.chain import ResolutionChain  # implements ConfigDefaults
engine = JobExecutionEngine(config_defaults=resolution_chain, ...)
```

### 4. Create the module

```python
# src/functualize/_discovery/my_new_module.py

"""Brief description of what this module does."""

from __future__ import annotations

from typing import TYPE_CHECKING

from functualize._types.descriptors import JobDescriptor
from functualize._primitives.resilient import resilient

if TYPE_CHECKING:
    from pathlib import Path
```

### 5. Verify with lint-imports

```bash
uv run lint-imports
```

If it reports a violation, you're importing from a forbidden layer. Fix it using the Protocol pattern above.

### 6. Write tests

Tests mirror the source domain structure. For a module in `src/functualize/_discovery/my_new_module.py`:

- Place unit tests in `tests/discovery/test_my_new_module.py`
- Place property tests in `tests/discovery/test_my_new_module_props.py` (or `_properties.py` or `_property.py`)
- Tests CAN import from any layer (test code is not subject to import-linter)

### 7. If the module introduces a new public-facing concept

See `guides/adding-public-api.md` for how to expose it through the public folders.
