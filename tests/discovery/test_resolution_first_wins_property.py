"""Property-based test for Resolution pipeline get_job first-wins (Property 8).

Tests that when multiple providers have a job with the same name,
resolve_one(name) returns the result from the FIRST registered provider
(by registration order) that returns non-None from get_job.

**Validates: Requirements 5.2, 5.3**
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from hypothesis import given
from hypothesis import strategies as st

from functualize._discovery.pipeline import ResolutionPipeline
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

# This property is about *which provider answers first*, so only two fields
# carry information: `name` (what is looked up) and `module_path` (the
# discriminator the assertions use to tell whose descriptor came back). The
# remaining fields are copied through untouched by the pipeline, so generating
# them buys no coverage and costs a great deal — the original strategy drew six
# `from_regex` values per descriptor, including a 64-character hash, which was
# slow enough that Hypothesis aborted the test with FailedHealthCheck before it
# could generate a usable input.

_identifier_chars = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=0, max_size=8
)

# Valid job names: simple identifiers
job_names = st.tuples(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz"), _identifier_chars
).map("".join)

# Module paths — the discriminator, so it stays generated
module_paths = st.lists(job_names, min_size=1, max_size=3).map(".".join)


@st.composite
def job_descriptors(draw: st.DrawFn) -> JobDescriptor:
    """Strategy to generate a JobDescriptor varying only name and module_path."""
    return JobDescriptor(
        name=draw(job_names),
        group=None,
        module_path=draw(module_paths),
        source_file="/test/module.py",
        source_mtime=0.0,
        content_hash="0" * 64,
        docstring=None,
        config_fields=[],
        dependencies={},
        metadata=None,
    )


@st.composite
def unique_descriptor_lists(
    draw: st.DrawFn,
    min_size: int = 0,
    max_size: int = 5,
) -> list[JobDescriptor]:
    """Strategy to generate a list of JobDescriptors with unique names."""
    names = draw(st.lists(job_names, min_size=min_size, max_size=max_size, unique=True))
    descriptors = []
    for name in names:
        desc = draw(job_descriptors())
        descriptors.append(replace(desc, name=name))
    return descriptors


@st.composite
def overlapping_providers_scenario(
    draw: st.DrawFn,
) -> tuple[list[list[JobDescriptor]], str]:
    """Generate multiple providers with at least one overlapping name.

    Returns a tuple of (list of descriptor lists per provider, the overlapping name).
    At least 2 providers will contain the overlapping name.
    """
    # Generate 2-4 providers
    num_providers = draw(st.integers(min_value=2, max_value=4))

    # Pick a shared name that will appear in multiple providers
    shared_name = draw(job_names)

    # Generate distinct descriptor lists for each provider, each containing the shared name
    provider_descriptors: list[list[JobDescriptor]] = []

    for i in range(num_providers):
        # Generate unique names for this provider (excluding the shared name)
        unique_names = draw(
            st.lists(job_names, min_size=0, max_size=3, unique=True).filter(
                lambda names: shared_name not in names
            )
        )

        # Create descriptors with unique names
        descs: list[JobDescriptor] = []
        for name in unique_names:
            desc = draw(job_descriptors())
            descs.append(replace(desc, name=name))

        # Add the shared name descriptor with a unique module_path to distinguish
        # which provider it came from
        shared_desc = draw(job_descriptors())
        shared_desc = replace(
            shared_desc,
            name=shared_name,
            module_path=f"provider_{i}.module",
        )
        descs.append(shared_desc)

        provider_descriptors.append(descs)

    return provider_descriptors, shared_name


# --- Property 8: Resolution pipeline get_job first-wins ---


@given(data=overlapping_providers_scenario())
def test_property_8_resolve_one_returns_first_provider_result(
    data: tuple[list[list[JobDescriptor]], str],
) -> None:
    """When multiple providers have a job with the same name,
    resolve_one(name) returns the result from the FIRST registered provider
    (by registration order) that returns non-None from get_job.

    **Validates: Requirements 5.2, 5.3**
    """
    provider_descriptors, shared_name = data

    pipeline = ResolutionPipeline()

    # Register all providers in order
    for descs in provider_descriptors:
        pipeline.add_provider(DictProvider(descs))

    # Resolve the shared name
    result = pipeline.resolve_one(shared_name)

    # The first provider that has this name should win
    expected_desc = None
    for descs in provider_descriptors:
        for desc in descs:
            if desc.name == shared_name:
                expected_desc = desc
                break
        if expected_desc is not None:
            break

    assert result is not None, (
        f"resolve_one('{shared_name}') returned None but providers have this job"
    )
    assert result == expected_desc, (
        f"resolve_one('{shared_name}') returned descriptor from wrong provider. "
        f"Expected module_path='{expected_desc.module_path}', "
        f"got module_path='{result.module_path}'"
    )


@given(data=overlapping_providers_scenario())
def test_property_8_first_wins_ignores_later_providers(
    data: tuple[list[list[JobDescriptor]], str],
) -> None:
    """When the first provider returns non-None for a name, later providers
    are not consulted (the result comes from the first provider only).

    This validates that even if later providers have a different descriptor
    for the same name, the first provider's result is used.

    **Validates: Requirements 5.2, 5.3**
    """
    provider_descriptors, shared_name = data

    pipeline = ResolutionPipeline()

    # Register all providers in order
    for descs in provider_descriptors:
        pipeline.add_provider(DictProvider(descs))

    result = pipeline.resolve_one(shared_name)

    # Verify result matches only the first provider's version
    first_provider_desc = None
    for desc in provider_descriptors[0]:
        if desc.name == shared_name:
            first_provider_desc = desc
            break

    assert first_provider_desc is not None, (
        "First provider should contain the shared name"
    )
    assert result is not None, (
        f"resolve_one('{shared_name}') returned None unexpectedly"
    )
    assert result.module_path == first_provider_desc.module_path, (
        f"Result came from wrong provider: "
        f"expected module_path='{first_provider_desc.module_path}', "
        f"got module_path='{result.module_path}'"
    )


@given(
    provider_descs=st.lists(
        unique_descriptor_lists(min_size=1, max_size=4),
        min_size=2,
        max_size=4,
    )
)
def test_property_8_resolve_one_none_when_no_provider_has_name(
    provider_descs: list[list[JobDescriptor]],
) -> None:
    """When no provider has a job with the given name, resolve_one returns None.

    **Validates: Requirements 5.2, 5.3**
    """
    pipeline = ResolutionPipeline()

    # Collect all names that exist in any provider
    all_names: set[str] = set()
    for descs in provider_descs:
        pipeline.add_provider(DictProvider(descs))
        for desc in descs:
            all_names.add(desc.name)

    # Use a name guaranteed not to exist
    absent_name = "zzzz_absent_name_not_in_providers"
    if absent_name not in all_names:
        result = pipeline.resolve_one(absent_name)
        assert result is None, (
            f"resolve_one('{absent_name}') should return None for absent name, "
            f"but got: {result}"
        )


@given(data=overlapping_providers_scenario())
def test_property_8_first_non_none_wins_skipping_none_providers(
    data: tuple[list[list[JobDescriptor]], str],
) -> None:
    """When some early providers don't have the name (return None) but a later
    provider does, resolve_one returns from the first provider that returns
    non-None.

    **Validates: Requirements 5.2, 5.3**
    """
    provider_descriptors, shared_name = data

    # Create a scenario where the first provider does NOT have the shared name
    # but later providers do.
    # Remove shared_name from the first provider
    first_without_shared = [d for d in provider_descriptors[0] if d.name != shared_name]

    pipeline = ResolutionPipeline()

    # Register first provider WITHOUT the shared name
    pipeline.add_provider(DictProvider(first_without_shared))

    # Register remaining providers (which still have the shared name)
    for descs in provider_descriptors[1:]:
        pipeline.add_provider(DictProvider(descs))

    result = pipeline.resolve_one(shared_name)

    # The first provider with the name (index 1 from original) should win
    expected_desc = None
    for descs in provider_descriptors[1:]:
        for desc in descs:
            if desc.name == shared_name:
                expected_desc = desc
                break
        if expected_desc is not None:
            break

    assert result is not None, (
        f"resolve_one('{shared_name}') returned None but later providers have it"
    )
    assert result == expected_desc, (
        f"resolve_one('{shared_name}') should return from first non-None provider. "
        f"Expected module_path='{expected_desc.module_path}', "
        f"got module_path='{result.module_path}'"
    )
