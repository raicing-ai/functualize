"""Property-based tests for RenameTransform bijection (Property 6).

Tests that RenameTransform correctly:
- Renames matching job names in transform_list, passes others through unchanged
- Blocks lookups by old (renamed-from) names via transform_get returning None
- Returns descriptor with new name when looking up by new (renamed-to) name

**Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5**
"""

from __future__ import annotations

import dataclasses

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from functualize._discovery.transforms import RenameTransform
from functualize._types.descriptors import FieldDescriptor, JobDescriptor
from functualize._types.job_declaration import JobDeclaration

# --- Strategies ---

# Generate valid job names (non-empty identifiers)
job_names = st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True).filter(
    lambda s: s.isidentifier()
)

# Generate optional group strings
groups = st.one_of(st.none(), st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True))

# These tests assert that RenameTransform preserves every field it does not rename,
# so the non-name fields must still *vary* — a constant everywhere would let a
# transform that blanked a field pass. What they do not need is expensive variation:
# `from_regex` (a 64-char hex hash among them) was drawn per field per descriptor.
# Sampling from a couple of prepared values keeps two distinguishable values per
# field at O(1) draw cost.
field_descriptors = st.sampled_from(
    [
        FieldDescriptor(
            name="alpha",
            type_annotation="str",
            choices=None,
            default=None,
            required=False,
            description="",
        ),
        FieldDescriptor(
            name="beta",
            type_annotation="int",
            choices=["x", "y"],
            default=3,
            required=True,
            description="beta field",
        ),
    ]
)

# Generate optional JobDeclaration
declaration_strategy = st.one_of(
    st.none(),
    st.builds(
        JobDeclaration,
        extra_description=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
        category=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
        examples=st.one_of(
            st.none(), st.lists(st.text(min_size=1, max_size=20), max_size=3)
        ),
        tags=st.one_of(
            st.none(), st.lists(st.text(min_size=1, max_size=10), max_size=5)
        ),
    ),
)

# Generate full JobDescriptor instances
job_descriptors = st.builds(
    JobDescriptor,
    name=job_names,
    group=groups,
    module_path=st.sampled_from(["pkg.mod", "other.pkg.deep"]),
    source_file=st.sampled_from(["/pkg/mod.py", "/other/deep.py"]),
    source_mtime=st.sampled_from([0.0, 1234.5]),
    content_hash=st.sampled_from(["0" * 64, "f" * 64]),
    docstring=st.sampled_from([None, "a docstring"]),
    config_fields=st.lists(field_descriptors, max_size=2),
    dependencies=st.sampled_from([{}, {"/pkg/dep.py": "a" * 64}]),
    declaration=declaration_strategy,
)


@st.composite
def rename_scenario(draw: st.DrawFn) -> tuple[dict[str, str], list[JobDescriptor]]:
    """Generate a valid rename mapping and a list of descriptors.

    Ensures:
    - Rename mapping keys and values are all distinct (bijection)
    - Some descriptors have names matching rename keys (will be renamed)
    - Some descriptors have names NOT in rename keys (pass-through)
    """
    # Generate rename mapping with distinct keys and distinct values
    num_renames = draw(st.integers(min_value=1, max_value=5))
    all_names = draw(
        st.lists(
            job_names,
            min_size=num_renames * 2,
            max_size=num_renames * 2,
            unique=True,
        )
    )
    old_names = all_names[:num_renames]
    new_names = all_names[num_renames:]
    renames = dict(zip(old_names, new_names, strict=False))

    # Generate descriptors - some with names that match rename keys, some without
    descriptors: list[JobDescriptor] = []

    # Add some descriptors with names in the rename mapping (will be renamed)
    num_matched = draw(st.integers(min_value=1, max_value=min(num_renames, 3)))
    for old_name in old_names[:num_matched]:
        desc = draw(job_descriptors)
        descriptors.append(dataclasses.replace(desc, name=old_name))

    # Add some descriptors with names NOT in the rename mapping (pass-through)
    num_unmatched = draw(st.integers(min_value=0, max_value=3))
    for _ in range(num_unmatched):
        desc = draw(job_descriptors)
        # Ensure name is not in renames keys or values
        assume(desc.name not in renames and desc.name not in renames.values())
        descriptors.append(desc)

    return renames, descriptors


# --- Property 6: RenameTransform bijection ---


@settings(suppress_health_check=[HealthCheck.too_slow])
@given(data=rename_scenario())
def test_property_6_transform_list_renames_matching_names(
    data: tuple[dict[str, str], list[JobDescriptor]],
) -> None:
    """RenameTransform.transform_list replaces names matching keys in renames
    with the corresponding values, and passes others through unchanged.

    **Validates: Requirements 12.1, 12.2**
    """
    renames, jobs = data
    transform = RenameTransform(renames)
    result = transform.transform_list(jobs)

    # Same length - rename doesn't add or remove
    assert len(result) == len(jobs)

    for original, transformed in zip(jobs, result, strict=False):
        if original.name in renames:
            # Name should be replaced with the new name
            expected_new_name = renames[original.name]
            assert transformed.name == expected_new_name, (
                f"Expected name '{expected_new_name}' but got '{transformed.name}' "
                f"for original '{original.name}'"
            )
            # All other fields should remain unchanged
            assert transformed.group == original.group
            assert transformed.module_path == original.module_path
            assert transformed.source_file == original.source_file
            assert transformed.content_hash == original.content_hash
            assert transformed.docstring == original.docstring
            assert transformed.config_fields == original.config_fields
            assert transformed.dependencies == original.dependencies
            assert transformed.declaration == original.declaration
        else:
            # Non-matching names pass through unchanged (same object)
            assert transformed is original, (
                f"Non-renamed job should be passed through unchanged. "
                f"name={original.name!r}"
            )


@settings(suppress_health_check=[HealthCheck.too_slow])
@given(data=rename_scenario())
def test_property_6_transform_get_old_name_returns_none(
    data: tuple[dict[str, str], list[JobDescriptor]],
) -> None:
    """RenameTransform.transform_get returns None when called with an old name
    that has been renamed (the old name is blocked).

    **Validates: Requirements 12.5**
    """
    renames, jobs = data
    transform = RenameTransform(renames)

    # For every old_name in renames, transform_get should return None
    # regardless of whether a descriptor is provided
    for old_name in renames:
        # Find a descriptor with this name if one exists
        matching = [j for j in jobs if j.name == old_name]
        descriptor = matching[0] if matching else None

        result = transform.transform_get(old_name, descriptor)
        assert result is None, (
            f"Expected None for renamed-from name '{old_name}', "
            f"but got descriptor with name '{result.name if result else None}'"
        )


@settings(suppress_health_check=[HealthCheck.too_slow])
@given(data=rename_scenario())
def test_property_6_transform_get_new_name_returns_descriptor_with_new_name(
    data: tuple[dict[str, str], list[JobDescriptor]],
) -> None:
    """RenameTransform.transform_get returns the descriptor with the new name
    applied when called with a new_name (value in renames mapping).

    **Validates: Requirements 12.3**
    """
    renames, jobs = data
    transform = RenameTransform(renames)

    # For every new_name in renames values, transform_get should return
    # the descriptor with name set to new_name (if a descriptor is provided)
    for old_name, new_name in renames.items():
        # Find a descriptor with the original name
        matching = [j for j in jobs if j.name == old_name]
        if not matching:
            continue

        original_desc = matching[0]
        # When looking up by new_name with the original descriptor,
        # transform_get should return it with the new name
        result = transform.transform_get(new_name, original_desc)
        assert result is not None, (
            f"Expected descriptor for new_name '{new_name}', got None"
        )
        assert result.name == new_name, (
            f"Expected result name '{new_name}', got '{result.name}'"
        )
        # All other fields preserved
        assert result.group == original_desc.group
        assert result.module_path == original_desc.module_path
        assert result.source_file == original_desc.source_file
        assert result.content_hash == original_desc.content_hash


@settings(suppress_health_check=[HealthCheck.too_slow])
@given(data=rename_scenario())
def test_property_6_transform_get_new_name_with_none_returns_none(
    data: tuple[dict[str, str], list[JobDescriptor]],
) -> None:
    """RenameTransform.transform_get returns None when called with a new_name
    but the job parameter is None (no underlying descriptor found).

    **Validates: Requirements 12.3**
    """
    renames, _jobs = data
    transform = RenameTransform(renames)

    # For every new_name, if job is None, result should be None
    for _old_name, new_name in renames.items():
        result = transform.transform_get(new_name, None)
        assert result is None, (
            f"Expected None when job is None for new_name '{new_name}', got {result}"
        )


@settings(suppress_health_check=[HealthCheck.too_slow])
@given(data=rename_scenario())
def test_property_6_transform_get_unrelated_name_passes_through(
    data: tuple[dict[str, str], list[JobDescriptor]],
) -> None:
    """RenameTransform.transform_get passes through names that are neither
    old names (keys) nor new names (values) in the renames mapping.

    **Validates: Requirements 12.4**
    """
    renames, jobs = data
    transform = RenameTransform(renames)

    # Find descriptors with names not involved in any rename
    unrelated = [
        j for j in jobs if j.name not in renames and j.name not in renames.values()
    ]

    for job in unrelated:
        result = transform.transform_get(job.name, job)
        assert result is job, (
            f"Expected pass-through for unrelated name '{job.name}', "
            f"but got different result"
        )
