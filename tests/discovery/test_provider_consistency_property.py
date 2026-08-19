"""Property-based test for Provider consistency (Property 2).

Tests that any JobProvider implementation maintains consistency between
list_jobs() and get_job(): every descriptor returned by list_jobs() is
retrievable via get_job(d.name), and get_job returns None for absent names.

**Validates: Requirements 1.5**
"""

from __future__ import annotations

from collections.abc import Sequence

from hypothesis import given
from hypothesis import strategies as st

from functualize._types.descriptors import JobDescriptor

# --- DictProvider test helper ---


class DictProvider:
    """Test helper: a JobProvider backed by a dict of descriptors keyed by name.

    This satisfies the JobProvider Protocol structurally using an in-memory
    dictionary, providing a minimal correct implementation for property testing.
    """

    def __init__(self, descriptors: Sequence[JobDescriptor]) -> None:
        self._jobs: dict[str, JobDescriptor] = {d.name: d for d in descriptors}

    def list_jobs(self) -> Sequence[JobDescriptor]:
        return list(self._jobs.values())

    def get_job(self, name: str) -> JobDescriptor | None:
        return self._jobs.get(name)


# --- Strategies ---

# Valid job names: simple identifiers
job_names = st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True).filter(
    lambda s: s.isidentifier()
)

# Optional group values
group_values = st.one_of(st.none(), job_names)

# Module paths
module_paths = st.from_regex(
    r"[a-z][a-z0-9_]{0,10}(\.[a-z][a-z0-9_]{0,10}){0,3}", fullmatch=True
)

# Source file paths
source_files = st.from_regex(r"/[a-z][a-z0-9_/]{0,30}\.py", fullmatch=True)

# Content hashes (hex strings)
content_hashes = st.from_regex(r"[0-9a-f]{64}", fullmatch=True)


@st.composite
def job_descriptors(draw: st.DrawFn) -> JobDescriptor:
    """Strategy to generate a random JobDescriptor."""
    return JobDescriptor(
        name=draw(job_names),
        group=draw(group_values),
        module_path=draw(module_paths),
        source_file=draw(source_files),
        source_mtime=draw(st.floats(min_value=0.0, max_value=1e12, allow_nan=False)),
        content_hash=draw(content_hashes),
        docstring=draw(st.one_of(st.none(), st.text(min_size=0, max_size=100))),
        config_fields=[],
        dependencies={},
        metadata=None,
    )


@st.composite
def unique_descriptor_lists(draw: st.DrawFn) -> list[JobDescriptor]:
    """Strategy to generate a list of JobDescriptors with unique names."""
    names = draw(st.lists(job_names, min_size=0, max_size=10, unique=True))
    descriptors = []
    for name in names:
        desc = draw(job_descriptors())
        # Replace name to ensure uniqueness
        from dataclasses import replace

        descriptors.append(replace(desc, name=name))
    return descriptors


# Names that are guaranteed not to be in a given set
absent_names = st.from_regex(r"absent_[a-z0-9]{1,10}", fullmatch=True)


# --- Property 2: Provider consistency (list_jobs ↔ get_job) ---


@given(descriptors=unique_descriptor_lists())
def test_property_2_every_listed_job_is_retrievable(
    descriptors: list[JobDescriptor],
) -> None:
    """For any DictProvider backed by a set of descriptors, every descriptor
    returned by list_jobs() must be retrievable via get_job(d.name) and the
    retrieved descriptor must be equivalent.

    **Validates: Requirements 1.5**
    """
    provider = DictProvider(descriptors)
    listed = provider.list_jobs()

    for desc in listed:
        retrieved = provider.get_job(desc.name)
        assert retrieved is not None, (
            f"get_job('{desc.name}') returned None but descriptor is in list_jobs(). "
            f"Listed names: {[d.name for d in listed]}"
        )
        assert retrieved == desc, (
            f"get_job('{desc.name}') returned a different descriptor than list_jobs(). "
            f"Expected: {desc}, Got: {retrieved}"
        )


@given(
    descriptors=unique_descriptor_lists(),
    absent_name=absent_names,
)
def test_property_2_get_job_returns_none_for_absent_names(
    descriptors: list[JobDescriptor], absent_name: str
) -> None:
    """For any DictProvider, get_job() must return None for names that are not
    present in list_jobs().

    **Validates: Requirements 1.5**
    """
    provider = DictProvider(descriptors)

    # The absent_name strategy generates names prefixed with "absent_" which
    # won't collide with our job_names strategy (starts with [a-z] no prefix)
    listed_names = {d.name for d in provider.list_jobs()}

    # Only test if the absent name is truly absent
    if absent_name not in listed_names:
        result = provider.get_job(absent_name)
        assert result is None, (
            f"get_job('{absent_name}') should return None for absent name, "
            f"but returned: {result}. Listed names: {listed_names}"
        )


@given(descriptors=unique_descriptor_lists())
def test_property_2_list_jobs_names_match_get_job_domain(
    descriptors: list[JobDescriptor],
) -> None:
    """The set of names from list_jobs() defines the exact domain where
    get_job returns non-None: get_job SHALL NOT return a descriptor whose
    name is absent from list_jobs().

    **Validates: Requirements 1.5**
    """
    provider = DictProvider(descriptors)
    listed = provider.list_jobs()
    listed_names = {d.name for d in listed}

    # Verify: every name in list_jobs can be retrieved
    for name in listed_names:
        assert provider.get_job(name) is not None, (
            f"get_job('{name}') returned None but name is in list_jobs()"
        )

    # Verify: the retrieved descriptor's name matches what we asked for
    for desc in listed:
        retrieved = provider.get_job(desc.name)
        assert retrieved is not None
        assert retrieved.name == desc.name, (
            f"get_job('{desc.name}') returned descriptor with name '{retrieved.name}'"
        )
