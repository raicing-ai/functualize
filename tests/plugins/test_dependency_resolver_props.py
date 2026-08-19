"""Property-based tests for Plugin Dependency Topological Sort.

Tests Property 17 (Dependency Topological Sort) using Hypothesis.

**Validates: Requirements 13.1, 13.3, 13.4**
"""

from __future__ import annotations

import random
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._plugins.loader import (
    CircularDependencyError,
    MissingDependencyError,
    topological_sort,
)

# --- Fake Plugin ---


class FakePlugin:
    """Minimal fake plugin for testing."""

    def __init__(self, name: str, depends_on: list[str] | None = None) -> None:
        self.name = name
        self.version = "1.0.0"
        self.description = f"Plugin {name}"
        self.depends_on: list[str] | None = depends_on

    def __call__(self, app: Any) -> None:
        pass

    def __repr__(self) -> str:
        return f"FakePlugin({self.name!r}, depends_on={self.depends_on!r})"


# --- Strategies ---

# Strategy for valid plugin names (lowercase letters + digits, short)
plugin_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll",),  # type: ignore[arg-type]
        whitelist_characters="_",
    ),
    min_size=1,
    max_size=12,
)


@st.composite
def valid_dag_plugins(
    draw: st.DrawFn,
) -> list[FakePlugin]:
    """Generate a list of plugins forming a valid DAG (no cycles).

    Strategy: generate N unique plugin names, assign each plugin a
    subset of plugins that appear earlier in the list as dependencies.
    This guarantees a DAG because dependencies always point to
    earlier-indexed plugins.
    """
    n = draw(st.integers(min_value=1, max_value=8))
    names = draw(
        st.lists(
            plugin_names,
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    plugins: list[FakePlugin] = []
    for i, name in enumerate(names):
        if i == 0:
            plugins.append(FakePlugin(name, depends_on=[]))
        else:
            # Pick a subset of earlier plugins as deps
            available_deps = [names[j] for j in range(i)]
            deps = draw(
                st.lists(
                    st.sampled_from(available_deps),
                    min_size=0,
                    max_size=min(3, i),
                    unique=True,
                )
            )
            plugins.append(FakePlugin(name, depends_on=deps))

    # Shuffle the input order to verify sort is independent of input order
    shuffled = draw(st.permutations(plugins))
    return list(shuffled)


@st.composite
def circular_dependency_plugins(
    draw: st.DrawFn,
) -> list[FakePlugin]:
    """Generate a list of plugins with at least one circular dependency.

    Strategy: generate a cycle of length >= 2 among a subset of plugins.
    """
    cycle_len = draw(st.integers(min_value=2, max_value=5))
    names = draw(
        st.lists(
            plugin_names,
            min_size=cycle_len,
            max_size=cycle_len,
            unique=True,
        )
    )

    # Create a cycle: each plugin depends on the next, last depends on first
    plugins: list[FakePlugin] = []
    for i, name in enumerate(names):
        dep = names[(i + 1) % cycle_len]
        plugins.append(FakePlugin(name, depends_on=[dep]))

    return plugins


@st.composite
def missing_dependency_plugins(
    draw: st.DrawFn,
) -> tuple[list[FakePlugin], str]:
    """Generate plugins where at least one depends on a non-existent plugin.

    Returns:
        Tuple of (plugins list, name of the missing dependency).
    """
    n = draw(st.integers(min_value=1, max_value=5))
    names = draw(
        st.lists(
            plugin_names,
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    # Generate a missing name guaranteed not in the list
    missing_name = draw(plugin_names.filter(lambda x: x not in names))

    # Pick one plugin to depend on the missing name
    idx = draw(st.integers(min_value=0, max_value=n - 1))

    plugins: list[FakePlugin] = []
    for i, name in enumerate(names):
        if i == idx:
            plugins.append(FakePlugin(name, depends_on=[missing_name]))
        else:
            plugins.append(FakePlugin(name, depends_on=[]))

    return plugins, missing_name


# --- Property 17: Dependency Topological Sort ---


class TestDependencyTopologicalSort:
    """Property 17: For any valid DAG of plugins, topological_sort produces
    a correct ordering respecting all dependency edges, contains exactly the
    same plugins as input, uses stable alphabetical ordering for unrelated
    plugins, and raises appropriate errors for cycles and missing deps.

    **Validates: Requirements 13.1, 13.3, 13.4**
    """

    @given(plugins=valid_dag_plugins())
    def test_output_respects_all_dependency_edges(
        self, plugins: list[FakePlugin]
    ) -> None:
        """**Validates: Requirements 13.1**

        For any valid DAG, every dependency appears before its dependent
        in the output.
        """
        result = topological_sort(plugins)
        result_names = [p.name for p in result]
        name_to_index = {name: i for i, name in enumerate(result_names)}

        for plugin in result:
            deps: list[str] = plugin.depends_on or []
            for dep in deps:
                assert dep in name_to_index, (
                    f"Dependency '{dep}' of '{plugin.name}' not in output"
                )
                assert name_to_index[dep] < name_to_index[plugin.name], (
                    f"Dependency '{dep}' must appear before "
                    f"'{plugin.name}' in topological order, "
                    f"but got indices {name_to_index[dep]} >= "
                    f"{name_to_index[plugin.name]}"
                )

    @given(plugins=valid_dag_plugins())
    def test_output_contains_exactly_same_plugins(
        self, plugins: list[FakePlugin]
    ) -> None:
        """**Validates: Requirements 13.1**

        The output contains exactly the same plugins as the input:
        no duplicates, no missing.
        """
        result = topological_sort(plugins)
        input_names = sorted(p.name for p in plugins)
        output_names = sorted(p.name for p in result)

        # Same set of plugins
        assert input_names == output_names, (
            f"Input plugins: {input_names}, Output plugins: {output_names}"
        )

        # No duplicates in output
        result_names = [p.name for p in result]
        assert len(result_names) == len(set(result_names)), (
            f"Duplicate plugins in output: {result_names}"
        )

    @given(plugins=valid_dag_plugins())
    def test_stable_alphabetical_ordering_for_unrelated_plugins(
        self, plugins: list[FakePlugin]
    ) -> None:
        """**Validates: Requirements 13.1**

        For plugins with no dependencies between them, alphabetical
        ordering is stable — the output is deterministic regardless of
        input order. Specifically, plugins that are simultaneously
        available (same topological "wave") are ordered alphabetically.
        """
        result = topological_sort(plugins)
        result_names = [p.name for p in result]

        # The key property: output is deterministic regardless of input
        # ordering. Run again with a different permutation of the same
        # plugins and verify identical output.
        shuffled = list(plugins)
        random.shuffle(shuffled)
        result2 = topological_sort(shuffled)
        result2_names = [p.name for p in result2]

        assert result_names == result2_names, (
            f"Topological sort is not deterministic: {result_names} vs {result2_names}"
        )

        # Additional check: among plugins with no dependencies at all,
        # they must appear in alphabetical order relative to each other
        # at the start of the output (they all have in-degree 0).
        no_dep_names = sorted(p.name for p in plugins if not (p.depends_on or []))
        no_dep_indices = [result_names.index(n) for n in no_dep_names]
        # These should be in increasing order (alphabetically stable)
        assert no_dep_indices == sorted(no_dep_indices), (
            f"Zero-dependency plugins are not alphabetically ordered: "
            f"{list(zip(no_dep_names, no_dep_indices, strict=True))}"
        )

    @given(plugins=circular_dependency_plugins())
    def test_circular_dependencies_raise_error(self, plugins: list[FakePlugin]) -> None:
        """**Validates: Requirements 13.4**

        Circular dependencies always raise CircularDependencyError.
        """
        with pytest.raises(CircularDependencyError) as exc_info:
            topological_sort(plugins)

        # The error should contain a cycle path
        assert len(exc_info.value.cycle) >= 2
        # The cycle should form a valid loop (first == last)
        assert exc_info.value.cycle[0] == exc_info.value.cycle[-1]

    @given(data=missing_dependency_plugins())
    def test_missing_dependencies_raise_error(
        self, data: tuple[list[FakePlugin], str]
    ) -> None:
        """**Validates: Requirements 13.3**

        Missing dependencies always raise MissingDependencyError with
        identifying information.
        """
        plugins, missing_name = data

        with pytest.raises(MissingDependencyError) as exc_info:
            topological_sort(plugins)

        assert exc_info.value.missing == missing_name
        # The plugin_name should be one of the input plugins
        assert exc_info.value.plugin_name in [p.name for p in plugins]
