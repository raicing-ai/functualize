# Guide: Adding a New Public API Symbol

When you need to expose a new class, function, or type to users.

## The Golden Rule

> If `_cli/` needs it and can't access it, it should be public. If only internal layers need it, keep it internal.

## Steps

### 1. Decide which public folder it belongs in

| If the symbol is for... | It goes in... |
|-------------------------|---------------|
| App construction, adapters, presets, utilities | `app/` |
| Job function authors (capabilities, context) | `job/` |
| Plugin/extension authors (protocols, events) | `plugin/` |
| Shared types used by multiple audiences | `types/` |
| Test utilities and doubles | `testing/` |

### 2. Implement in the internal layer

The actual logic lives in `_engine/`, `_discovery/`, etc. The public folder only re-exports.

### 3. Add to the public `__init__.py`

```python
# Example: adding CacheInfo to types/

# types/__init__.py
from functualize._types.cache import CacheInfo  # noqa: F401 (re-export)

__all__ = [
    "JobResult",
    "JobDescriptor",
    "FieldDescriptor",
    "RunStatus",
    "RunType",
    "JobPhase",
    "CacheInfo",         # ← NEW
]
```

### 4. Add to `__all__`

Every public `__init__.py` MUST have an explicit `__all__`. Your new symbol goes here. This is the API contract.

### 5. Verify the import works

```python
# Should work from the user's perspective:
from functualize.types import CacheInfo
```

### 6. Verify `_cli/` can use it

If this was added because `_cli/` needed it, verify:

```python
# _cli/builtins.py
from functualize.types import CacheInfo  # ← should work without lint-imports violation
```

### 7. Document

- Add to `docs/` (mkdocs) if it's user-facing
- Add to `contributor/reference/code-map.md` for contributor reference

## Important: Internal → Public Import Direction

The public `__init__.py` files are the ONE place where internal modules are imported into public space:

```python
# app/__init__.py imports from _app/
from functualize._app.impl import FunctualizeApp  # This is allowed (app/ → _app/)
```

But `_app/` NEVER imports from `app/`:
```python
# _app/boot.py — WRONG, would be caught by lint-imports
from functualize.app import FunctualizeApp  # ❌ Internal never imports public
```

## Checklist

- [ ] Implementation lives in the correct internal layer
- [ ] Re-exported from the appropriate public `__init__.py`
- [ ] Added to `__all__`
- [ ] `uv run lint-imports` passes
- [ ] Import works from user perspective
- [ ] Added to code-map.md
- [ ] Documented in mkdocs (if user-facing)
