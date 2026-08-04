"""Property-based tests for hierarchy validation.

Uses Hypothesis to verify correctness properties across many random inputs.
"""

from __future__ import annotations

import os
from pathlib import Path

from hypothesis import assume, given
from hypothesis import strategies as st

from functualize._discovery.hierarchy import (
    ErrorFormatter,
    HierarchyValidationError,
    HierarchyValidator,
    ValidationContext,
    ValidationFailure,
    VersionResolver,
)

# Feature: hierarchy-validation, Property 1: Version specifier parsing extracts correct minimum
# **Validates: Requirements 1.4, 1.5**


# --- Strategies ---

version_component = st.integers(min_value=0, max_value=99)

version_tuple = st.tuples(version_component, version_component, version_component)


def version_string(ver: tuple[int, int, int]) -> str:
    """Format a version tuple as a dotted string."""
    return f"{ver[0]}.{ver[1]}.{ver[2]}"


# PEP 440 specifiers with a lower bound: >=, ==, ~=
pep440_bounded_specifier = version_tuple.map(
    lambda v: st.sampled_from(
        [
            (f">={version_string(v)}", v),
            (f"=={version_string(v)}", v),
            (f"~={version_string(v)}", v),
        ]
    )
).flatmap(lambda s: s)

# Poetry caret specifier: ^X.Y.Z
caret_specifier = version_tuple.map(lambda v: (f"^{version_string(v)}", v))

# Specifiers with no lower bound: !=, <, <=
no_lower_bound_specifier = version_tuple.flatmap(
    lambda v: st.sampled_from(
        [
            (f"!={version_string(v)}", None),
            (f"<{version_string(v)}", None),
            (f"<={version_string(v)}", None),
        ]
    )
)


# --- Property Tests ---


@given(data=pep440_bounded_specifier)
def test_pep440_bounded_specifier_extracts_correct_minimum(
    data: tuple[str, tuple[int, int, int]],
) -> None:
    """PEP 440 specifiers with lower bounds (>=, ==, ~=) return the correct minimum version.

    **Validates: Requirements 1.4, 1.5**
    """
    specifier_str, expected_version = data

    result = VersionResolver._extract_minimum_version(specifier_str)

    assert result == expected_version, (
        f"Expected {expected_version} for specifier '{specifier_str}', got {result}"
    )


@given(data=caret_specifier)
def test_caret_specifier_extracts_correct_minimum(
    data: tuple[str, tuple[int, int, int]],
) -> None:
    """Poetry caret specifiers (^X.Y.Z) return the correct minimum version.

    **Validates: Requirements 1.4, 1.5**
    """
    specifier_str, expected_version = data

    result = VersionResolver._extract_minimum_version(specifier_str)

    assert result == expected_version, (
        f"Expected {expected_version} for specifier '{specifier_str}', got {result}"
    )


@given(data=no_lower_bound_specifier)
def test_no_lower_bound_specifier_returns_none(
    data: tuple[str, None],
) -> None:
    """Specifiers without a lower bound (!=, <, <=) return None.

    **Validates: Requirements 1.4, 1.5**
    """
    specifier_str, expected = data

    result = VersionResolver._extract_minimum_version(specifier_str)

    assert result is None, (
        f"Expected None for specifier '{specifier_str}', got {result}"
    )


# Feature: hierarchy-validation, Property 2: Version compatibility classification is correct


@given(
    parent_version=version_tuple,
    child_version=version_tuple,
)
def test_version_compatibility_classification_is_correct(
    parent_version: tuple[int, int, int],
    child_version: tuple[int, int, int],
) -> None:
    """Version compatibility returns True iff child (major, minor) >= parent (major, minor).

    **Validates: Requirements 2.1, 2.2, 2.4**
    """

    result = HierarchyValidator.check_version_compatibility(
        child_version=child_version,
        parent_version=parent_version,
    )

    child_major, child_minor, _ = child_version
    parent_major, parent_minor, _ = parent_version

    expected = (child_major, child_minor) >= (parent_major, parent_minor)

    assert result == expected, (
        f"check_version_compatibility({child_version}, {parent_version}) "
        f"returned {result}, expected {expected}"
    )


@given(
    child_version=version_tuple,
)
def test_version_compatibility_none_parent_always_compatible(
    child_version: tuple[int, int, int],
) -> None:
    """When parent version is None, compatibility always returns True.

    **Validates: Requirements 2.1, 2.2, 2.4**
    """

    result = HierarchyValidator.check_version_compatibility(
        child_version=child_version,
        parent_version=None,
    )

    assert result is True, f"Expected True when parent_version is None, got {result}"


@given(
    parent_version=version_tuple,
)
def test_version_compatibility_none_child_always_compatible(
    parent_version: tuple[int, int, int],
) -> None:
    """When child version is None, compatibility always returns True.

    **Validates: Requirements 2.1, 2.2, 2.4**
    """

    result = HierarchyValidator.check_version_compatibility(
        child_version=None,
        parent_version=parent_version,
    )

    assert result is True, f"Expected True when child_version is None, got {result}"


# Feature: hierarchy-validation, Property 3: Incompatibility messages contain all required fields
# **Validates: Requirements 2.2, 2.6, 5.1**

# --- Strategies for Property 3 ---

namespace_strategy = st.text(min_size=1, alphabet="abcdefghijklmnopqrstuvwxyz")
path_strategy = st.text(min_size=1)


@given(
    namespace=namespace_strategy,
    path=path_strategy,
    child_version=version_tuple,
    parent_version=version_tuple,
)
def test_incompatibility_message_contains_all_required_fields(
    namespace: str,
    path: str,
    child_version: tuple[int, int, int],
    parent_version: tuple[int, int, int],
) -> None:
    """Incompatibility messages contain all four required values: namespace, path, child version, parent version.

    **Validates: Requirements 2.2, 2.6, 5.1**
    """
    message = ErrorFormatter.format_version_warning(
        child_namespace=namespace,
        child_path=path,
        child_version=child_version,
        parent_version=parent_version,
    )

    child_ver_str = f"{child_version[0]}.{child_version[1]}.{child_version[2]}"
    parent_ver_str = f"{parent_version[0]}.{parent_version[1]}.{parent_version[2]}"

    assert namespace in message, (
        f"Expected namespace '{namespace}' in message: {message}"
    )
    assert path in message, f"Expected path '{path}' in message: {message}"
    assert child_ver_str in message, (
        f"Expected child version '{child_ver_str}' in message: {message}"
    )
    assert parent_ver_str in message, (
        f"Expected parent version '{parent_ver_str}' in message: {message}"
    )


# Feature: hierarchy-validation, Property 6: Path canonicalization is idempotent
# **Validates: Requirements 3.5**

# --- Strategies for path generation ---

path_segment = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="/."),
    min_size=1,
    max_size=100,
)

path_from_segments = st.lists(
    st.one_of(
        st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=10,
        ),
        st.just("."),
        st.just(".."),
    ),
    min_size=1,
    max_size=10,
).map(lambda segments: "/".join(segments))


# --- Property Tests ---


@given(p=path_segment)
def test_path_canonicalization_is_idempotent_text(p: str) -> None:
    """Applying os.path.realpath twice gives the same result as applying it once.

    **Validates: Requirements 3.5**
    """
    once = os.path.realpath(p)
    twice = os.path.realpath(once)
    assert twice == once, (
        f"Path canonicalization is not idempotent: "
        f"realpath('{p}') = '{once}', realpath(realpath('{p}')) = '{twice}'"
    )


@given(p=path_from_segments)
def test_path_canonicalization_is_idempotent_segments(p: str) -> None:
    """Applying os.path.realpath twice on segment-based paths gives the same result as once.

    **Validates: Requirements 3.5**
    """
    once = os.path.realpath(p)
    twice = os.path.realpath(once)
    assert twice == once, (
        f"Path canonicalization is not idempotent: "
        f"realpath('{p}') = '{once}', realpath(realpath('{p}')) = '{twice}'"
    )


# Feature: hierarchy-validation, Property 5: Ancestry chain accumulates correctly through transitive children

# --- Strategies for Property 5 ---

# Generate unique path segments for building a chain of projects
unique_path_segments = st.lists(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"), whitelist_characters="-_"
        ),
        min_size=1,
        max_size=20,
    ),
    min_size=1,
    max_size=8,
    unique=True,
)


@given(segments=unique_path_segments)
def test_ancestry_chain_accumulates_correctly_through_transitive_children(
    segments: list[str],
) -> None:
    """Ancestry chain accumulates all parent paths plus child path through transitive children.

    Starting from a root context, iteratively calling child_context for each path
    ensures that:
    - The new context's ancestry_chain contains all previous paths plus the new child path
    - The new context's depth equals parent depth + 1
    - The ancestry_list is ordered correctly (matches insertion order)

    **Validates: Requirements 3.3, 3.4**
    """
    # Build unique absolute paths from segments
    paths = [Path(f"/projects/{seg}") for seg in segments]

    # Create root context with the first path as root
    root_path = paths[0]
    context = HierarchyValidator.create_root_context(
        root_path=root_path,
        parent_version=(1, 0, 0),
        strict=False,
    )

    # Verify root context initialization

    canonical_root = os.path.realpath(str(root_path))
    assert canonical_root in context.ancestry_chain
    assert context.ancestry_list == [canonical_root]
    assert context.depth == 0

    # Iteratively create child contexts for remaining paths
    expected_ancestry_list = [canonical_root]

    for i, child_path in enumerate(paths[1:], start=1):
        parent_context = context
        context = HierarchyValidator.child_context(
            child_path=child_path,
            parent_context=parent_context,
        )

        canonical_child = os.path.realpath(str(child_path))
        expected_ancestry_list.append(canonical_child)

        # Assert ancestry_chain contains all previous paths plus the new child path
        for prev_path in expected_ancestry_list:
            assert prev_path in context.ancestry_chain, (
                f"Expected {prev_path} in ancestry_chain at depth {i}, "
                f"got {context.ancestry_chain}"
            )

        # Assert ancestry_chain size matches expected
        assert len(context.ancestry_chain) == len(expected_ancestry_list), (
            f"Expected ancestry_chain size {len(expected_ancestry_list)} at depth {i}, "
            f"got {len(context.ancestry_chain)}"
        )

        # Assert depth equals parent depth + 1
        assert context.depth == parent_context.depth + 1, (
            f"Expected depth {parent_context.depth + 1}, got {context.depth}"
        )
        assert context.depth == i, f"Expected depth {i}, got {context.depth}"

        # Assert ancestry_list is ordered correctly
        assert context.ancestry_list == expected_ancestry_list, (
            f"Expected ancestry_list {expected_ancestry_list}, "
            f"got {context.ancestry_list}"
        )


# Feature: hierarchy-validation, Property 4: Cycle detection is correct
# **Validates: Requirements 3.1, 3.2, 5.2**


# --- Strategies for Property 4 ---

# Generate unique path segments for building canonical absolute paths
path_segment = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=10,
)

# Generate a list of unique absolute path strings (simulating canonical paths)
unique_canonical_paths = st.lists(
    path_segment,
    min_size=1,
    max_size=8,
    unique=True,
).map(lambda segments: [f"/project/{seg}" for seg in segments])


# --- Property Tests for Cycle Detection ---


@given(
    ancestry_paths=unique_canonical_paths,
    data=st.data(),
)
def test_cycle_detected_when_child_in_ancestry(
    ancestry_paths: list[str],
    data: st.DataObject,
) -> None:
    """validate_child detects a cycle when the child's canonical path is in the ancestry chain.

    **Validates: Requirements 3.1, 3.2, 5.2**
    """
    # Pick one path from the ancestry to use as the child (creating a cycle)
    child_path_str = data.draw(st.sampled_from(ancestry_paths))

    context = ValidationContext(
        ancestry_chain=set(ancestry_paths),
        ancestry_list=list(ancestry_paths),
        parent_version=None,
        strict=False,
        depth=0,
        max_depth=10,
    )

    result = HierarchyValidator.validate_child(
        child_namespace="test_child",
        child_path=Path(child_path_str),
        context=context,
    )

    # A cycle MUST be detected
    assert result is not None, (
        f"Expected cycle detection for path '{child_path_str}' "
        f"in ancestry {ancestry_paths}"
    )
    assert result.failure_type == "cycle_detected"

    # The reason must contain " → " separators forming the full cycle path
    assert " \u2192 " in result.reason, (
        f"Cycle error message must contain ' \u2192 ' separators, got: {result.reason}"
    )

    # The formatted cycle path should end with the repeated path
    # and contain all ancestry paths in order
    for ancestor in ancestry_paths:
        assert ancestor in result.reason, (
            f"Cycle error message must contain ancestor '{ancestor}', "
            f"got: {result.reason}"
        )
    # The repeated (child) path should appear at the end of the chain
    assert result.reason.endswith(child_path_str), (
        f"Cycle error message must end with the repeated path '{child_path_str}', "
        f"got: {result.reason}"
    )


@given(
    ancestry_paths=unique_canonical_paths,
    fresh_segment=path_segment,
)
def test_no_cycle_when_child_not_in_ancestry(
    ancestry_paths: list[str],
    fresh_segment: str,
) -> None:
    """validate_child returns None (no failure) when the child's path is NOT in the ancestry chain.

    **Validates: Requirements 3.1, 3.2, 5.2**
    """
    # Create a child path that is guaranteed not to be in the ancestry
    child_path_str = f"/project/fresh_{fresh_segment}_unique"

    # Ensure the child path is truly not in the ancestry
    # (extremely unlikely but let's be safe with the strategy)

    assume(child_path_str not in ancestry_paths)

    context = ValidationContext(
        ancestry_chain=set(ancestry_paths),
        ancestry_list=list(ancestry_paths),
        parent_version=None,
        strict=False,
        depth=0,
        max_depth=10,
    )

    result = HierarchyValidator.validate_child(
        child_namespace="test_child",
        child_path=Path(child_path_str),
        context=context,
    )

    # No cycle should be detected (and no other failure since depth=0 < max_depth=10
    # and parent_version=None skips version check)
    assert result is None, (
        f"Expected no failure for path '{child_path_str}' not in ancestry "
        f"{ancestry_paths}, but got: {result}"
    )


@given(
    ancestry_paths=unique_canonical_paths,
    data=st.data(),
)
def test_cycle_message_contains_ordered_path_with_arrow_separators(
    ancestry_paths: list[str],
    data: st.DataObject,
) -> None:
    """When a cycle is detected, the error message contains the full ordered path with ' → ' separators.

    **Validates: Requirements 3.1, 3.2, 5.2**
    """
    # Pick one path from the ancestry to create a cycle
    child_path_str = data.draw(st.sampled_from(ancestry_paths))

    context = ValidationContext(
        ancestry_chain=set(ancestry_paths),
        ancestry_list=list(ancestry_paths),
        parent_version=None,
        strict=False,
        depth=0,
        max_depth=10,
    )

    result = HierarchyValidator.validate_child(
        child_namespace="test_child",
        child_path=Path(child_path_str),
        context=context,
    )

    assert result is not None
    assert result.failure_type == "cycle_detected"

    # The cycle path in the reason should be: "ancestry[0] → ancestry[1] → ... → child_path"
    expected_cycle_path = " \u2192 ".join([*ancestry_paths, child_path_str])
    assert expected_cycle_path in result.reason, (
        f"Expected cycle path '{expected_cycle_path}' in reason, got: {result.reason}"
    )


# Feature: hierarchy-validation, Property 7: Depth limit enforcement at boundary


@given(
    depth=st.integers(min_value=0, max_value=20),
    max_depth=st.integers(min_value=1, max_value=20),
)
def test_depth_limit_enforcement_at_boundary(
    depth: int,
    max_depth: int,
) -> None:
    """validate_child returns depth-exceeded failure iff depth >= max_depth.

    **Validates: Requirements 3.7**
    """

    # Create a simple ancestry chain that won't trigger cycle detection
    ancestry_paths = {f"/fake/ancestor/{i}" for i in range(depth)}
    ancestry_list = [f"/fake/ancestor/{i}" for i in range(depth)]

    context = ValidationContext(
        ancestry_chain=ancestry_paths,
        ancestry_list=ancestry_list,
        parent_version=(1, 0, 0),
        strict=False,
        depth=depth,
        max_depth=max_depth,
    )

    # Use a child path NOT in the ancestry chain to avoid cycle detection
    child_path = Path("/fake/child/project")

    result = HierarchyValidator.validate_child(
        child_namespace="test-child",
        child_path=child_path,
        context=context,
    )

    if depth >= max_depth:
        assert result is not None, (
            f"Expected ValidationFailure when depth={depth} >= max_depth={max_depth}, "
            f"got None"
        )
        assert isinstance(result, ValidationFailure)
        assert result.failure_type == "depth_exceeded", (
            f"Expected failure_type='depth_exceeded', got '{result.failure_type}'"
        )
    else:
        assert result is None, (
            f"Expected None when depth={depth} < max_depth={max_depth}, "
            f"got ValidationFailure(failure_type='{result.failure_type}')"
        )


# Feature: hierarchy-validation, Property 9: Strict mode aggregates all failures

# --- Strategies for Property 9 ---

failure_type_strategy = st.sampled_from(
    ["version_incompatible", "cycle_detected", "depth_exceeded"]
)

validation_failure_strategy = st.builds(
    ValidationFailure,
    child_namespace=st.text(min_size=1, max_size=20),
    child_path=st.text(min_size=1, max_size=50),
    reason=st.text(min_size=1, max_size=100),
    failure_type=failure_type_strategy,
)


@given(
    failures=st.lists(validation_failure_strategy, min_size=1, max_size=20),
)
def test_strict_mode_aggregates_all_failures(
    failures: list[ValidationFailure],
) -> None:
    """Strict mode HierarchyValidationError contains all failures and length matches total failed.

    **Validates: Requirements 4.4**
    """
    error = HierarchyValidationError(
        message=f"Hierarchy validation failed for {len(failures)} child project(s) (strict mode enabled)",
        failures=failures,
    )

    # Assert that error.failures has the same length as the input list
    assert len(error.failures) == len(failures), (
        f"Expected {len(failures)} failures in error, got {len(error.failures)}"
    )

    # Assert that all failures are present in error.failures
    for failure in failures:
        assert failure in error.failures, (
            f"Expected failure {failure} to be present in error.failures"
        )
