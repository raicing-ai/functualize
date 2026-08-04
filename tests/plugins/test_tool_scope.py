"""Unit tests for the ToolScope builder class.

Tests the deny-by-default tool visibility builder for AI calls,
validating filtering, composition, and resolution to ToolDefs.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from functualize_ai import ToolDef, ToolScope

# ===========================================================================
# Test fixtures / helpers
# ===========================================================================


def _make_descriptor(
    name: str,
    group: str | None = None,
    docstring: str = "",
    tags: list[str] | None = None,
    config_fields: list[Any] | None = None,
) -> SimpleNamespace:
    """Create a mock job descriptor for testing."""
    metadata = SimpleNamespace(tags=tags) if tags else SimpleNamespace(tags=[])
    return SimpleNamespace(
        name=name,
        group=group,
        docstring=docstring,
        metadata=metadata,
        config_fields=config_fields or [],
        parameters=[],
    )


class MockRegistry:
    """A mock job registry for testing ToolScope resolution."""

    def __init__(self, descriptors: list[Any]) -> None:
        self._descriptors = descriptors

    def get_descriptors(self) -> list[Any]:
        return self._descriptors


@pytest.fixture
def sample_descriptors() -> list[Any]:
    """Create a sample set of job descriptors."""
    return [
        _make_descriptor(
            "deploy",
            group="ops",
            docstring="Deploy app",
            tags=["production", "deployment"],
        ),
        _make_descriptor(
            "build", group="dev", docstring="Build project", tags=["development"]
        ),
        _make_descriptor(
            "test_suite",
            group="dev",
            docstring="Run tests",
            tags=["testing", "development"],
        ),
        _make_descriptor(
            "monitor",
            group="ops",
            docstring="Monitor services",
            tags=["production", "observability"],
        ),
        _make_descriptor(
            "cleanup", group=None, docstring="Clean up resources", tags=[]
        ),
    ]


@pytest.fixture
def registry(sample_descriptors: list[Any]) -> MockRegistry:
    """Create a mock registry with sample descriptors."""
    return MockRegistry(sample_descriptors)


# ===========================================================================
# Test ToolScope.only()
# ===========================================================================


class TestToolScopeOnly:
    """Tests for ToolScope.only() class method."""

    def test_filters_to_listed_names(self, registry: MockRegistry) -> None:
        scope = ToolScope.only(["deploy", "build"])
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 2
        assert {d.name for d in defs} == {"deploy", "build"}

    def test_single_name(self, registry: MockRegistry) -> None:
        scope = ToolScope.only(["deploy"])
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 1
        assert defs[0].name == "deploy"

    def test_empty_list_returns_no_tools(self, registry: MockRegistry) -> None:
        scope = ToolScope.only([])
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 0

    def test_nonexistent_name_ignored(self, registry: MockRegistry) -> None:
        scope = ToolScope.only(["deploy", "nonexistent"])
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 1
        assert defs[0].name == "deploy"

    def test_returns_tool_defs(self, registry: MockRegistry) -> None:
        scope = ToolScope.only(["deploy"])
        defs = scope.to_tool_defs(registry)
        assert all(isinstance(d, ToolDef) for d in defs)

    def test_tool_def_has_job_name(self, registry: MockRegistry) -> None:
        scope = ToolScope.only(["deploy"])
        defs = scope.to_tool_defs(registry)
        assert defs[0].job_name == "deploy"

    def test_tool_def_has_description(self, registry: MockRegistry) -> None:
        scope = ToolScope.only(["deploy"])
        defs = scope.to_tool_defs(registry)
        assert defs[0].description == "Deploy app"


# ===========================================================================
# Test ToolScope.tagged()
# ===========================================================================


class TestToolScopeTagged:
    """Tests for ToolScope.tagged() class method."""

    def test_single_tag(self, registry: MockRegistry) -> None:
        scope = ToolScope.tagged("production")
        defs = scope.to_tool_defs(registry)
        assert {d.name for d in defs} == {"deploy", "monitor"}

    def test_multiple_tags_requires_all(self, registry: MockRegistry) -> None:
        scope = ToolScope.tagged("production", "deployment")
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 1
        assert defs[0].name == "deploy"

    def test_no_matching_tags(self, registry: MockRegistry) -> None:
        scope = ToolScope.tagged("nonexistent")
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 0

    def test_empty_tags_matches_all(self, registry: MockRegistry) -> None:
        # No tags required means all pass the filter
        scope = ToolScope.tagged()
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 5


# ===========================================================================
# Test ToolScope.group()
# ===========================================================================


class TestToolScopeGroup:
    """Tests for ToolScope.group() class method."""

    def test_filters_by_group(self, registry: MockRegistry) -> None:
        scope = ToolScope.group("ops")
        defs = scope.to_tool_defs(registry)
        assert {d.name for d in defs} == {"deploy", "monitor"}

    def test_different_group(self, registry: MockRegistry) -> None:
        scope = ToolScope.group("dev")
        defs = scope.to_tool_defs(registry)
        assert {d.name for d in defs} == {"build", "test_suite"}

    def test_nonexistent_group(self, registry: MockRegistry) -> None:
        scope = ToolScope.group("nonexistent")
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 0


# ===========================================================================
# Test ToolScope.functions()
# ===========================================================================


class TestToolScopeFunctions:
    """Tests for ToolScope.functions() class method."""

    def test_includes_callable(self, registry: MockRegistry) -> None:
        def my_tool(x: int, y: str) -> str:
            """Does something."""
            return f"{x}{y}"

        scope = ToolScope.functions([my_tool])
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 1
        assert defs[0].name == "my_tool"

    def test_uses_docstring_as_description(self, registry: MockRegistry) -> None:
        def my_tool(x: int) -> int:
            """Compute a value."""
            return x * 2

        scope = ToolScope.functions([my_tool])
        defs = scope.to_tool_defs(registry)
        assert defs[0].description == "Compute a value."

    def test_no_docstring(self, registry: MockRegistry) -> None:
        def bare_tool(x: int) -> int:
            return x

        scope = ToolScope.functions([bare_tool])
        defs = scope.to_tool_defs(registry)
        assert defs[0].description == ""

    def test_function_ref_preserved(self, registry: MockRegistry) -> None:
        def my_tool() -> None:
            """A tool."""
            pass

        scope = ToolScope.functions([my_tool])
        defs = scope.to_tool_defs(registry)
        assert defs[0].function is my_tool

    def test_job_name_is_none(self, registry: MockRegistry) -> None:
        def my_tool() -> None:
            """A tool."""
            pass

        scope = ToolScope.functions([my_tool])
        defs = scope.to_tool_defs(registry)
        assert defs[0].job_name is None

    def test_schema_from_signature(self, registry: MockRegistry) -> None:
        def my_tool(name: str, count: int, flag: bool = False) -> None:
            """A tool."""
            pass

        scope = ToolScope.functions([my_tool])
        defs = scope.to_tool_defs(registry)
        schema = defs[0].parameters_schema
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"
        assert schema["properties"]["flag"]["type"] == "boolean"
        assert "name" in schema["required"]
        assert "count" in schema["required"]
        assert "flag" not in schema["required"]

    def test_multiple_functions(self, registry: MockRegistry) -> None:
        def tool_a() -> None:
            """Tool A."""
            pass

        def tool_b(x: int) -> int:
            """Tool B."""
            return x

        scope = ToolScope.functions([tool_a, tool_b])
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 2
        assert {d.name for d in defs} == {"tool_a", "tool_b"}


# ===========================================================================
# Test + operator (union)
# ===========================================================================


class TestToolScopeUnion:
    """Tests for the + operator combining ToolScopes."""

    def test_union_includes_both(self, registry: MockRegistry) -> None:
        scope1 = ToolScope.only(["deploy"])
        scope2 = ToolScope.only(["build"])
        combined = scope1 + scope2
        defs = combined.to_tool_defs(registry)
        assert {d.name for d in defs} == {"deploy", "build"}

    def test_union_deduplicates(self, registry: MockRegistry) -> None:
        scope1 = ToolScope.only(["deploy"])
        scope2 = ToolScope.only(["deploy", "build"])
        combined = scope1 + scope2
        defs = combined.to_tool_defs(registry)
        assert len(defs) == 2
        names = [d.name for d in defs]
        assert names.count("deploy") == 1

    def test_union_mixed_filter_types(self, registry: MockRegistry) -> None:
        scope1 = ToolScope.only(["deploy"])
        scope2 = ToolScope.group("dev")
        combined = scope1 + scope2
        defs = combined.to_tool_defs(registry)
        assert {d.name for d in defs} == {"deploy", "build", "test_suite"}

    def test_union_with_functions(self, registry: MockRegistry) -> None:
        def helper(x: int) -> int:
            """Help."""
            return x

        scope1 = ToolScope.only(["deploy"])
        scope2 = ToolScope.functions([helper])
        combined = scope1 + scope2
        defs = combined.to_tool_defs(registry)
        assert len(defs) == 2
        assert {d.name for d in defs} == {"deploy", "helper"}

    def test_union_merges_instructions(self) -> None:
        scope1 = ToolScope.only(["a"]).with_instructions("First")
        scope2 = ToolScope.only(["b"]).with_instructions("Second")
        combined = scope1 + scope2
        assert combined.instructions == "First\nSecond"

    def test_union_one_has_instructions(self) -> None:
        scope1 = ToolScope.only(["a"]).with_instructions("Only one")
        scope2 = ToolScope.only(["b"])
        combined = scope1 + scope2
        assert combined.instructions == "Only one"

    def test_union_merges_approval(self) -> None:
        scope1 = ToolScope.only(["a"]).approval_required()
        scope2 = ToolScope.only(["b"])
        combined = scope1 + scope2
        assert combined.requires_approval is True

    def test_union_returns_new_instance(self) -> None:
        scope1 = ToolScope.only(["a"])
        scope2 = ToolScope.only(["b"])
        combined = scope1 + scope2
        assert combined is not scope1
        assert combined is not scope2


# ===========================================================================
# Test with_instructions()
# ===========================================================================


class TestToolScopeWithInstructions:
    """Tests for ToolScope.with_instructions() modifier."""

    def test_attaches_instructions(self) -> None:
        scope = ToolScope.only(["deploy"]).with_instructions("Be careful")
        assert scope.instructions == "Be careful"

    def test_returns_new_instance(self) -> None:
        scope1 = ToolScope.only(["deploy"])
        scope2 = scope1.with_instructions("Be careful")
        assert scope1 is not scope2
        assert scope1.instructions is None
        assert scope2.instructions == "Be careful"

    def test_preserves_filters(self, registry: MockRegistry) -> None:
        scope = ToolScope.only(["deploy"]).with_instructions("text")
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 1
        assert defs[0].name == "deploy"


# ===========================================================================
# Test approval_required()
# ===========================================================================


class TestToolScopeApprovalRequired:
    """Tests for ToolScope.approval_required() modifier."""

    def test_marks_approval_required(self) -> None:
        scope = ToolScope.only(["deploy"]).approval_required()
        assert scope.requires_approval is True

    def test_default_no_approval(self) -> None:
        scope = ToolScope.only(["deploy"])
        assert scope.requires_approval is False

    def test_with_gate_callable(self) -> None:
        def my_gate() -> bool:
            return True

        scope = ToolScope.only(["deploy"]).approval_required(gate=my_gate)
        assert scope.requires_approval is True
        assert scope.approval_gate is my_gate

    def test_returns_new_instance(self) -> None:
        scope1 = ToolScope.only(["deploy"])
        scope2 = scope1.approval_required()
        assert scope1 is not scope2
        assert scope1.requires_approval is False
        assert scope2.requires_approval is True

    def test_preserves_filters(self, registry: MockRegistry) -> None:
        scope = ToolScope.only(["deploy"]).approval_required()
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 1
        assert defs[0].name == "deploy"


# ===========================================================================
# Test to_tool_defs() with config fields
# ===========================================================================


class TestToolScopeToToolDefs:
    """Tests for ToolScope.to_tool_defs() resolution."""

    def test_generates_schema_from_config_fields(self) -> None:
        fields = [
            SimpleNamespace(
                name="target",
                type_annotation="str",
                description="Deployment target",
                required=True,
                choices=None,
            ),
            SimpleNamespace(
                name="dry_run",
                type_annotation="bool",
                description="Dry run mode",
                required=False,
                choices=None,
            ),
        ]
        desc = _make_descriptor("deploy", config_fields=fields)
        registry = MockRegistry([desc])

        scope = ToolScope.only(["deploy"])
        defs = scope.to_tool_defs(registry)
        schema = defs[0].parameters_schema

        assert schema["type"] == "object"
        assert "target" in schema["properties"]
        assert schema["properties"]["target"]["type"] == "string"
        assert schema["properties"]["dry_run"]["type"] == "boolean"
        assert "target" in schema["required"]
        assert "dry_run" not in schema.get("required", [])

    def test_empty_config_fields_empty_schema(self) -> None:
        desc = _make_descriptor("simple")
        registry = MockRegistry([desc])

        scope = ToolScope.only(["simple"])
        defs = scope.to_tool_defs(registry)
        assert defs[0].parameters_schema == {}

    def test_metadata_with_dict_tags(self) -> None:
        """Test that descriptors with dict-style metadata also work."""
        desc = SimpleNamespace(
            name="my_job",
            group="grp",
            docstring="A job",
            metadata={"tags": ["alpha", "beta"]},
            config_fields=[],
            parameters=[],
        )
        registry = MockRegistry([desc])

        scope = ToolScope.tagged("alpha")
        defs = scope.to_tool_defs(registry)
        assert len(defs) == 1
        assert defs[0].name == "my_job"

    def test_duck_typed_iterable_registry(self) -> None:
        """Test that an iterable can be used as a registry."""
        descriptors = [_make_descriptor("job1"), _make_descriptor("job2")]
        scope = ToolScope.only(["job1"])
        defs = scope.to_tool_defs(descriptors)
        assert len(defs) == 1
        assert defs[0].name == "job1"

    def test_zero_ai_plugin_dependencies(self) -> None:
        """Ensure ToolScope has no imports from AI implementation plugins."""

        import functualize_ai._tool_scope as module

        # Check that no pydantic-ai or litellm modules are loaded by our module
        source = module.__file__
        assert source is not None
        with open(source) as f:
            content = f.read()
        assert "pydantic_ai" not in content
        assert "litellm" not in content
        assert "openai" not in content
        assert "anthropic" not in content
