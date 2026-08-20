"""Property-based tests for pre-filter combinators (Property 2).

Tests the composable pre-filter combinators from functualize.primitives.pre_filter:
- Property 2: Pre-filter combinator boolean algebra

# Feature: unified-architecture-redesign, Property 2
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from functualize._primitives.pre_filter import AllOf, AnyOf, ModulePreFilter, NoneOf

# =============================================================================
# Helpers: Simple True/False returning filters for property testing
# =============================================================================


class ConstantFilter:
    """A filter that always returns a fixed boolean value.

    Satisfies ModulePreFilter Protocol via structural typing.
    """

    def __init__(self, result: bool) -> None:
        self._result = result

    def should_import(self, source_file: Path) -> bool:
        return self._result


# Strategy: generate a list of boolean values representing filter results
_filter_results_strategy = st.lists(st.booleans(), min_size=0, max_size=10)

# Strategy: generate a file path (content doesn't matter since we use constant filters)
_path_strategy = st.builds(
    Path,
    st.from_regex(r"[a-z][a-z0-9_]{0,8}\.py", fullmatch=True),
)


# =============================================================================
# Property 2: Pre-filter combinator boolean algebra
# =============================================================================


class TestPreFilterCombinatorBooleanAlgebra:
    """Property 2: Pre-filter combinator boolean algebra.

    For any set of ModulePreFilter implementations and any source file path,
    AllOf(*filters).should_import(path) SHALL equal
        all(f.should_import(path) for f in filters),
    AnyOf(*filters).should_import(path) SHALL equal
        any(f.should_import(path) for f in filters),
    and NoneOf(*filters).should_import(path) SHALL equal
        not any(f.should_import(path) for f in filters).

    **Validates: Requirements 1.7**
    """

    @given(filter_results=_filter_results_strategy, path=_path_strategy)
    def test_allof_equals_builtin_all(self, filter_results: list[bool], path: Path):
        """AllOf(*filters).should_import(path) == all(f.should_import(path) for f in filters).

        **Validates: Requirements 1.7**
        """
        filters = [ConstantFilter(r) for r in filter_results]
        combinator = AllOf(*filters)

        actual = combinator.should_import(path)
        expected = all(f.should_import(path) for f in filters)

        assert actual == expected

    @given(filter_results=_filter_results_strategy, path=_path_strategy)
    def test_anyof_equals_builtin_any(self, filter_results: list[bool], path: Path):
        """AnyOf(*filters).should_import(path) == any(f.should_import(path) for f in filters).

        **Validates: Requirements 1.7**
        """
        filters = [ConstantFilter(r) for r in filter_results]
        combinator = AnyOf(*filters)

        actual = combinator.should_import(path)
        expected = any(f.should_import(path) for f in filters)

        assert actual == expected

    @given(filter_results=_filter_results_strategy, path=_path_strategy)
    def test_noneof_equals_not_any(self, filter_results: list[bool], path: Path):
        """NoneOf(*filters).should_import(path) == not any(f.should_import(path) for f in filters).

        **Validates: Requirements 1.7**
        """
        filters = [ConstantFilter(r) for r in filter_results]
        combinator = NoneOf(*filters)

        actual = combinator.should_import(path)
        expected = not any(f.should_import(path) for f in filters)

        assert actual == expected

    @given(filter_results=_filter_results_strategy, path=_path_strategy)
    def test_noneof_is_complement_of_anyof(
        self, filter_results: list[bool], path: Path
    ):
        """NoneOf(*filters) is always the logical complement of AnyOf(*filters).

        **Validates: Requirements 1.7**
        """
        filters = [ConstantFilter(r) for r in filter_results]
        any_of = AnyOf(*filters)
        none_of = NoneOf(*filters)

        assert none_of.should_import(path) == (not any_of.should_import(path))

    @given(filter_results=_filter_results_strategy, path=_path_strategy)
    def test_combinators_satisfy_protocol(self, filter_results: list[bool], path: Path):
        """All combinators satisfy the ModulePreFilter Protocol via structural typing.

        **Validates: Requirements 1.7**
        """
        filters = [ConstantFilter(r) for r in filter_results]

        all_of = AllOf(*filters)
        any_of = AnyOf(*filters)
        none_of = NoneOf(*filters)

        assert isinstance(all_of, ModulePreFilter)
        assert isinstance(any_of, ModulePreFilter)
        assert isinstance(none_of, ModulePreFilter)

    @given(
        filter_results_a=_filter_results_strategy,
        filter_results_b=_filter_results_strategy,
        path=_path_strategy,
    )
    def test_allof_nested_composition(
        self, filter_results_a: list[bool], filter_results_b: list[bool], path: Path
    ):
        """Nested AllOf(AllOf(a...), AllOf(b...)) == AllOf(a... + b...).

        **Validates: Requirements 1.7**
        """
        filters_a = [ConstantFilter(r) for r in filter_results_a]
        filters_b = [ConstantFilter(r) for r in filter_results_b]

        # Nested composition
        nested = AllOf(AllOf(*filters_a), AllOf(*filters_b))
        # Flat composition
        flat = AllOf(*(filters_a + filters_b))

        assert nested.should_import(path) == flat.should_import(path)
