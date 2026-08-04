"""Property-based tests for JobTransform identity pass-through (Property 1).

Tests that the default JobTransform (no subclass override) acts as a pure identity
transform: transform_list returns the same descriptors in the same order, and
transform_get returns the same descriptor it receives.

**Validates: Requirements 2.3, 2.5, 2.6**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._discovery.transforms import IdentityTransform
from functualize._types.descriptors import FieldDescriptor, JobDescriptor
from functualize._types.job_declaration import JobDeclaration

# --- Strategies ---

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


# --- Property 1: Transform identity pass-through ---


@settings(max_examples=100)
@given(jobs=job_descriptor_lists)
def test_property_1_transform_list_identity(jobs: list[JobDescriptor]) -> None:
    """For any list of JobDescriptors, applying the default JobTransform's
    transform_list returns the same descriptors in the same order.

    The identity transform must not add, remove, reorder, or modify any
    descriptor in the input sequence.

    **Validates: Requirements 2.3, 2.5, 2.6**
    """
    transform = IdentityTransform()
    result = transform.transform_list(jobs)

    # Same length
    assert len(result) == len(jobs), (
        f"Identity transform changed list length: input={len(jobs)}, output={len(result)}"
    )

    # Same elements in same order (identity — same objects)
    for i, (original, transformed) in enumerate(zip(jobs, result, strict=False)):
        assert transformed is original, (
            f"Identity transform at index {i}: expected same object identity. "
            f"Original name={original.name}, transformed name={transformed.name}"
        )


@settings(max_examples=100)
@given(name=job_names, job=st.one_of(st.none(), job_descriptors))
def test_property_1_transform_get_identity(
    name: str, job: JobDescriptor | None
) -> None:
    """For any name and descriptor (or None), applying the default JobTransform's
    transform_get returns the exact same descriptor (or None) it received.

    The identity transform must pass through both present and absent jobs unchanged.

    **Validates: Requirements 2.3, 2.5, 2.6**
    """
    transform = IdentityTransform()
    result = transform.transform_get(name, job)

    # Same object identity (or both None)
    assert result is job, (
        f"Identity transform_get did not pass through unchanged. "
        f"name={name!r}, input={job}, output={result}"
    )
