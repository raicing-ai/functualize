"""Property-based tests for VisibilityTransform correctness (Property 5).

Tests that VisibilityTransform correctly hides jobs by name or tag intersection,
passes through jobs with no metadata or None tags when only hidden_tags is set,
and passes all jobs through when neither set is provided.

**Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5**
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from functualize._discovery.transforms import VisibilityTransform
from functualize._types.descriptors import FieldDescriptor, JobDescriptor
from functualize._types.job_declaration import JobDeclaration

# --- Strategies (reused patterns from test_transform_identity_property.py) ---

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

# Tag values: short alphabetic strings
tag_values = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)

# Generate optional JobDeclaration with controlled tags
declaration_strategy = st.one_of(
    st.none(),
    st.builds(
        JobDeclaration,
        extra_description=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
        category=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
        examples=st.lists(st.text(min_size=1, max_size=20), max_size=3),
        tags=st.lists(tag_values, max_size=5),
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

# Generate lists of JobDescriptors
job_descriptor_lists = st.lists(job_descriptors, min_size=0, max_size=10)

# Generate sets of hidden names (drawn from valid job name space)
hidden_name_sets = st.frozensets(job_names, min_size=0, max_size=5)

# Generate sets of hidden tags (drawn from tag value space)
hidden_tag_sets = st.frozensets(tag_values, min_size=0, max_size=5)


# --- Helper ---


def _is_hidden(
    job: JobDescriptor, hidden_names: set[str], hidden_tags: set[str]
) -> bool:
    """Reference implementation: determine if a job should be hidden."""
    if job.name in hidden_names:
        return True
    return bool(
        hidden_tags
        and job.declaration is not None
        and job.declaration.tags
        and set(job.declaration.tags) & hidden_tags
    )


# --- Property 5: VisibilityTransform correctness ---


@given(
    jobs=job_descriptor_lists,
    hidden_names=hidden_name_sets,
    hidden_tags=hidden_tag_sets,
)
def test_property_5_visibility_excludes_hidden_names_and_tags(
    jobs: list[JobDescriptor],
    hidden_names: frozenset[str],
    hidden_tags: frozenset[str],
) -> None:
    """VisibilityTransform excludes exactly those jobs matching hidden_names
    OR having tags intersecting hidden_tags.

    For any list of descriptors and any hidden_names/hidden_tags sets,
    the transform output contains exactly the jobs that are NOT hidden.

    **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5**
    """
    transform = VisibilityTransform(
        hidden_names=set(hidden_names), hidden_tags=set(hidden_tags)
    )
    result = list(transform.transform_list(jobs))

    # Compute expected: jobs NOT hidden by our reference implementation
    expected = [
        j for j in jobs if not _is_hidden(j, set(hidden_names), set(hidden_tags))
    ]

    assert len(result) == len(expected), (
        f"Length mismatch: got {len(result)}, expected {len(expected)}. "
        f"hidden_names={hidden_names}, hidden_tags={hidden_tags}"
    )

    for i, (actual, exp) in enumerate(zip(result, expected, strict=False)):
        assert actual is exp, (
            f"Mismatch at index {i}: expected job name={exp.name}, got name={actual.name}"
        )


@given(
    jobs=job_descriptor_lists,
    hidden_names=hidden_name_sets,
    hidden_tags=hidden_tag_sets,
)
def test_property_5_visibility_no_metadata_not_excluded_by_tags(
    jobs: list[JobDescriptor],
    hidden_names: frozenset[str],
    hidden_tags: frozenset[str],
) -> None:
    """Jobs with no metadata or None tags are NOT excluded by hidden_tags.

    Only hidden_names can exclude jobs that lack metadata/tags.

    **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5**
    """
    transform = VisibilityTransform(
        hidden_names=set(hidden_names), hidden_tags=set(hidden_tags)
    )
    result = list(transform.transform_list(jobs))

    for job in jobs:
        has_no_tags = job.declaration is None or not job.declaration.tags
        name_not_hidden = job.name not in hidden_names

        if has_no_tags and name_not_hidden:
            # This job MUST appear in the result
            assert job in result, (
                f"Job '{job.name}' with no metadata/tags was incorrectly excluded. "
                f"hidden_names={hidden_names}, hidden_tags={hidden_tags}"
            )


@given(jobs=job_descriptor_lists)
def test_property_5_visibility_empty_sets_passthrough(
    jobs: list[JobDescriptor],
) -> None:
    """When neither hidden_names nor hidden_tags is provided (both empty),
    all jobs pass through unchanged.

    **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5**
    """
    # Test with explicit empty sets
    transform = VisibilityTransform(hidden_names=set(), hidden_tags=set())
    result = transform.transform_list(jobs)

    assert len(result) == len(jobs), (
        f"Empty hidden sets changed list length: input={len(jobs)}, output={len(result)}"
    )
    for i, (original, transformed) in enumerate(zip(jobs, result, strict=False)):
        assert transformed is original, (
            f"Empty hidden sets modified job at index {i}: "
            f"original name={original.name}, result name={transformed.name}"
        )


@given(jobs=job_descriptor_lists)
def test_property_5_visibility_none_sets_passthrough(
    jobs: list[JobDescriptor],
) -> None:
    """When hidden_names and hidden_tags are both None, all jobs pass through.

    **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5**
    """
    transform = VisibilityTransform(hidden_names=None, hidden_tags=None)
    result = transform.transform_list(jobs)

    assert len(result) == len(jobs), (
        f"None hidden sets changed list length: input={len(jobs)}, output={len(result)}"
    )
    for i, (original, transformed) in enumerate(zip(jobs, result, strict=False)):
        assert transformed is original, (
            f"None hidden sets modified job at index {i}: "
            f"original name={original.name}, result name={transformed.name}"
        )


@given(
    job=job_descriptors,
    hidden_names=hidden_name_sets,
    hidden_tags=hidden_tag_sets,
)
def test_property_5_visibility_transform_get_consistency(
    job: JobDescriptor,
    hidden_names: frozenset[str],
    hidden_tags: frozenset[str],
) -> None:
    """transform_get returns None for hidden jobs and the job itself for visible ones.

    This must be consistent with transform_list behavior.

    **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5**
    """
    transform = VisibilityTransform(
        hidden_names=set(hidden_names), hidden_tags=set(hidden_tags)
    )

    result = transform.transform_get(job.name, job)
    should_be_hidden = _is_hidden(job, set(hidden_names), set(hidden_tags))

    if should_be_hidden:
        assert result is None, (
            f"transform_get should return None for hidden job '{job.name}'. "
            f"hidden_names={hidden_names}, hidden_tags={hidden_tags}, "
            f"job tags={job.declaration.tags if job.declaration else None}"
        )
    else:
        assert result is job, (
            f"transform_get should return the job for visible job '{job.name}'. "
            f"hidden_names={hidden_names}, hidden_tags={hidden_tags}"
        )


@given(
    hidden_names=hidden_name_sets,
    hidden_tags=hidden_tag_sets,
)
def test_property_5_visibility_transform_get_none_passthrough(
    hidden_names: frozenset[str],
    hidden_tags: frozenset[str],
) -> None:
    """transform_get with job=None always returns None regardless of hidden sets.

    **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5**
    """
    transform = VisibilityTransform(
        hidden_names=set(hidden_names), hidden_tags=set(hidden_tags)
    )

    result = transform.transform_get("any_name", None)
    assert result is None, "transform_get should return None when job is None"
