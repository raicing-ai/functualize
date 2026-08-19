"""Property-based tests for NamespaceTransform round-trip (Property 3).

Tests that NamespaceTransform correctly prefixes all job names with the form
"{prefix}{separator}{original_name}" in transform_list, and that transform_get
returns None for non-prefixed names.

**Validates: Requirements 9.2, 9.3, 9.4**
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from functualize._discovery.transforms import NamespaceTransform
from functualize._types.descriptors import FieldDescriptor, JobDescriptor
from functualize._types.job_declaration import JobDeclaration
from functualize._types.naming import normalize_name

# --- Strategies (reused from test_transform_identity_property.py) ---

# Generate valid job names (non-empty identifiers)
job_names = st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True).filter(
    lambda s: s.isidentifier()
)

# Generate optional group strings
groups = st.one_of(st.none(), st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True))

# Generate FieldDescriptor instances
field_descriptors = st.builds(
    FieldDescriptor,
    name=st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True),
    type_annotation=st.sampled_from(
        ["str", "int", "bool", "float", "enum", "list[str]"]
    ),
    choices=st.one_of(
        st.none(), st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=5)
    ),
    default=st.one_of(st.none(), st.text(max_size=10), st.integers(-100, 100)),
    required=st.booleans(),
    description=st.text(max_size=30),
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
    module_path=st.from_regex(r"[a-z][a-z0-9_.]{0,30}", fullmatch=True),
    source_file=st.from_regex(r"/[a-z][a-z0-9_/]{0,30}\.py", fullmatch=True),
    source_mtime=st.floats(min_value=0.0, max_value=1e12, allow_nan=False),
    content_hash=st.from_regex(r"[0-9a-f]{64}", fullmatch=True),
    docstring=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
    config_fields=st.lists(field_descriptors, max_size=3),
    dependencies=st.dictionaries(
        st.from_regex(r"/[a-z][a-z0-9_/]{0,20}\.py", fullmatch=True),
        st.from_regex(r"[0-9a-f]{64}", fullmatch=True),
        max_size=3,
    ),
    declaration=declaration_strategy,
)

# Generate lists of JobDescriptors (the main input)
job_descriptor_lists = st.lists(job_descriptors, min_size=0, max_size=10)

# Generate valid non-empty prefixes (identifiers without separator characters)
prefixes = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)

# Generate valid separators (non-empty, common separator chars)
separators = st.sampled_from([":", ".", "/", "-", "_", "::", "->"])


# --- Property 3: NamespaceTransform round-trip ---


@given(prefix=prefixes, separator=separators, jobs=job_descriptor_lists)
def test_property_3_transform_list_prefixes_all_names(
    prefix: str, separator: str, jobs: list[JobDescriptor]
) -> None:
    """For any valid prefix, separator, and list of JobDescriptors, applying
    NamespaceTransform.transform_list produces output names of the form
    "{prefix}{separator}{original_name}" for every descriptor.

    The transform must:
    - Preserve the number of descriptors (no filtering)
    - Produce names matching the expected "{prefix}{separator}{original}" pattern
    - Preserve all other descriptor fields unchanged

    **Validates: Requirements 9.2, 9.3, 9.4**
    """
    transform = NamespaceTransform(prefix=prefix, separator=separator)
    result = transform.transform_list(jobs)

    # Same length — namespace transform doesn't filter
    assert len(result) == len(jobs), (
        f"NamespaceTransform changed list length: input={len(jobs)}, output={len(result)}"
    )

    # A namespace is a group segment, so the transform publishes it canonical.
    full_prefix = f"{normalize_name(prefix)}{separator}"

    for i, (original, transformed) in enumerate(zip(jobs, result, strict=False)):
        expected_name = f"{full_prefix}{original.name}"
        assert transformed.name == expected_name, (
            f"At index {i}: expected name '{expected_name}', "
            f"got '{transformed.name}' (original='{original.name}', "
            f"prefix='{prefix}', separator='{separator}')"
        )

        # All other fields must be unchanged
        assert transformed.group == original.group
        assert transformed.module_path == original.module_path
        assert transformed.source_file == original.source_file
        assert transformed.source_mtime == original.source_mtime
        assert transformed.content_hash == original.content_hash
        assert transformed.docstring == original.docstring
        assert transformed.config_fields == original.config_fields
        assert transformed.dependencies == original.dependencies
        assert transformed.declaration == original.declaration


@given(prefix=prefixes, separator=separators, name=job_names)
def test_property_3_transform_get_returns_none_for_non_prefixed_names(
    prefix: str, separator: str, name: str
) -> None:
    """For any valid prefix and separator, calling transform_get with a name
    that does NOT start with "{prefix}{separator}" returns None, regardless
    of whether a job descriptor is provided.

    This validates that NamespaceTransform correctly rejects lookups for names
    outside its namespace.

    **Validates: Requirements 9.2, 9.3, 9.4**
    """
    transform = NamespaceTransform(prefix=prefix, separator=separator)
    full_prefix = f"{prefix}{separator}"

    # Ensure the name does not start with the full prefix
    # Since our name strategy generates identifiers like "abc_def" and prefixes
    # are also identifiers, we construct a non-prefixed name by using the raw name
    # only when it doesn't accidentally match
    if name.startswith((full_prefix, f"{normalize_name(prefix)}{separator}")):
        # Skip this case — it would be a valid prefixed name
        return

    # With a real job descriptor provided — should still return None
    dummy_job = JobDescriptor(
        name=name,
        group=None,
        module_path="test.module",
        source_file="/test.py",
        source_mtime=0.0,
        content_hash="a" * 64,
        docstring=None,
        config_fields=[],
        dependencies={},
        declaration=None,
    )

    result = transform.transform_get(name, dummy_job)
    assert result is None, (
        f"transform_get should return None for non-prefixed name '{name}' "
        f"(prefix='{prefix}', separator='{separator}', full_prefix='{full_prefix}')"
    )

    # With None job — should also return None
    result_none = transform.transform_get(name, None)
    assert result_none is None, (
        f"transform_get should return None for non-prefixed name '{name}' "
        f"even when job is None"
    )


@given(prefix=prefixes, separator=separators, job=job_descriptors)
def test_property_3_transform_get_returns_prefixed_for_valid_names(
    prefix: str, separator: str, job: JobDescriptor
) -> None:
    """For any valid prefix, separator, and job descriptor, calling transform_get
    with a correctly prefixed name ("{prefix}{separator}{job.name}") returns
    a descriptor with the prefixed name applied.

    This validates the "round-trip" aspect: names produced by transform_list
    are recognizable by transform_get.

    **Validates: Requirements 9.2, 9.3, 9.4**
    """
    transform = NamespaceTransform(prefix=prefix, separator=separator)
    # The published (canonical) prefix is what a caller sees from transform_list
    # and therefore what it looks the job back up by.
    full_prefix = f"{normalize_name(prefix)}{separator}"
    prefixed_name = f"{full_prefix}{job.name}"

    result = transform.transform_get(prefixed_name, job)

    assert result is not None, (
        f"transform_get returned None for validly-prefixed name '{prefixed_name}' "
        f"with a non-None job descriptor"
    )

    # The result should have the prefixed name
    assert result.name == f"{full_prefix}{job.name}", (
        f"Expected result name '{full_prefix}{job.name}', got '{result.name}'"
    )

    # All other fields must be preserved
    assert result.group == job.group
    assert result.module_path == job.module_path
    assert result.source_file == job.source_file
    assert result.source_mtime == job.source_mtime
    assert result.content_hash == job.content_hash
    assert result.docstring == job.docstring
    assert result.config_fields == job.config_fields
    assert result.dependencies == job.dependencies
    assert result.declaration == job.declaration
