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

Tests live in the **domain-mirrored directory** for the code under test, exactly like
unit tests — `tests/discovery/`, `tests/config/`, `tests/context/`. There is no
`tests/properties/` directory, and there never has been; what makes a file a property
test is its **name**, not its location:

```
tests/<domain>/test_<component>_properties.py    # also _props.py, _property.py
```

`tests/conftest.py` skips anything matching those suffixes unless `--run-slow` is
passed, wherever it sits in the tree. See `contributor/reference/testing-strategy.md`.

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

**Do not pin `max_examples` inline.** `@settings(max_examples=N)` beats the profile, so
a pinned test ignores `HYPOTHESIS_PROFILE` entirely. This is not a style preference:
1,228 decorators across 179 files had pinned it, which made the profile lever do
*nothing* — reconnecting `HYPOTHESIS_PROFILE` in conftest moved `tests/discovery/` from
383s to 382s. Only after the pins were stripped did the lever work: 444s at `default`,
75s at `dev`.

**Green at `default` is not green at `ci`.** The `ci` profile draws 200 examples where
`default` draws 100, so CI reaches inputs a local `--run-slow` never generates. Verify
with `HYPOTHESIS_PROFILE=ci` before claiming a tier is green — twice now that has been
the difference between a passing local run and a red CI.

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

❌ **Don't make properties that always pass** — `assert True` after complex setup is a waste

❌ **Don't reach for Hypothesis when the input space is finite.** If every argument comes
from an enum, `st.booleans()`, or a small bounded `st.integers()`, the whole domain can be
enumerated — and `parametrize` then covers it *exhaustively* where `@given` covers it only
*probably*, in a fraction of the runs. 119 tests here draw entirely from finite domains; 99
of them have ≤64 total combinations and were spending 200 examples each on it.

Converting one such file caught a real coverage hole: it hard-coded
`non_terminal_statuses = [RUNNING, UNKNOWN]` against an 8-member enum, so `BLOCKED` and
`SKIPPED` were never used as a starting state by any test. Derive the complement rather
than listing it, and add a guard test asserting the partition is total.

❌ **Don't generate fields the assertions never read.** A strategy that builds a full
`JobDescriptor` — `module_path`, `source_file`, a 64-character `content_hash`, a nested
`dependencies` dict — for a test that only asserts on `.name` pays a `from_regex` draw per
field per object, per example. Six such files accounted for the top of the slow tier;
constraining them to what the assertions actually read took 139s to 41s with no loss of
coverage.

Where the assertions *do* check that unrelated fields survive a transform, the fields must
still vary — but they can vary cheaply. `st.sampled_from(["0" * 64, "f" * 64])` gives two
distinguishable values at O(1) draw cost; `from_regex(r"[0-9a-f]{64}")` does not.

### Suppressing health checks

The general rule is **don't suppress** — `suppress_health_check` usually hides a real
problem, most often a strategy that is too expensive (see the anti-pattern above; fix the
strategy instead).

`HealthCheck.too_slow` is the documented exception, and `tests/conftest.py` suppresses it
on all three profiles along with `deadline=None`. Both of those check *wall-clock time*,
which under `-n 10` measures how loaded the machine is rather than anything about the
code. They fired at random and accounted for 13 of the last 15 failures in the slow-tier
repair. Genuinely slow properties are found with `--durations`, which measures the right
thing.

Do not extend that suppression to other health checks, and do not add it per-test — if a
single test needs it, the strategy is the problem.

## Running Property Tests

```bash
# Quick smoke (10 examples)
HYPOTHESIS_PROFILE=dev uv run pytest --run-slow -k "properties"

# Full run (100 examples, `default` profile)
uv run pytest --run-slow

# What CI runs (200 examples). Verify with this before calling the tier green.
HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto

# Specific file
uv run pytest --run-slow tests/discovery/test_registry_properties.py

# Where the time actually goes — the only way to find semantic over-generation
HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n 10 --durations=50
```

## Auditing the suite

Two scans worth re-running when the tier gets slow. Both are static and take seconds.

**Finite input spaces** — candidates for `parametrize`. Flags `@given` tests whose every
argument comes from `sampled_from` / `booleans` / a small bounded `integers`:

```python
# for each @given, resolve each keyword strategy to a cardinality (None if unbounded);
# report tests where every argument is finite, and the product of cardinalities.
# A product below the profile's max_examples means parametrize strictly dominates.
```

**Structurally duplicate tests** — normalise each `@given` body, renaming the drawn
parameters positionally, then group by the normalised source. Tests that collide differ
only in which strategy feeds them, which is either a `parametrize` case or, when one
strategy's domain is a subset of another's, redundant outright. This found 15 groups
covering 35 tests, including a byte-identical pair filed under two different spec
properties and three tests that were strict subsets of a fourth.

**What static analysis cannot do:** it cannot tell a round-trip property from a
pass-through. `assert from_dict(to_dict(x)) == x` and `assert store.get(k) == v` are the
same AST shape and opposite in value — the first is the best use of Hypothesis there is,
the second proves the same thing 200 times. Adding data-flow tainting to separate them
moved the count from 136 to 24 and mislabelled the worst offender. **Read the tests before
deleting them**; use the scans to decide what to read, not what to cut.
