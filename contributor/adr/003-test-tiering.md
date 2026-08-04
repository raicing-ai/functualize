# ADR-003: Test Suite Tiering with --run-slow

**Status**: accepted
**Date**: 2026-07-16
**Deciders**: Core team

## Context

The test suite included property-based (Hypothesis) tests and subprocess-heavy packaging
tests that dominated wall-clock time. Developers needed fast inner-loop feedback (< 60s)
during coding, but the full suite including property tests ran 8–12 minutes. Without a
tiering mechanism, developers either ran everything (slow) or nothing (risky).

Root causes of slowness:
- Property tests creating hundreds of FunctualizeApp instances (`test_auto_scope.py`)
- Hypothesis serialization round-trips with complex data
- Subprocess spawning for packaging tests (`uv build`, `functualize --help`)
- File I/O + hash computation under Hypothesis

## Decision

Implement a marker-based tiering system:

1. **`@pytest.mark.slow`** marker for property-based and expensive tests
2. **`--run-slow` CLI option** to include slow tests (off by default)
3. **conftest.py auto-skip**: tests marked `slow` are automatically skipped unless
   `--run-slow` is passed

This gives three effective tiers:
- **Inner loop** (`uv run pytest -x -q`): fast tests only, target ≤ 60s
- **Full suite** (`uv run pytest --run-slow`): everything including property tests
- **Plugin tests** (`pytest plugins/<name>/tests/`): isolated per-plugin

## Consequences

### Positive

- Default `pytest` run is fast enough for inner-loop development
- Property tests still run in CI via `--run-slow`
- Simple mechanism — one marker, one flag, no complex configuration
- Works with existing pytest infrastructure (no new dependencies)

### Negative

- Developers must remember to run `--run-slow` before pushing (CI catches this)
- New property tests must be manually marked `@pytest.mark.slow`

### Neutral

- pytest-xdist parallelization remains a future optimization (not yet adopted)
- Property-test cold storage (`tests/archive/`) deferred — current approach sufficient

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Separate test directories (`tests/unit/`, `tests/properties/`) | Clear physical separation | Breaks domain-mirrored dir structure; migration churn | Conflicts with established testing-strategy doc |
| Time-based auto-tiering | No manual marking | Flaky on different hardware; can't predict | Unreliable |
| Only run changed-file tests | Fastest possible | Complex dependency tracking; misses integration failures | Too risky for a pre-release project |

## References

- Implementation: `pyproject.toml` (`[tool.pytest.ini_options]` markers),
  `tests/conftest.py` (`--run-slow` option + auto-skip logic)
- Testing strategy: `contributor/reference/testing-strategy.md`
