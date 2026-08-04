"""The invariants `JobGraph` is only as good as (SG G4).

`JobGraph`'s docstring makes two promises that nothing enforced:

1. **It never reads `entry.function`.** On a warm boot that attribute is a
   deferred-import stand-in carrying no declaration and no annotations, so
   anything derived from it works on a cold boot and silently vanishes on a
   warm one. That exact divergence has already shipped in this codebase.
2. **Building validates.** Registration has three doors — discovery,
   `register_dynamic_job`, and `register_module` — and only one ever called a
   validator. The fix was to validate where every path must pass anyway, so a
   guard on N entry points became a guard on the thing they all need.

A docstring cannot fail. These tests can: the first hands `JobGraph` a
registry whose `function` attribute *raises on access*, so a read is not a
style violation but a crash with a pointer to this file.
"""

from __future__ import annotations

from typing import Any

import pytest

from functualize._engine.job_graph import JobGraph
from functualize._types.errors import JobDependencyError


class _ExplodingFunction:
    """Stands in for the one thing a warm boot does not have."""

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        raise AssertionError(
            "JobGraph read `entry.function`. On a warm boot that is a "
            "deferred-import stand-in with no declaration and no annotations, "
            "so whatever was just derived from it works cold and silently "
            "vanishes warm. Take the fact from `entry.dependencies` or from a "
            "declaration that survives the cache instead."
        )


class _WarmEntry:
    """A registry entry shaped like a warm-cache one: no live function."""

    function = _ExplodingFunction()

    def __init__(self, name: str, dependencies: tuple[str, ...] = ()) -> None:
        self.name = name
        self.dependencies = dependencies
        self.group = name.rsplit(".", 1)[0] if "." in name else None


def _warm_registry(**jobs: tuple[str, ...]) -> dict[str, Any]:
    return {name: _WarmEntry(name, deps) for name, deps in jobs.items()}


class TestNeverReadsTheFunction:
    """Every public entry point, against a registry that punishes the read."""

    def test_building_edges(self) -> None:
        graph = JobGraph(_warm_registry(lint=(), test=(), deploy=("lint", "test")))
        assert sorted(graph.edges["deploy"]) == ["lint", "test"]

    def test_ordering(self) -> None:
        graph = JobGraph(_warm_registry(a=(), b=("a",), c=("b",)))
        assert graph.order_for("c") == ["a", "b"]

    def test_validating(self) -> None:
        JobGraph(_warm_registry(a=(), b=("a",))).validate()

    def test_direct_dependencies(self) -> None:
        graph = JobGraph(_warm_registry(a=(), b=("a",)))
        assert graph.deps_of("b") == ["a"]

    def test_resolving_a_leaf_reference(self) -> None:
        """The path most tempted to match by function identity.

        Identity matching would resolve on a cold boot and fall through on a
        warm one — the divergence that shipped as `dependencies failed for
        'ship': compile_it`.
        """
        registry = _warm_registry(**{"build.compile-it": (), "ship": ("compile-it",)})
        assert JobGraph(registry).deps_of("ship") == ["build.compile-it"]

    def test_reporting_an_unknown_reference(self) -> None:
        """Even the error path must not reach for the function to describe it."""
        graph = JobGraph(_warm_registry(ship=("ghost",)))
        with pytest.raises(JobDependencyError, match="unknown job 'ghost'"):
            graph.validate()

    def test_reporting_a_cycle(self) -> None:
        graph = JobGraph(_warm_registry(a=("b",), b=("a",)))
        with pytest.raises(JobDependencyError, match="cycle"):
            graph.validate()


class TestTheInvariantTestItselfWorks:
    """A guard nobody has seen fail is a guard nobody should trust."""

    def test_the_stand_in_really_raises(self) -> None:
        entry = _WarmEntry("x")
        with pytest.raises(AssertionError, match="read `entry.function`"):
            _ = entry.function


class TestBuildingIsValidating:
    """The second door, pinned: no query can skip the check."""

    @pytest.mark.parametrize(
        "query",
        [
            lambda g: g.edges,
            lambda g: g.deps_of("ship"),
            lambda g: g.order_for("ship"),
            lambda g: g.validate(),
        ],
        ids=["edges", "deps_of", "order_for", "validate"],
    )
    def test_every_query_rejects_a_bad_reference(self, query: Any) -> None:
        graph = JobGraph(_warm_registry(ship=("ghost",)))
        with pytest.raises(JobDependencyError):
            query(graph)

    def test_a_rebuild_after_invalidate_revalidates(self) -> None:
        """`invalidate()` must not leave a validated verdict behind."""
        registry = _warm_registry(ship=())
        graph = JobGraph(registry)
        graph.validate()

        registry["ship"] = _WarmEntry("ship", ("ghost",))
        graph.invalidate()

        with pytest.raises(JobDependencyError, match="unknown job 'ghost'"):
            graph.validate()
