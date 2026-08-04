"""Property-based tests for GroupFilterTransform (Property 4).

Tests that GroupFilterTransform correctly filters job descriptors based on
include/exclude group sets, following the semantics:
- include_groups: only jobs with group IN include_groups pass through
- exclude_groups: jobs with group IN exclude_groups are removed
- Both set: include first, then exclude
- None-group: excluded by include_groups, included by exclude_groups-only

**Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._discovery.transforms import GroupFilterTransform
from functualize._types.descriptors import FieldDescriptor, JobDescriptor
from functualize._types.job_declaration import JobDeclaration

# --- Strategies (reused from test_transform_identity_property.py) ---

# Generate valid job names (non-empty identifiers)
job_names = st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True).filter(
    lambda s: s.isidentifier()
)

# Generate group name strings (non-None groups for explicit group values)
group_names = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)

# Generate optional group strings (either None or a group name)
groups = st.one_of(st.none(), group_names)

# Generate FieldDescriptor instances
field_descriptors = st.builds(
    FieldDescriptor,
    name=st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True),
    type_annotation=st.sampled_from(
        ["str", "int", "bool", "float", "enum", "list[str]"]
    ),
    choices=st.one_of(
        st.none(),
        st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=5),
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

# Strategy for include/exclude group sets
group_sets = st.one_of(
    st.none(),
    st.frozensets(group_names, min_size=1, max_size=5).map(set),
)


# --- Property 4: GroupFilterTransform correctness ---


@settings(max_examples=100)
@given(jobs=job_descriptor_lists, include_groups=group_sets)
def test_property_4_include_groups_only(
    jobs: list[JobDescriptor], include_groups: set[str] | None
) -> None:
    """When include_groups is set, only jobs with group IN include_groups pass through.
    Jobs with group=None are excluded since None is not in any include set.

    **Validates: Requirements 10.1, 10.2, 10.5**
    """
    transform = GroupFilterTransform(include_groups=include_groups)
    result = transform.transform_list(jobs)

    if include_groups is None:
        # No include filter → all jobs pass through
        assert list(result) == list(jobs), (
            "With include_groups=None, all jobs should pass through unchanged"
        )
    else:
        # Only jobs whose group is in include_groups should remain
        for job in result:
            assert job.group in include_groups, (
                f"Job with group={job.group!r} passed through include filter "
                f"but is not in include_groups={include_groups}"
            )
        # All jobs from input that have matching groups should be present
        expected = [j for j in jobs if j.group in include_groups]
        assert list(result) == expected, (
            "Include filter did not produce the expected subset"
        )


@settings(max_examples=100)
@given(jobs=job_descriptor_lists, exclude_groups=group_sets)
def test_property_4_exclude_groups_only(
    jobs: list[JobDescriptor], exclude_groups: set[str] | None
) -> None:
    """When exclude_groups is set, jobs with group IN exclude_groups are removed.
    Jobs with group=None are NOT excluded (None is not in any exclude set).

    **Validates: Requirements 10.1, 10.3, 10.5**
    """
    transform = GroupFilterTransform(exclude_groups=exclude_groups)
    result = transform.transform_list(jobs)

    if exclude_groups is None:
        # No exclude filter → all jobs pass through
        assert list(result) == list(jobs), (
            "With exclude_groups=None, all jobs should pass through unchanged"
        )
    else:
        # No job in result should have a group in exclude_groups
        for job in result:
            assert job.group not in exclude_groups, (
                f"Job with group={job.group!r} was not removed by exclude filter "
                f"exclude_groups={exclude_groups}"
            )
        # All jobs from input that are NOT excluded should be present
        expected = [j for j in jobs if j.group not in exclude_groups]
        assert list(result) == expected, (
            "Exclude filter did not produce the expected result"
        )


@settings(max_examples=100)
@given(
    jobs=job_descriptor_lists,
    include_groups=st.frozensets(group_names, min_size=1, max_size=5).map(set),
    exclude_groups=st.frozensets(group_names, min_size=1, max_size=5).map(set),
)
def test_property_4_include_then_exclude(
    jobs: list[JobDescriptor],
    include_groups: set[str],
    exclude_groups: set[str],
) -> None:
    """When both include_groups and exclude_groups are set, include is applied
    first, then exclude from the result.

    **Validates: Requirements 10.4**
    """
    transform = GroupFilterTransform(
        include_groups=include_groups, exclude_groups=exclude_groups
    )
    result = transform.transform_list(jobs)

    # Manually compute expected: include first, then exclude
    after_include = [j for j in jobs if j.group in include_groups]
    expected = [j for j in after_include if j.group not in exclude_groups]

    assert list(result) == expected, (
        f"Include-then-exclude did not match expected. "
        f"include={include_groups}, exclude={exclude_groups}"
    )


@settings(max_examples=100)
@given(
    jobs=job_descriptor_lists,
    include_groups=group_sets,
    exclude_groups=group_sets,
)
def test_property_4_transform_get_consistent_with_list(
    jobs: list[JobDescriptor],
    include_groups: set[str] | None,
    exclude_groups: set[str] | None,
) -> None:
    """transform_get should be consistent with transform_list: a job passes
    transform_get iff it would be present in transform_list output.

    **Validates: Requirements 10.2, 10.3, 10.4, 10.5**
    """
    transform = GroupFilterTransform(
        include_groups=include_groups, exclude_groups=exclude_groups
    )
    list_result = transform.transform_list(jobs)
    list_result_set = set(id(j) for j in list_result)

    for job in jobs:
        get_result = transform.transform_get(job.name, job)
        in_list = id(job) in list_result_set

        if in_list:
            assert get_result is job, (
                f"Job {job.name!r} (group={job.group!r}) is in transform_list output "
                f"but transform_get returned None"
            )
        else:
            assert get_result is None, (
                f"Job {job.name!r} (group={job.group!r}) is NOT in transform_list "
                f"output but transform_get returned it"
            )


@settings(max_examples=100)
@given(
    include_groups=group_sets,
    exclude_groups=group_sets,
)
def test_property_4_transform_get_none_passthrough(
    include_groups: set[str] | None,
    exclude_groups: set[str] | None,
) -> None:
    """transform_get with job=None always returns None regardless of filter config.

    **Validates: Requirements 10.2, 10.3**
    """
    transform = GroupFilterTransform(
        include_groups=include_groups, exclude_groups=exclude_groups
    )
    result = transform.transform_get("any_name", None)
    assert result is None, "transform_get should return None when job=None"
