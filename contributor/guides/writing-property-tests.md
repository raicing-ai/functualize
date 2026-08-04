# Guide: Writing Property Tests

Property tests verify **universal invariants** — things that should hold true for ALL valid inputs, not just specific examples.

## When to Use Property Tests

| Use property tests for... | Use unit tests for... |
|---|---|
| "For any valid X, Y always holds" | "Given this specific input, expect this output" |
| Mathematical relationships (round-trip, commutativity) | Error messages contain specific text |
| Protocol satisfaction across random implementations | Integration with real filesystem/network |
| Cache validity invariants | Boot sequence ordering |

## Conventions

### File location

```
tests/properties/test_<component>.py
```

### Tagging

```python
class TestMiddlewareChainProperties:
    """Feature: unified-architecture-redesign, Property 1: Middleware priority ordering"""

    @given(...)
    def test_priority_ordering(self, middlewares):
        """Validates: Requirements 1.2, 1.3"""
        ...
```

### Hypothesis Profiles

Tests run with the profile set by `HYPOTHESIS_PROFILE` env var:

```python
from hypothesis import settings

# The conftest.py handles profile loading automatically.
# Just write @given(...) — no @settings needed unless overriding.
```

### Marking as slow

Property tests are auto-detected by filename (`*_properties.py`, `*_props.py`, `*_property.py`). They're skipped unless `--run-slow` is passed. If you put property tests in a differently-named file, mark them:

```python
import pytest

@pytest.mark.slow
class TestMyProperties:
    ...
```

## Common Patterns

### Round-trip property

```python
from hypothesis import given
from hypothesis.strategies import text, integers

@given(name=text(min_size=1), priority=integers(0, 999))
def test_namespace_transform_round_trip(self, name, priority):
    """Adding then stripping a namespace prefix returns the original name."""
    transform = NamespaceTransform("ns")
    prefixed = f"ns.{name}"
    # transform_get strips the prefix before delegation
    assert transform._strip_prefix(prefixed) == name
```

### Invariant property

```python
@given(entries=lists(builds(CacheEntry, ...)))
def test_cache_entry_count_matches_descriptors(self, entries):
    """Cache entry count always equals descriptor count after sync."""
    provider = CachedDirectoryScanProvider(entries=entries)
    descriptors = provider.list_jobs()
    assert len(descriptors) == len(provider._by_name)
```

### Commutativity / algebra property

```python
@given(filters=lists(builds(lambda: MockFilter(decision=...))))
def test_allof_matches_builtin_all(self, filters):
    """AllOf(filters) == all(f.should_import(path) for f in filters)"""
    path = Path("test.py")
    result = AllOf(*filters).should_import(path)
    expected = all(f.should_import(path) for f in filters)
    assert result == expected
```

### Error property

```python
@given(type_name=text(min_size=1).filter(lambda s: s not in registered_types))
def test_missing_provider_raises_with_diagnostics(self, type_name):
    """Resolving an unregistered type always includes available types in error."""
    registry = DIRegistry()
    registry.provide(str, "hello")

    with pytest.raises(MissingProviderError) as exc_info:
        registry.resolve(type(type_name, (), {}))

    assert "str" in str(exc_info.value)  # available types listed
```

## Strategies for Domain Types

Build reusable strategies for your domain:

```python
# tests/strategies.py
from hypothesis import strategies as st

job_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1, max_size=64,
)

priorities = st.integers(min_value=0, max_value=999)

field_types = st.sampled_from(["str", "int", "float", "bool", "list[str]", "Path"])
```

## Anti-Patterns

❌ **Don't test implementation details** — properties should survive refactoring

❌ **Don't use @example() as a crutch** — if you need specific examples, write a unit test instead

❌ **Don't suppress too aggressively** — `@settings(suppress_health_check=[...])` hides real problems

❌ **Don't make properties that always pass** — `assert True` after complex setup is a waste

## Running Property Tests

```bash
# Quick smoke (10 examples)
HYPOTHESIS_PROFILE=dev uv run pytest --run-slow -k "properties"

# Full run (100 examples)
uv run pytest --run-slow

# Specific file
uv run pytest --run-slow tests/properties/test_di_registry.py
```
