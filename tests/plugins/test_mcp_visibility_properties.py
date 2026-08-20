"""Property-based tests for MCP visibility filtering and partial config resolution.

Tests Property 28 and Property 30 from the Phase 2–5 Domain SDKs design document.

Property 28: MCP discover_jobs returns exactly the visible job set —
For any set of jobs with varying visibility, tags, and include-tags/exclude-jobs
config, discover_jobs SHALL return only jobs where: visibility ≠ "internal",
AND (include_tags is empty OR job has at least one matching tag), AND
job name is not in exclude_jobs, AND job does not have any excluded tag.

Property 30: MCP partial config resolution —
For any job with a config model having required and optional fields, when
run_job is called with a partial config (only required fields), the MCP adapter
SHALL resolve missing fields from the config chain and produce a fully valid
config model instance (i.e., succeed without error).

**Validates: Requirements 16.4, 16.12, 16.13, 16.14, 17.5**
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from hypothesis import assume, given
from hypothesis import strategies as st

# Stub out functualize_ai to avoid ImportError when functualize_mcp.__init__
# triggers import of _workflow_tools (which depends on functualize_ai).
if "functualize_ai" not in sys.modules:
    sys.modules["functualize_ai"] = MagicMock()

from functualize_mcp._config import MCPConfig  # noqa: E402
from functualize_mcp._tools import MCPToolRegistry  # noqa: E402

# ===========================================================================
# Test helpers — minimal descriptor and app fakes
# ===========================================================================


@dataclass(frozen=True)
class FakeField:
    """Minimal config field descriptor for testing."""

    name: str
    type_annotation: str
    default: Any | None = None
    description: str = ""
    required: bool = True
    choices: list[str] | None = None


@dataclass
class FakeDescriptor:
    """Minimal job descriptor for property testing."""

    name: str
    group: str | None = None
    docstring: str | None = None
    config_fields: list[FakeField] = field(default_factory=list)
    parameters: list[FakeField] = field(default_factory=list)
    declaration: Any = field(default_factory=dict)
    # Plugin extension data. Real JobDescriptors always carry this (empty for
    # most jobs) and the MCP translation path reads it, so a fake without it
    # fails during generation rather than in an assertion.
    metadata: dict[str, Any] = field(default_factory=dict)


class FakeJobResult:
    """Fake job result returned by app.execute()."""

    def __init__(
        self,
        status: str = "success",
        return_value: Any = None,
        duration_ms: float = 42.0,
    ):
        self.status = status
        self.return_value = return_value
        self.duration_ms = duration_ms


class FakeApp:
    """Minimal fake FunctualizeApp for testing MCPToolRegistry."""

    def __init__(
        self,
        descriptors: list[FakeDescriptor] | None = None,
        execute_results: dict[str, FakeJobResult] | None = None,
    ):
        self._descriptors = descriptors or []
        self._execute_results = execute_results or {}

    def get_jobs(self) -> list[FakeDescriptor]:
        return self._descriptors

    def get_job(self, name: str) -> FakeDescriptor | None:
        for d in self._descriptors:
            if d.name == name:
                return d
        return None

    def execute(self, job_name: str, **kwargs: Any) -> FakeJobResult:
        if job_name in self._execute_results:
            return self._execute_results[job_name]
        return FakeJobResult(status="success", return_value=f"executed {job_name}")


# ===========================================================================
# Strategies
# ===========================================================================

# Valid job names (alphanumeric + underscore, starting with a letter)
job_names_st = st.text(
    alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_"),
    min_size=1,
    max_size=20,
)

# Tags — simple lowercase identifiers
tag_st = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_-"),
    min_size=1,
    max_size=15,
)

# Tag lists (for metadata)
tags_list_st = st.lists(tag_st, min_size=0, max_size=4, unique=True)

# Visibility options
visibility_st = st.sampled_from([None, "public", "internal"])


@st.composite
def descriptor_st(draw: st.DrawFn) -> FakeDescriptor:
    """Generate a FakeDescriptor with random visibility and tags."""
    name = draw(job_names_st)
    visibility = draw(visibility_st)
    tags = draw(tags_list_st)
    metadata = SimpleNamespace(
        extra_description=None,
        category=None,
        examples=None,
        tags=tags,
        visibility=visibility,
    )
    return FakeDescriptor(
        name=name,
        docstring=f"{name} does something useful.",
        declaration=metadata,
    )


@st.composite
def descriptors_with_unique_names_st(
    draw: st.DrawFn, min_size: int = 1, max_size: int = 10
) -> list[FakeDescriptor]:
    """Generate a list of FakeDescriptors with unique names."""
    descriptors = draw(st.lists(descriptor_st(), min_size=min_size, max_size=max_size))
    # Ensure unique names
    seen: set[str] = set()
    unique: list[FakeDescriptor] = []
    for d in descriptors:
        if d.name not in seen:
            seen.add(d.name)
            unique.append(d)
    assume(len(unique) >= min_size)
    return unique


@st.composite
def mcp_config_for_descriptors_st(
    draw: st.DrawFn, descriptors: list[FakeDescriptor]
) -> MCPConfig:
    """Generate an MCPConfig with filters drawn from the given descriptors.

    This ensures that include_tags, exclude_tags, and exclude_jobs contain
    values that actually exist in the descriptor set (for meaningful filtering).
    """
    # Collect all tags and names from descriptors
    all_tags: set[str] = set()
    all_names: set[str] = set()
    for d in descriptors:
        tags = getattr(d.declaration, "tags", None) or []
        all_tags.update(tags)
        all_names.add(d.name)

    # Draw subset of tags/names for filtering
    include_tags = draw(
        st.lists(st.sampled_from(sorted(all_tags)), max_size=3, unique=True)
        if all_tags
        else st.just([])
    )
    exclude_tags = draw(
        st.lists(st.sampled_from(sorted(all_tags)), max_size=2, unique=True)
        if all_tags
        else st.just([])
    )
    exclude_jobs = draw(
        st.lists(st.sampled_from(sorted(all_names)), max_size=3, unique=True)
        if all_names
        else st.just([])
    )

    return MCPConfig(
        include_tags=include_tags,
        exclude_tags=exclude_tags,
        exclude_jobs=exclude_jobs,
    )


# ===========================================================================
# Helper: compute expected visible set
# ===========================================================================


def compute_expected_visible(
    descriptors: list[FakeDescriptor], config: MCPConfig
) -> set[str]:
    """Compute the expected set of visible job names given descriptors and config.

    Filtering rules (from _translator._filter_descriptors):
    1. Exclude jobs with visibility="internal"
    2. Exclude jobs listed in config.exclude_jobs
    3. Exclude jobs tagged with any tag in config.exclude_tags
    4. If config.include_tags is non-empty, include only jobs tagged
       with at least one of the specified tags
    """
    visible: set[str] = set()

    for d in descriptors:
        # Visibility and tags come from the `@job` declaration. `metadata` is
        # plugin extension data (a plain dict) and never carried these — read
        # it here and every job silently looks external, because `getattr` on a
        # dict returns the default rather than raising.
        declaration = d.declaration
        visibility = getattr(declaration, "visibility", None)
        tags = getattr(declaration, "tags", None) or []

        # Rule 1: exclude internal
        if visibility == "internal":
            continue

        # Rule 2: exclude by name
        if d.name in config.exclude_jobs:
            continue

        # Rule 3: exclude by excluded tags
        if config.exclude_tags and any(t in config.exclude_tags for t in tags):
            continue

        # Rule 4: include-tags filter
        if config.include_tags and not any(t in config.include_tags for t in tags):
            continue

        visible.add(d.name)

    return visible


# ===========================================================================
# Property 28: MCP discover_jobs returns exactly the visible job set
# ===========================================================================


class TestMCPDiscoverJobsVisibilityProperty:
    """Property 28: MCP discover_jobs returns exactly the visible job set.

    For any set of jobs with varying visibility, tags, and include-tags/exclude-jobs
    config, discover_jobs SHALL return only jobs where: visibility ≠ "internal",
    AND (include_tags is empty OR job has at least one matching tag), AND
    job name is not in exclude_jobs, AND job does not have any excluded tag.

    **Validates: Requirements 16.4, 16.12, 16.13, 16.14**
    """

    @given(data=st.data())
    def test_discover_jobs_returns_exactly_visible_set(
        self, data: st.DataObject
    ) -> None:
        """For any set of N job descriptors with mixed visibility/tags,
        discover_jobs returns EXACTLY the set matching MCPConfig filters.

        **Validates: Requirements 16.4, 16.12, 16.13, 16.14**
        """
        descriptors = data.draw(
            descriptors_with_unique_names_st(min_size=1, max_size=10)
        )
        config = data.draw(mcp_config_for_descriptors_st(descriptors))

        app = FakeApp(descriptors=descriptors)
        registry = MCPToolRegistry(app, config=config)
        result = asyncio.run(registry._discover_jobs())

        actual_names = {j["name"] for j in result["jobs"]}
        expected_names = compute_expected_visible(descriptors, config)

        assert actual_names == expected_names

    @given(data=st.data())
    def test_internal_jobs_never_appear(self, data: st.DataObject) -> None:
        """For any MCPConfig, jobs with visibility="internal" are never
        returned by discover_jobs.

        **Validates: Requirements 16.12**
        """
        descriptors = data.draw(
            descriptors_with_unique_names_st(min_size=1, max_size=10)
        )
        config = data.draw(mcp_config_for_descriptors_st(descriptors))

        app = FakeApp(descriptors=descriptors)
        registry = MCPToolRegistry(app, config=config)
        result = asyncio.run(registry._discover_jobs())

        actual_names = {j["name"] for j in result["jobs"]}

        # Verify no internal jobs appear
        for d in descriptors:
            visibility = getattr(d.declaration, "visibility", None)
            if visibility == "internal":
                assert d.name not in actual_names, (
                    f"Internal job '{d.name}' should not appear in discover_jobs"
                )

    @given(data=st.data())
    def test_excluded_jobs_never_appear(self, data: st.DataObject) -> None:
        """For any MCPConfig with exclude_jobs, those jobs are never
        returned by discover_jobs.

        **Validates: Requirements 16.14**
        """
        descriptors = data.draw(
            descriptors_with_unique_names_st(min_size=1, max_size=10)
        )
        config = data.draw(mcp_config_for_descriptors_st(descriptors))

        app = FakeApp(descriptors=descriptors)
        registry = MCPToolRegistry(app, config=config)
        result = asyncio.run(registry._discover_jobs())

        actual_names = {j["name"] for j in result["jobs"]}

        # Verify excluded jobs do not appear
        for excluded_name in config.exclude_jobs:
            assert excluded_name not in actual_names, (
                f"Excluded job '{excluded_name}' should not appear in discover_jobs"
            )

    @given(data=st.data())
    def test_include_tags_filters_correctly(self, data: st.DataObject) -> None:
        """When include_tags is non-empty, only jobs with at least one matching
        tag appear in discover_jobs results.

        **Validates: Requirements 16.13**
        """
        descriptors = data.draw(
            descriptors_with_unique_names_st(min_size=1, max_size=10)
        )
        # Force include_tags to be non-empty for this test
        all_tags: set[str] = set()
        for d in descriptors:
            tags = getattr(d.declaration, "tags", None) or []
            all_tags.update(tags)

        assume(len(all_tags) > 0)

        include_tags = data.draw(
            st.lists(
                st.sampled_from(sorted(all_tags)), min_size=1, max_size=3, unique=True
            )
        )
        config = MCPConfig(include_tags=include_tags)

        app = FakeApp(descriptors=descriptors)
        registry = MCPToolRegistry(app, config=config)
        result = asyncio.run(registry._discover_jobs())

        actual_names = {j["name"] for j in result["jobs"]}

        # Every returned job must have at least one tag in include_tags
        for d in descriptors:
            if d.name in actual_names:
                tags = getattr(d.declaration, "tags", None) or []
                assert any(t in include_tags for t in tags), (
                    f"Job '{d.name}' appeared but has no matching include_tag. "
                    f"Job tags: {tags}, include_tags: {include_tags}"
                )

    @given(data=st.data())
    def test_discover_jobs_result_structure(self, data: st.DataObject) -> None:
        """Each job in discover_jobs result has name, description, and tags fields.

        **Validates: Requirements 16.4**
        """
        descriptors = data.draw(
            descriptors_with_unique_names_st(min_size=1, max_size=8)
        )
        config = MCPConfig()

        app = FakeApp(descriptors=descriptors)
        registry = MCPToolRegistry(app, config=config)
        result = asyncio.run(registry._discover_jobs())

        for job in result["jobs"]:
            assert "name" in job, "Job missing 'name' field"
            assert "description" in job, "Job missing 'description' field"
            assert "tags" in job, "Job missing 'tags' field"
            assert isinstance(job["name"], str)
            assert isinstance(job["description"], str)
            assert isinstance(job["tags"], list)


# ===========================================================================
# Property 30: MCP partial config resolution
# ===========================================================================


# Reserved names that conflict with app.execute() signature
_RESERVED_NAMES = frozenset({"job_name", "name", "self", "kwargs", "args"})

# Field name strategy for config fields
field_names_st = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "N"), whitelist_characters="_"),
    min_size=2,
    max_size=15,
).filter(lambda s: (s[0].isalpha() or s[0] == "_") and s not in _RESERVED_NAMES)

# Type annotations
type_annotations_st = st.sampled_from(["str", "int", "float", "bool"])


@st.composite
def config_fields_st(draw: st.DrawFn) -> list[FakeField]:
    """Generate a mix of required and optional config fields with unique names."""
    num_required = draw(st.integers(min_value=1, max_value=3))
    num_optional = draw(st.integers(min_value=1, max_value=3))

    names = draw(
        st.lists(
            field_names_st,
            min_size=num_required + num_optional,
            max_size=num_required + num_optional,
            unique=True,
        )
    )

    fields: list[FakeField] = []

    # Required fields
    for i in range(num_required):
        type_ann = draw(type_annotations_st)
        fields.append(
            FakeField(
                name=names[i],
                type_annotation=type_ann,
                required=True,
                description=f"Required field {names[i]}",
            )
        )

    # Optional fields with defaults
    for i in range(num_required, num_required + num_optional):
        type_ann = draw(type_annotations_st)
        default = _default_for_type(type_ann)
        fields.append(
            FakeField(
                name=names[i],
                type_annotation=type_ann,
                required=False,
                default=default,
                description=f"Optional field {names[i]}",
            )
        )

    return fields


def _default_for_type(type_ann: str) -> Any:
    """Return a sensible default value for a given type annotation."""
    defaults = {
        "str": "default_value",
        "int": 0,
        "float": 0.0,
        "bool": False,
    }
    return defaults.get(type_ann, "default")


def _value_for_type(type_ann: str) -> Any:
    """Return a sensible test value for a given type annotation."""
    values = {
        "str": "test_value",
        "int": 42,
        "float": 3.14,
        "bool": True,
    }
    return values.get(type_ann, "test")


class TestMCPPartialConfigResolutionProperty:
    """Property 30: MCP partial config resolution.

    For any job with required and optional config fields, run_job with
    partial config (only required fields) should succeed without error.

    **Validates: Requirements 17.5**
    """

    @given(data=st.data())
    def test_run_job_with_only_required_fields_succeeds(
        self, data: st.DataObject
    ) -> None:
        """For any job with required and optional config fields, run_job
        with only required fields provided succeeds without error.

        **Validates: Requirements 17.5**
        """
        job_name = data.draw(job_names_st)
        fields = data.draw(config_fields_st())

        descriptor = FakeDescriptor(
            name=job_name,
            docstring=f"{job_name} processes data.",
            config_fields=fields,
            declaration=SimpleNamespace(
                extra_description=None,
                category=None,
                examples=None,
                tags=[],
                visibility=None,
            ),
        )

        app = FakeApp(descriptors=[descriptor])
        registry = MCPToolRegistry(app, config=MCPConfig())

        # Build partial config with only required fields
        partial_config = {
            f.name: _value_for_type(f.type_annotation) for f in fields if f.required
        }

        result = asyncio.run(registry._run_job(job_name, partial_config))

        # Should succeed without error
        assert "error" not in result, (
            f"run_job with partial config (required-only) failed: {result}"
        )
        assert result["status"] == "success"

    @given(data=st.data())
    def test_run_job_with_full_config_succeeds(self, data: st.DataObject) -> None:
        """For any job with required and optional config fields, run_job
        with all fields provided succeeds without error.

        **Validates: Requirements 17.5**
        """
        job_name = data.draw(job_names_st)
        fields = data.draw(config_fields_st())

        descriptor = FakeDescriptor(
            name=job_name,
            docstring=f"{job_name} processes data.",
            config_fields=fields,
            declaration=SimpleNamespace(
                extra_description=None,
                category=None,
                examples=None,
                tags=[],
                visibility=None,
            ),
        )

        app = FakeApp(descriptors=[descriptor])
        registry = MCPToolRegistry(app, config=MCPConfig())

        # Build full config with all fields
        full_config = {f.name: _value_for_type(f.type_annotation) for f in fields}

        result = asyncio.run(registry._run_job(job_name, full_config))

        # Should succeed without error
        assert "error" not in result, f"run_job with full config failed: {result}"
        assert result["status"] == "success"

    @given(data=st.data())
    def test_run_job_with_empty_config_succeeds(self, data: st.DataObject) -> None:
        """For any visible job, run_job with empty config (None) succeeds
        when the app resolves missing fields from the config chain.

        **Validates: Requirements 17.5**
        """
        job_name = data.draw(job_names_st)
        fields = data.draw(config_fields_st())

        descriptor = FakeDescriptor(
            name=job_name,
            docstring=f"{job_name} processes data.",
            config_fields=fields,
            declaration=SimpleNamespace(
                extra_description=None,
                category=None,
                examples=None,
                tags=[],
                visibility=None,
            ),
        )

        app = FakeApp(descriptors=[descriptor])
        registry = MCPToolRegistry(app, config=MCPConfig())

        # Call with no config — the config chain should resolve all fields
        result = asyncio.run(registry._run_job(job_name, None))

        # Should succeed without error (app.execute handles resolution)
        assert "error" not in result, f"run_job with no config failed: {result}"
        assert result["status"] == "success"

    @given(data=st.data())
    def test_partial_config_kwargs_passed_to_execute(self, data: st.DataObject) -> None:
        """For any job, the partial config dict is passed as kwargs to
        app.execute(), allowing the config chain to resolve missing fields.

        **Validates: Requirements 17.5**
        """
        job_name = data.draw(job_names_st)
        fields = data.draw(config_fields_st())

        descriptor = FakeDescriptor(
            name=job_name,
            docstring=f"{job_name} processes data.",
            config_fields=fields,
            declaration=SimpleNamespace(
                extra_description=None,
                category=None,
                examples=None,
                tags=[],
                visibility=None,
            ),
        )

        # Track what kwargs are passed to execute
        captured_kwargs: dict[str, Any] = {}

        class TrackingApp(FakeApp):
            def execute(self, jn: str, **kwargs: Any) -> FakeJobResult:
                captured_kwargs.update(kwargs)
                return FakeJobResult(status="success", return_value="ok")

        app = TrackingApp(descriptors=[descriptor])
        registry = MCPToolRegistry(app, config=MCPConfig())

        # Build partial config with only required fields
        partial_config = {
            f.name: _value_for_type(f.type_annotation) for f in fields if f.required
        }

        asyncio.run(registry._run_job(job_name, partial_config))

        # Verify that exactly the required-field kwargs were passed
        for f in fields:
            if f.required:
                assert f.name in captured_kwargs, (
                    f"Required field '{f.name}' not passed to execute()"
                )
                assert captured_kwargs[f.name] == _value_for_type(f.type_annotation)
