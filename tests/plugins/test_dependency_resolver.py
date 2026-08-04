"""Unit tests for plugin dependency resolver."""

from __future__ import annotations

from typing import Any

import pytest

from functualize._plugins.loader import (
    CircularDependencyError,
    MissingDependencyError,
    topological_sort,
)


class FakePlugin:
    """Minimal fake plugin with required attributes."""

    def __init__(
        self,
        name: str,
        depends_on: list[str] | None = None,
    ) -> None:
        self.name = name
        self.version = "1.0.0"
        self.description = f"Plugin {name}"
        self.depends_on = depends_on

    def __call__(self, app: Any) -> None:
        pass


class TestTopologicalSort:
    """Tests for topological_sort function."""

    def test_empty_list(self) -> None:
        """Empty plugin list returns empty result."""
        result = topological_sort([])
        assert result == []

    def test_single_plugin_no_deps(self) -> None:
        """Single plugin with no dependencies."""
        p = FakePlugin("alpha")
        result = topological_sort([p])
        assert result == [p]

    def test_multiple_plugins_no_deps_alphabetical(self) -> None:
        """Plugins with no dependencies are sorted alphabetically."""
        c = FakePlugin("charlie")
        a = FakePlugin("alpha")
        b = FakePlugin("bravo")
        result = topological_sort([c, a, b])
        names = [p.name for p in result]
        assert names == ["alpha", "bravo", "charlie"]

    def test_linear_dependency_chain(self) -> None:
        """A -> B -> C: C depends on B, B depends on A."""
        a = FakePlugin("a")
        b = FakePlugin("b", depends_on=["a"])
        c = FakePlugin("c", depends_on=["b"])
        result = topological_sort([c, b, a])
        names = [p.name for p in result]
        assert names == ["a", "b", "c"]

    def test_diamond_dependency(self) -> None:
        """Diamond: D depends on B and C; B and C depend on A."""
        a = FakePlugin("a")
        b = FakePlugin("b", depends_on=["a"])
        c = FakePlugin("c", depends_on=["a"])
        d = FakePlugin("d", depends_on=["b", "c"])
        result = topological_sort([d, c, b, a])
        names = [p.name for p in result]
        # A must come first, then B and C (alphabetical), then D
        assert names.index("a") < names.index("b")
        assert names.index("a") < names.index("c")
        assert names.index("b") < names.index("d")
        assert names.index("c") < names.index("d")
        assert names == ["a", "b", "c", "d"]

    def test_multiple_dependencies(self) -> None:
        """Plugin with multiple dependencies."""
        a = FakePlugin("a")
        b = FakePlugin("b")
        c = FakePlugin("c", depends_on=["a", "b"])
        result = topological_sort([c, b, a])
        names = [p.name for p in result]
        assert names.index("a") < names.index("c")
        assert names.index("b") < names.index("c")

    def test_none_depends_on_treated_as_empty(self) -> None:
        """Plugin with depends_on=None is treated as no dependencies."""
        a = FakePlugin("a", depends_on=None)
        b = FakePlugin("b", depends_on=None)
        result = topological_sort([b, a])
        names = [p.name for p in result]
        assert names == ["a", "b"]

    def test_plugin_without_depends_on_attribute(self) -> None:
        """Plugin object without depends_on attribute works fine."""

        class MinimalPlugin:
            name = "minimal"
            version = "1.0.0"
            description = "Minimal"

            def __call__(self, app: Any) -> None:
                pass

        p = MinimalPlugin()
        result = topological_sort([p])
        assert result == [p]

    def test_stable_ordering_deterministic(self) -> None:
        """Same input produces same output every time."""
        plugins = [FakePlugin(f"plugin_{i}") for i in range(10)]
        result1 = topological_sort(plugins)
        result2 = topological_sort(plugins)
        assert [p.name for p in result1] == [p.name for p in result2]


class TestMissingDependencyError:
    """Tests for MissingDependencyError."""

    def test_missing_dependency_raised(self) -> None:
        """Raises MissingDependencyError when dependency not in plugin list."""
        a = FakePlugin("a", depends_on=["missing_plugin"])
        with pytest.raises(MissingDependencyError) as exc_info:
            topological_sort([a])
        assert exc_info.value.plugin_name == "a"
        assert exc_info.value.missing == "missing_plugin"

    def test_error_message_contains_details(self) -> None:
        """Error message includes plugin name and missing dependency."""
        a = FakePlugin("my_plugin", depends_on=["nonexistent"])
        with pytest.raises(MissingDependencyError, match="my_plugin"):
            topological_sort([a])

    def test_missing_dependency_attributes(self) -> None:
        """Error exposes plugin_name and missing attributes."""
        err = MissingDependencyError("foo", "bar")
        assert err.plugin_name == "foo"
        assert err.missing == "bar"
        assert "foo" in str(err)
        assert "bar" in str(err)


class TestCircularDependencyError:
    """Tests for CircularDependencyError."""

    def test_simple_cycle_detected(self) -> None:
        """Direct circular dependency A -> B -> A."""
        a = FakePlugin("a", depends_on=["b"])
        b = FakePlugin("b", depends_on=["a"])
        with pytest.raises(CircularDependencyError) as exc_info:
            topological_sort([a, b])
        # Cycle should contain both nodes
        assert "a" in exc_info.value.cycle
        assert "b" in exc_info.value.cycle

    def test_three_node_cycle(self) -> None:
        """Cycle among three plugins: A -> B -> C -> A."""
        a = FakePlugin("a", depends_on=["c"])
        b = FakePlugin("b", depends_on=["a"])
        c = FakePlugin("c", depends_on=["b"])
        with pytest.raises(CircularDependencyError) as exc_info:
            topological_sort([a, b, c])
        assert len(exc_info.value.cycle) >= 3

    def test_cycle_with_non_cyclic_plugins(self) -> None:
        """Cycle detected even when some plugins are not in the cycle."""
        # x has no deps, a and b form a cycle
        x = FakePlugin("x")
        a = FakePlugin("a", depends_on=["b"])
        b = FakePlugin("b", depends_on=["a"])
        with pytest.raises(CircularDependencyError):
            topological_sort([x, a, b])

    def test_error_cycle_path_format(self) -> None:
        """Error message contains cycle path with arrows."""
        err = CircularDependencyError(["a", "b", "a"])
        assert "a -> b -> a" in str(err)

    def test_self_dependency_cycle(self) -> None:
        """Plugin depending on itself causes a cycle."""
        a = FakePlugin("a", depends_on=["a"])
        with pytest.raises(CircularDependencyError) as exc_info:
            topological_sort([a])
        assert "a" in exc_info.value.cycle
