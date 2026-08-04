"""Property-based tests for primitives utilities (Properties 21–24).

Tests the core primitive utility functions from functualize.primitives:
- Property 21: first_non_none resolution chain
- Property 22: resilient generator completeness
- Property 23: iter_module_files filtering
- Property 24: lazy_cached single-computation guarantee

# Feature: unified-architecture-redesign, Properties 21–24
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._primitives import (
    first_non_none,
    iter_module_files,
    lazy_cached,
    resilient,
)

# =============================================================================
# Property 21: first_non_none resolution chain
# =============================================================================


# Strategy: generate a list of values where some may be None
_values_strategy = st.lists(
    st.one_of(
        st.none(),
        st.integers(),
        st.text(min_size=0, max_size=20),
        st.booleans(),
        st.floats(allow_nan=False),
    ),
    min_size=0,
    max_size=10,
)


class TestFirstNonNoneResolutionChain:
    """Property 21: first_non_none resolution chain.

    For any sequence of values (v1, v2, ..., vN) where some may be None,
    first_non_none(*values) SHALL return the first vi that is not None,
    or None if all values are None.

    **Validates: Requirements 1.10**
    """

    @given(values=_values_strategy)
    @settings(max_examples=200)
    def test_returns_first_non_none_value(self, values: list[Any]):
        """first_non_none returns the first non-None element in the sequence.

        **Validates: Requirements 1.10**
        """
        result = first_non_none(*values)

        # Compute expected via reference implementation
        expected = None
        for v in values:
            if v is not None:
                expected = v
                break

        assert result == expected

    @given(values=st.lists(st.none(), min_size=0, max_size=10))
    @settings(max_examples=100)
    def test_all_none_returns_none(self, values: list[None]):
        """When all values are None, first_non_none returns None.

        **Validates: Requirements 1.10**
        """
        result = first_non_none(*values)
        assert result is None

    @given(
        prefix_nones=st.integers(min_value=0, max_value=5),
        non_none_value=st.one_of(
            st.integers(), st.text(min_size=1, max_size=10), st.booleans()
        ),
        suffix=_values_strategy,
    )
    @settings(max_examples=200)
    def test_ignores_values_after_first_non_none(
        self,
        prefix_nones: int,
        non_none_value: Any,
        suffix: list[Any],
    ):
        """first_non_none stops at the first non-None and ignores the rest.

        **Validates: Requirements 1.10**
        """
        values = [None] * prefix_nones + [non_none_value] + suffix
        result = first_non_none(*values)
        assert result is non_none_value


# =============================================================================
# Property 22: resilient generator completeness
# =============================================================================


class _RaisingIterator:
    """An iterator that raises exceptions at specified indices but continues after."""

    def __init__(self, items: list[Any], error_indices: set[int]):
        self._items = items
        self._error_indices = error_indices
        self._index = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._index >= len(self._items):
            raise StopIteration
        i = self._index
        self._index += 1
        if i in self._error_indices:
            raise ValueError(f"error_at_{i}")
        return self._items[i]


@st.composite
def _iterable_with_errors(draw: st.DrawFn) -> tuple[list[Any], set[int]]:
    """Generate a list of items and a set of indices that should raise errors."""
    length = draw(st.integers(min_value=0, max_value=15))
    items = draw(
        st.lists(
            st.integers(min_value=-1000, max_value=1000),
            min_size=length,
            max_size=length,
        )
    )
    # Choose a subset of indices to be error indices
    error_indices = draw(
        st.frozensets(
            st.integers(min_value=0, max_value=max(0, length - 1)), max_size=length
        )
        if length > 0
        else st.just(frozenset())
    )
    return items, set(error_indices)


class TestResilientGeneratorCompleteness:
    """Property 22: resilient generator completeness.

    For any iterable where items at indices I_success produce values and items
    at indices I_error raise exceptions, resilient(iterable, on_error) SHALL
    yield exactly the values at I_success in order, call on_error exactly
    |I_error| times with the corresponding exceptions, and exhaust the iterable.

    **Validates: Requirements 1.12**
    """

    @given(data=_iterable_with_errors())
    @settings(max_examples=200)
    def test_yields_successful_items_in_order(self, data: tuple[list[Any], set[int]]):
        """resilient yields exactly the values at non-error indices in order.

        **Validates: Requirements 1.12**
        """
        items, error_indices = data
        errors_received: list[Exception] = []

        def on_error(exc: Exception) -> None:
            errors_received.append(exc)

        iterable = _RaisingIterator(items, error_indices)
        result = list(resilient(iterable, on_error))

        # Expected successful values: items at non-error indices, in order
        expected_values = [
            items[i] for i in range(len(items)) if i not in error_indices
        ]
        assert result == expected_values

    @given(data=_iterable_with_errors())
    @settings(max_examples=200)
    def test_calls_on_error_for_each_exception(self, data: tuple[list[Any], set[int]]):
        """resilient calls on_error exactly |I_error| times.

        **Validates: Requirements 1.12**
        """
        items, error_indices = data
        errors_received: list[Exception] = []

        def on_error(exc: Exception) -> None:
            errors_received.append(exc)

        iterable = _RaisingIterator(items, error_indices)
        # Consume the generator fully
        list(resilient(iterable, on_error))

        # on_error should have been called exactly once per error index
        assert len(errors_received) == len(error_indices)

    @given(data=_iterable_with_errors())
    @settings(max_examples=200)
    def test_on_error_receives_correct_exceptions(
        self, data: tuple[list[Any], set[int]]
    ):
        """on_error receives the exact exceptions raised at error indices.

        **Validates: Requirements 1.12**
        """
        items, error_indices = data
        errors_received: list[Exception] = []

        def on_error(exc: Exception) -> None:
            errors_received.append(exc)

        iterable = _RaisingIterator(items, error_indices)
        list(resilient(iterable, on_error))

        # Verify each error corresponds to the expected index
        sorted_error_indices = sorted(error_indices)
        for i, idx in enumerate(sorted_error_indices):
            assert isinstance(errors_received[i], ValueError)
            assert str(errors_received[i]) == f"error_at_{idx}"

    @given(data=_iterable_with_errors())
    @settings(max_examples=200)
    def test_exhausts_iterable_completely(self, data: tuple[list[Any], set[int]]):
        """resilient exhausts the entire iterable (processes all indices).

        **Validates: Requirements 1.12**
        """
        items, error_indices = data
        errors_received: list[Exception] = []

        def on_error(exc: Exception) -> None:
            errors_received.append(exc)

        iterable = _RaisingIterator(items, error_indices)
        result = list(resilient(iterable, on_error))

        # Total items processed = successful + errors = len(items)
        assert len(result) + len(errors_received) == len(items)


# =============================================================================
# Property 23: iter_module_files filtering
# =============================================================================


@st.composite
def _directory_with_files(draw: st.DrawFn) -> tuple[list[str], list[str]]:
    """Generate a list of filenames and the expected filtered subset.

    Returns (all_filenames, expected_module_files) where expected_module_files
    are those ending in .py, not __init__.py, and not inside __pycache__/.
    """
    # Generate valid filenames
    base_names = draw(
        st.lists(
            st.from_regex(r"[a-z][a-z0-9_]{0,12}", fullmatch=True),
            min_size=0,
            max_size=8,
            unique=True,
        )
    )

    all_files: list[str] = []
    expected: list[str] = []

    for name in base_names:
        # Decide what kind of file this is
        file_type = draw(
            st.sampled_from(["py_module", "py_init", "non_py", "py_underscore"])
        )

        if file_type == "py_module":
            filename = f"{name}.py"
            all_files.append(filename)
            expected.append(filename)
        elif file_type == "py_init":
            filename = "__init__.py"
            if filename not in all_files:
                all_files.append(filename)
            # __init__.py is excluded
        elif file_type == "non_py":
            ext = draw(st.sampled_from([".txt", ".md", ".json", ".yaml", ".cfg", ""]))
            filename = f"{name}{ext}"
            all_files.append(filename)
            # Non-.py files are excluded
        elif file_type == "py_underscore":
            # A .py file with a normal name (but underscore prefix not excluded
            # by iter_module_files — only __init__.py is excluded)
            filename = f"{name}.py"
            all_files.append(filename)
            expected.append(filename)

    return all_files, expected


class TestIterModuleFilesFiltering:
    """Property 23: iter_module_files filtering.

    For any directory containing files F, iter_module_files(directory) SHALL
    yield exactly the subset of F that ends in .py, is not __init__.py, and
    is not within __pycache__/.

    **Validates: Requirements 1.11**
    """

    @given(data=_directory_with_files())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_yields_only_qualifying_py_files(
        self, data: tuple[list[str], list[str]], tmp_path: Path
    ):
        """iter_module_files yields .py files excluding __init__.py and __pycache__.

        **Validates: Requirements 1.11**
        """
        all_files, expected_names = data

        # Create a unique subdirectory per hypothesis example to avoid collisions
        import tempfile

        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))

        # Create the directory structure
        for filename in all_files:
            (test_dir / filename).write_text(f"# {filename}")

        # Also create a __pycache__ directory with .py files (should be excluded)
        pycache_dir = test_dir / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "cached_module.py").write_text("# cached")

        # Run the function
        result = list(iter_module_files(test_dir))
        result_names = sorted(p.name for p in result)

        # Verify: result should be exactly the expected module files
        assert result_names == sorted(expected_names)

    @given(
        py_files=st.lists(
            st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True),
            min_size=1,
            max_size=6,
            unique=True,
        )
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_excludes_init_py(self, py_files: list[str], tmp_path: Path):
        """__init__.py is always excluded from results.

        **Validates: Requirements 1.11**
        """
        import tempfile

        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))

        # Create regular .py files and __init__.py
        for name in py_files:
            (test_dir / f"{name}.py").write_text(f"# {name}")
        (test_dir / "__init__.py").write_text("# init")

        result = list(iter_module_files(test_dir))
        result_names = [p.name for p in result]

        assert "__init__.py" not in result_names
        # All regular .py files should be present
        for name in py_files:
            assert f"{name}.py" in result_names

    @given(
        non_py_files=st.lists(
            st.from_regex(
                r"[a-z][a-z0-9_]{0,8}\.(txt|md|json|yaml|cfg)", fullmatch=True
            ),
            min_size=1,
            max_size=6,
            unique=True,
        )
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_excludes_non_py_files(self, non_py_files: list[str], tmp_path: Path):
        """Non-.py files are always excluded from results.

        **Validates: Requirements 1.11**
        """
        import tempfile

        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))

        for filename in non_py_files:
            (test_dir / filename).write_text(f"# {filename}")

        result = list(iter_module_files(test_dir))
        assert result == []

    @given(
        py_files=st.lists(
            st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True),
            min_size=1,
            max_size=6,
            unique=True,
        )
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_results_are_sorted(self, py_files: list[str], tmp_path: Path):
        """iter_module_files yields results in sorted order.

        **Validates: Requirements 1.11**
        """
        import tempfile

        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))

        for name in py_files:
            (test_dir / f"{name}.py").write_text(f"# {name}")

        result = list(iter_module_files(test_dir))
        result_names = [p.name for p in result]

        assert result_names == sorted(result_names)


# =============================================================================
# Property 24: lazy_cached single-computation guarantee
# =============================================================================


class TestLazyCachedSingleComputation:
    """Property 24: lazy_cached single-computation guarantee.

    For any class attribute decorated with lazy_cached and any instance, the
    underlying computation SHALL be invoked exactly once regardless of how many
    times the attribute is accessed, and all accesses SHALL return the same
    object (by identity).

    **Validates: Requirements 1.13**
    """

    @given(num_accesses=st.integers(min_value=1, max_value=20))
    @settings(max_examples=200)
    def test_computation_invoked_exactly_once(self, num_accesses: int):
        """The underlying function is called exactly once regardless of access count.

        **Validates: Requirements 1.13**
        """
        call_count = 0

        class MyClass:
            @lazy_cached
            def expensive(self) -> list[int]:
                nonlocal call_count
                call_count += 1
                return [1, 2, 3]

        obj = MyClass()

        for _ in range(num_accesses):
            _ = obj.expensive

        assert call_count == 1

    @given(num_accesses=st.integers(min_value=2, max_value=20))
    @settings(max_examples=200)
    def test_all_accesses_return_same_object_by_identity(self, num_accesses: int):
        """All accesses return the exact same object (by identity).

        **Validates: Requirements 1.13**
        """

        class MyClass:
            @lazy_cached
            def data(self) -> list[int]:
                return [42]

        obj = MyClass()
        first_result = obj.data

        for _ in range(num_accesses - 1):
            assert obj.data is first_result

    @given(num_instances=st.integers(min_value=2, max_value=10))
    @settings(max_examples=100)
    def test_separate_instances_have_independent_caches(self, num_instances: int):
        """Each instance computes independently — no cross-instance contamination.

        **Validates: Requirements 1.13**
        """
        call_counts: dict[int, int] = {}

        class MyClass:
            @lazy_cached
            def value(self) -> object:
                obj_id = id(self)
                call_counts[obj_id] = call_counts.get(obj_id, 0) + 1
                return object()  # unique object per call

        instances = [MyClass() for _ in range(num_instances)]

        # Access each instance's value
        results = [inst.value for inst in instances]

        # Each instance should have its own distinct cached object
        for i in range(num_instances):
            for j in range(i + 1, num_instances):
                assert results[i] is not results[j]

        # Each instance's computation was called exactly once
        for inst in instances:
            assert call_counts[id(inst)] == 1

    @given(num_accesses=st.integers(min_value=1, max_value=10))
    @settings(max_examples=100)
    def test_descriptor_access_on_class_returns_descriptor(self, num_accesses: int):
        """Accessing lazy_cached on the class (not instance) returns the descriptor.

        **Validates: Requirements 1.13**
        """

        class MyClass:
            @lazy_cached
            def prop(self) -> int:
                return 99

        for _ in range(num_accesses):
            descriptor = MyClass.prop
            assert isinstance(descriptor, lazy_cached)
