# Layer Rules — Quick Reference

## Can I Import X From Y?

| FROM ↓ / TO → | `_types` | `_primitives` | `_events` | `_discovery` | `_config` | `_gate` | `_engine` | `_plugins` | `_app` | `_cli` | public (`app/` etc) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **`_types/`** | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`_primitives/`** | ✅ | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`_events/`** | ✅ | ✅ | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`_discovery/`** | ✅ | ✅ | ✅ | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`_config/`** | ✅ | ✅ | ✅ | ❌ | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`_gate/`** | ✅ | ✅ | ✅ | ❌ | ❌ | — | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`_engine/`** | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | — | ❌ | ❌ | ❌ | ❌ |
| **`_plugins/`** | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | — | ❌ | ❌ | ❌ |
| **`_app/`** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — | ❌ | ❌ |
| **`_cli/`** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — | ✅ |
| **public folders** | via re-export | via re-export | via re-export | — | — | — | — | — | ✅ (app/ only) | — | ✅ |

## Rules in Plain English

1. **`_types/`** imports nothing (only stdlib)
2. **`_primitives/`** imports only `_types/`
3. **`_events/`** imports `_types/` and `_primitives/`
4. **Peer layers** (`_discovery`, `_config`, `_gate`, `_engine`, `_plugins`) import `_types/` + `_primitives/` + `_events/` — never each other
5. **`_app/`** (composition root) imports everything internal — never `_cli/` or public folders
6. **`_cli/`** imports ONLY public folders — never anything with underscore prefix
7. **Internal layers** never import public folders (no circular re-export chains)

## How to Check

```bash
# Run locally
uv run lint-imports

# CI runs this automatically
```

## What If I Need Cross-Layer Communication?

See `contributor/architecture/dependency-graph.md` — the answer is always:
1. Define a Protocol in `_types/`
2. Have `_app/` wire the concrete implementation via constructor injection
