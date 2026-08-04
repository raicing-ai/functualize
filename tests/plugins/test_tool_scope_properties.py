"""Property-based tests for ToolScope filtering.

Tests Properties 10–14 from the Phase 2–5 Domain SDKs design document.

Property 10: ToolScope.only filters to listed names — For any set of job names,
ToolScope.only(names) returns exactly those names that exist in the registry.

Property 11: ToolScope.tagged filters to matching jobs — For any set of tags,
ToolScope.tagged(*tags) returns only jobs that have ALL of those tags.

Property 12: ToolScope.group filters to group members — For any group name,
ToolScope.group(name) returns exactly the jobs in that group.

Property 13: ToolScope union is additive — For any two ToolScopes A and B,
(A + B).to_tool_defs() is a superset of both A.to_tool_defs() and B.to_tool_defs().

Property 14: ToolScope.to_tool_defs returns provider-agnostic ToolDefs — For any
ToolScope resolution, all returned items are ToolDef instances with non-empty name
and description fields.

**Validates: Requirements 6.1, 6.2, 6.3, 6.5, 6.8**
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from functualize_ai import ToolDef, ToolScope
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# ===========================================================================
# Strategies
# ===========================================================================

# Valid job name characters (letters and underscore)
job_names_st = st.text(
    alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_"),
    min_size=1,
    max_size=30,
)

# Available tags pool
available_tags = [
    "safe",
    "production",
    "destructive",
    "internal",
    "fast",
    "slow",
    "ai",
    "ops",
    "dev",
]

# Strategy for a set of tags assigned to a job
job_tags_st = st.lists(
    st.sampled_from(available_tags),
    min_size=0,
    max_size=4,
    unique=True,
)

# Available group names
available_groups = ["ops", "dev", "ai", "tasks", "infra", "data", None]

group_names_st = st.sampled_from(available_groups)

# Strategy for a non-empty docstring
docstring_st = st.text(min_size=1, max_size=100)


# ===========================================================================
# Helpers
# ===========================================================================


def _make_descriptor(
    name: str,
    group: str | None = None,
    docstring: str = "A job.",
    tags: list[str] | None = None,
) -> SimpleNamespace:
    """Create a mock job descriptor for testing."""
    metadata = SimpleNamespace(tags=tags if tags is not None else [])
    return SimpleNamespace(
        name=name,
        group=group,
        docstring=docstring,
        metadata=metadata,
        config_fields=[],
        parameters=[],
    )


class MockRegistry:
    """A mock job registry for testing ToolScope resolution."""

    def __init__(self, descriptors: list[Any]) -> None:
        self._descriptors = descriptors

    def get_descriptors(self) -> list[Any]:
        return self._descriptors


@st.composite
def job_registries(draw: st.DrawFn) -> tuple[MockRegistry, list[SimpleNamespace]]:
    """Generate a random job registry with random names, tags, and groups."""
    num_jobs = draw(st.integers(min_value=1, max_value=15))
    names = draw(
        st.lists(job_names_st, min_size=num_jobs, max_size=num_jobs, unique=True)
    )
    descriptors = []
    for name in names:
        tags = draw(job_tags_st)
        group = draw(group_names_st)
        docstring = draw(docstring_st)
        descriptors.append(
            _make_descriptor(name=name, group=group, docstring=docstring, tags=tags)
        )
    return MockRegistry(descriptors), descriptors


# ===========================================================================
# Property 10: ToolScope.only filters to listed names
# ===========================================================================


class TestToolScopeOnlyProperty:
    """Property 10: ToolScope.only filters to listed names.

    For any set of job names, ToolScope.only(names) returns exactly those names
    that exist in the registry (no more, no less).

    **Validates: Requirements 6.1**
    """

    @given(data=st.data())
    @settings(max_examples=100)
    def test_only_returns_exactly_existing_names(self, data: st.DataObject) -> None:
        """ToolScope.only(S) returns ToolDefs whose names are exactly S ∩ registry_names.

        **Validates: Requirements 6.1**
        """
        registry, descriptors = data.draw(job_registries())
        all_names = [d.name for d in descriptors]

        # Draw a subset of existing names plus some that may not exist
        subset = data.draw(
            st.lists(
                st.one_of(
                    st.sampled_from(all_names),
                    job_names_st,  # may or may not exist in registry
                ),
                min_size=0,
                max_size=10,
                unique=True,
            )
        )

        scope = ToolScope.only(subset)
        defs = scope.to_tool_defs(registry)

        result_names = {d.name for d in defs}
        expected_names = set(subset) & set(all_names)

        assert result_names == expected_names

    @given(data=st.data())
    @settings(max_examples=100)
    def test_only_with_exact_subset_returns_all(self, data: st.DataObject) -> None:
        """When all names in the subset exist in registry, all are returned.

        **Validates: Requirements 6.1**
        """
        registry, descriptors = data.draw(job_registries())
        all_names = [d.name for d in descriptors]

        # Pick a random subset of existing names only
        subset = data.draw(
            st.lists(
                st.sampled_from(all_names),
                min_size=0,
                max_size=min(len(all_names), 8),
                unique=True,
            )
        )

        scope = ToolScope.only(subset)
        defs = scope.to_tool_defs(registry)

        result_names = {d.name for d in defs}
        assert result_names == set(subset)


# ===========================================================================
# Property 11: ToolScope.tagged filters to matching jobs
# ===========================================================================


class TestToolScopeTaggedProperty:
    """Property 11: ToolScope.tagged filters to matching jobs.

    For any set of tags T, ToolScope.tagged(*T) returns only jobs that have
    ALL tags in T in their @job.

    **Validates: Requirements 6.2**
    """

    @given(data=st.data())
    @settings(max_examples=100)
    def test_tagged_returns_only_jobs_with_all_tags(self, data: st.DataObject) -> None:
        """ToolScope.tagged(*T) returns ToolDefs only for jobs with ALL tags in T.

        **Validates: Requirements 6.2**
        """
        registry, descriptors = data.draw(job_registries())

        # Draw a non-empty set of tags to filter by
        filter_tags = data.draw(
            st.lists(
                st.sampled_from(available_tags),
                min_size=1,
                max_size=3,
                unique=True,
            )
        )

        scope = ToolScope.tagged(*filter_tags)
        defs = scope.to_tool_defs(registry)

        result_names = {d.name for d in defs}

        # Compute expected: jobs that have ALL filter_tags
        required_tags = set(filter_tags)
        expected_names = {
            d.name for d in descriptors if required_tags.issubset(set(d.metadata.tags))
        }

        assert result_names == expected_names

    @given(data=st.data())
    @settings(max_examples=100)
    def test_tagged_every_result_has_all_required_tags(
        self, data: st.DataObject
    ) -> None:
        """Every returned job has ALL of the requested tags.

        **Validates: Requirements 6.2**
        """
        registry, descriptors = data.draw(job_registries())

        filter_tags = data.draw(
            st.lists(
                st.sampled_from(available_tags),
                min_size=1,
                max_size=3,
                unique=True,
            )
        )

        scope = ToolScope.tagged(*filter_tags)
        defs = scope.to_tool_defs(registry)

        required_tags = set(filter_tags)
        for tool_def in defs:
            # Find the descriptor for this tool
            desc = next(d for d in descriptors if d.name == tool_def.name)
            assert required_tags.issubset(set(desc.metadata.tags))


# ===========================================================================
# Property 12: ToolScope.group filters to group members
# ===========================================================================


class TestToolScopeGroupProperty:
    """Property 12: ToolScope.group filters to group members.

    For any group name G, ToolScope.group(G) returns ToolDefs only for jobs in group G.

    **Validates: Requirements 6.3**
    """

    @given(data=st.data())
    @settings(max_examples=100)
    def test_group_returns_exactly_matching_jobs(self, data: st.DataObject) -> None:
        """ToolScope.group(G) returns exactly the jobs in that group.

        **Validates: Requirements 6.3**
        """
        registry, descriptors = data.draw(job_registries())

        # Pick a group name (could be one that exists or not)
        group_name = data.draw(
            st.sampled_from(
                ["ops", "dev", "ai", "tasks", "infra", "data", "nonexistent"]
            )
        )

        scope = ToolScope.group(group_name)
        defs = scope.to_tool_defs(registry)

        result_names = {d.name for d in defs}
        expected_names = {d.name for d in descriptors if d.group == group_name}

        assert result_names == expected_names

    @given(data=st.data())
    @settings(max_examples=100)
    def test_group_every_result_belongs_to_group(self, data: st.DataObject) -> None:
        """Every returned job belongs to the specified group.

        **Validates: Requirements 6.3**
        """
        registry, descriptors = data.draw(job_registries())

        group_name = data.draw(
            st.sampled_from(["ops", "dev", "ai", "tasks", "infra", "data"])
        )

        scope = ToolScope.group(group_name)
        defs = scope.to_tool_defs(registry)

        for tool_def in defs:
            desc = next(d for d in descriptors if d.name == tool_def.name)
            assert desc.group == group_name


# ===========================================================================
# Property 13: ToolScope union is additive
# ===========================================================================


class TestToolScopeUnionProperty:
    """Property 13: ToolScope union is additive.

    For any two ToolScopes A and B, (A + B).to_tool_defs() is a superset of
    both A.to_tool_defs() and B.to_tool_defs().

    **Validates: Requirements 6.5**
    """

    @given(data=st.data())
    @settings(max_examples=100)
    def test_union_is_superset_of_both(self, data: st.DataObject) -> None:
        """(A + B).to_tool_defs() contains all names from A and all from B.

        **Validates: Requirements 6.5**
        """
        registry, descriptors = data.draw(job_registries())
        all_names = [d.name for d in descriptors]

        # Build two ToolScopes from different subsets
        subset_a = data.draw(
            st.lists(
                st.sampled_from(all_names),
                min_size=0,
                max_size=min(len(all_names), 5),
                unique=True,
            )
        )
        subset_b = data.draw(
            st.lists(
                st.sampled_from(all_names),
                min_size=0,
                max_size=min(len(all_names), 5),
                unique=True,
            )
        )

        scope_a = ToolScope.only(subset_a)
        scope_b = ToolScope.only(subset_b)
        combined = scope_a + scope_b

        defs_a = scope_a.to_tool_defs(registry)
        defs_b = scope_b.to_tool_defs(registry)
        defs_combined = combined.to_tool_defs(registry)

        names_a = {d.name for d in defs_a}
        names_b = {d.name for d in defs_b}
        names_combined = {d.name for d in defs_combined}

        # Union should be superset of both
        assert names_a.issubset(names_combined)
        assert names_b.issubset(names_combined)

    @given(data=st.data())
    @settings(max_examples=100)
    def test_union_mixed_scopes_is_superset(self, data: st.DataObject) -> None:
        """Union of different scope types (only + tagged) is superset of both.

        **Validates: Requirements 6.5**
        """
        registry, descriptors = data.draw(job_registries())
        all_names = [d.name for d in descriptors]
        assume(len(all_names) >= 1)

        # Scope A: only some names
        subset_a = data.draw(
            st.lists(
                st.sampled_from(all_names),
                min_size=1,
                max_size=min(len(all_names), 4),
                unique=True,
            )
        )
        # Scope B: tagged
        filter_tags = data.draw(
            st.lists(
                st.sampled_from(available_tags),
                min_size=1,
                max_size=2,
                unique=True,
            )
        )

        scope_a = ToolScope.only(subset_a)
        scope_b = ToolScope.tagged(*filter_tags)
        combined = scope_a + scope_b

        defs_a = scope_a.to_tool_defs(registry)
        defs_b = scope_b.to_tool_defs(registry)
        defs_combined = combined.to_tool_defs(registry)

        names_a = {d.name for d in defs_a}
        names_b = {d.name for d in defs_b}
        names_combined = {d.name for d in defs_combined}

        assert names_a.issubset(names_combined)
        assert names_b.issubset(names_combined)

    @given(data=st.data())
    @settings(max_examples=100)
    def test_union_has_no_duplicate_names(self, data: st.DataObject) -> None:
        """Union deduplicates by name — no duplicate tool names in result.

        **Validates: Requirements 6.5**
        """
        registry, descriptors = data.draw(job_registries())
        all_names = [d.name for d in descriptors]

        # Intentionally overlap names
        subset_a = data.draw(
            st.lists(
                st.sampled_from(all_names),
                min_size=0,
                max_size=min(len(all_names), 5),
                unique=True,
            )
        )
        subset_b = data.draw(
            st.lists(
                st.sampled_from(all_names),
                min_size=0,
                max_size=min(len(all_names), 5),
                unique=True,
            )
        )

        scope_a = ToolScope.only(subset_a)
        scope_b = ToolScope.only(subset_b)
        combined = scope_a + scope_b

        defs_combined = combined.to_tool_defs(registry)
        names = [d.name for d in defs_combined]

        # No duplicates
        assert len(names) == len(set(names))


# ===========================================================================
# Property 14: ToolScope.to_tool_defs returns provider-agnostic ToolDefs
# ===========================================================================


class TestToolScopeToolDefsProperty:
    """Property 14: ToolScope.to_tool_defs returns provider-agnostic ToolDefs.

    For any ToolScope configuration and any job registry, to_tool_defs() SHALL
    return a list[ToolDef] where each entry has name: str, description: str,
    and parameters_schema: dict — with no references to any implementation-specific types.

    **Validates: Requirements 6.8**
    """

    @given(data=st.data())
    @settings(max_examples=100)
    def test_all_results_are_tooldef_instances(self, data: st.DataObject) -> None:
        """Every item returned by to_tool_defs() is a ToolDef instance.

        **Validates: Requirements 6.8**
        """
        registry, descriptors = data.draw(job_registries())
        all_names = [d.name for d in descriptors]

        subset = data.draw(
            st.lists(
                st.sampled_from(all_names),
                min_size=1,
                max_size=min(len(all_names), 8),
                unique=True,
            )
        )

        scope = ToolScope.only(subset)
        defs = scope.to_tool_defs(registry)

        for tool_def in defs:
            assert isinstance(tool_def, ToolDef)

    @given(data=st.data())
    @settings(max_examples=100)
    def test_all_results_have_non_empty_name(self, data: st.DataObject) -> None:
        """Every ToolDef has a non-empty name field.

        **Validates: Requirements 6.8**
        """
        registry, descriptors = data.draw(job_registries())
        all_names = [d.name for d in descriptors]

        subset = data.draw(
            st.lists(
                st.sampled_from(all_names),
                min_size=1,
                max_size=min(len(all_names), 8),
                unique=True,
            )
        )

        scope = ToolScope.only(subset)
        defs = scope.to_tool_defs(registry)

        for tool_def in defs:
            assert isinstance(tool_def.name, str)
            assert len(tool_def.name) > 0

    @given(data=st.data())
    @settings(max_examples=100)
    def test_all_results_have_description(self, data: st.DataObject) -> None:
        """Every ToolDef has a description field that is a string.

        **Validates: Requirements 6.8**
        """
        registry, descriptors = data.draw(job_registries())
        all_names = [d.name for d in descriptors]

        subset = data.draw(
            st.lists(
                st.sampled_from(all_names),
                min_size=1,
                max_size=min(len(all_names), 8),
                unique=True,
            )
        )

        scope = ToolScope.only(subset)
        defs = scope.to_tool_defs(registry)

        for tool_def in defs:
            assert isinstance(tool_def.description, str)
            # Our generated descriptors always have non-empty docstrings
            assert len(tool_def.description) > 0

    @given(data=st.data())
    @settings(max_examples=100)
    def test_all_results_have_parameters_schema_dict(self, data: st.DataObject) -> None:
        """Every ToolDef has a parameters_schema that is a dict.

        **Validates: Requirements 6.8**
        """
        registry, descriptors = data.draw(job_registries())
        all_names = [d.name for d in descriptors]

        subset = data.draw(
            st.lists(
                st.sampled_from(all_names),
                min_size=1,
                max_size=min(len(all_names), 8),
                unique=True,
            )
        )

        scope = ToolScope.only(subset)
        defs = scope.to_tool_defs(registry)

        for tool_def in defs:
            assert isinstance(tool_def.parameters_schema, dict)

    @given(data=st.data())
    @settings(max_examples=100)
    def test_no_provider_specific_types_in_results(self, data: st.DataObject) -> None:
        """ToolDef fields contain no provider-specific types (pydantic-ai, litellm, etc.).

        **Validates: Requirements 6.8**
        """
        registry, descriptors = data.draw(job_registries())
        all_names = [d.name for d in descriptors]

        subset = data.draw(
            st.lists(
                st.sampled_from(all_names),
                min_size=1,
                max_size=min(len(all_names), 8),
                unique=True,
            )
        )

        scope = ToolScope.only(subset)
        defs = scope.to_tool_defs(registry)

        for tool_def in defs:
            # Check that the type of each field is a standard Python type
            assert type(tool_def.name).__module__ == "builtins"
            assert type(tool_def.description).__module__ == "builtins"
            assert type(tool_def.parameters_schema).__module__ == "builtins"
            # function should be None for job-based tools
            assert tool_def.function is None

    @given(data=st.data())
    @settings(max_examples=100)
    def test_functions_scope_returns_tooldef_with_non_empty_name(
        self, data: st.DataObject
    ) -> None:
        """ToolScope.functions() also produces ToolDefs with non-empty names.

        **Validates: Requirements 6.8**
        """
        # Generate some random function names
        fn_names = data.draw(
            st.lists(job_names_st, min_size=1, max_size=5, unique=True)
        )

        # Create functions dynamically with unique names and docstrings
        functions = []
        for name in fn_names:
            # Create a simple function with a non-empty docstring
            fn = lambda x: x  # noqa: E731
            fn.__name__ = name
            fn.__doc__ = f"Tool function {name}."
            functions.append(fn)

        scope = ToolScope.functions(functions)
        # Use an empty registry since functions don't need it
        defs = scope.to_tool_defs(MockRegistry([]))

        for tool_def in defs:
            assert isinstance(tool_def, ToolDef)
            assert isinstance(tool_def.name, str)
            assert len(tool_def.name) > 0
            assert isinstance(tool_def.description, str)
            assert isinstance(tool_def.parameters_schema, dict)
