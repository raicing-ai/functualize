"""Unit tests for SchemaExporter — multi-format schema export.

Tests all four export formats (JSON, Markdown, OpenAI, TypeScript) and the
CLI command registration for `func mcp schema` and `func mcp tools`.

Validates Requirements: 19.1, 19.2, 19.3, 19.4, 19.5
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from functualize_mcp._schema_export import SchemaExporter

# ===========================================================================
# Test fixtures
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
    """Minimal job descriptor for unit testing."""

    name: str
    group: str | None = None
    docstring: str | None = None
    config_fields: list[FakeField] = field(default_factory=list)
    parameters: list[FakeField] = field(default_factory=list)
    declaration: Any = field(default_factory=dict)


@pytest.fixture
def exporter() -> SchemaExporter:
    return SchemaExporter()


@pytest.fixture
def simple_descriptor() -> FakeDescriptor:
    """A simple descriptor with one required and one optional field."""
    return FakeDescriptor(
        name="greet_user",
        docstring="Greet a user by name.\n\nAdditional details.",
        config_fields=[
            FakeField(
                name="name",
                type_annotation="str",
                required=True,
                description="The name to greet",
            ),
            FakeField(
                name="count",
                type_annotation="int",
                required=False,
                default=1,
                description="Number of greetings",
            ),
        ],
        declaration=SimpleNamespace(
            extra_description=None,
            category=None,
            examples=None,
            tags=["demo"],
            visibility=None,
        ),
    )


@pytest.fixture
def descriptor_with_examples() -> FakeDescriptor:
    """A descriptor with examples and multiple tags."""
    return FakeDescriptor(
        name="deploy_app",
        docstring="Deploy the application to target environment.",
        config_fields=[
            FakeField(
                name="env",
                type_annotation="str",
                required=True,
                description="Target environment",
                choices=["dev", "staging", "prod"],
            ),
            FakeField(
                name="dry_run",
                type_annotation="bool",
                required=False,
                default=False,
                description="Skip actual deployment",
            ),
        ],
        declaration=SimpleNamespace(
            extra_description=None,
            category="deployment",
            examples=["deploy --env staging", "deploy --env prod"],
            tags=["deploy", "ops"],
            visibility=None,
        ),
    )


# ===========================================================================
# export_json tests (Requirement 19.1)
# ===========================================================================


class TestExportJson:
    """Tests for export_json — MCP tool definition format."""

    def test_produces_valid_json_array(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_json([simple_descriptor])
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_tool_has_name_description_input_schema(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_json([simple_descriptor])
        parsed = json.loads(result)
        tool = parsed[0]
        assert tool["name"] == "greet_user"
        assert "Greet a user by name" in tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        assert "name" in tool["inputSchema"]["properties"]

    def test_includes_annotations_when_present(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_json([simple_descriptor])
        parsed = json.loads(result)
        tool = parsed[0]
        assert "annotations" in tool
        assert tool["annotations"]["tags"] == ["demo"]

    def test_empty_descriptors_produces_empty_array(
        self, exporter: SchemaExporter
    ) -> None:
        result = exporter.export_json([])
        parsed = json.loads(result)
        assert parsed == []

    def test_multiple_descriptors(
        self,
        exporter: SchemaExporter,
        simple_descriptor: FakeDescriptor,
        descriptor_with_examples: FakeDescriptor,
    ) -> None:
        result = exporter.export_json([simple_descriptor, descriptor_with_examples])
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "greet_user"
        assert parsed[1]["name"] == "deploy_app"


# ===========================================================================
# export_markdown tests (Requirement 19.2)
# ===========================================================================


class TestExportMarkdown:
    """Tests for export_markdown — parameters table per job."""

    def test_returns_list_of_tuples(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_markdown([simple_descriptor])
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], tuple)
        assert result[0][0] == "greet_user"

    def test_contains_heading_with_job_name(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_markdown([simple_descriptor])
        _, md = result[0]
        assert "# greet_user" in md

    def test_contains_parameters_table(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_markdown([simple_descriptor])
        _, md = result[0]
        assert "| Name | Type | Required | Default | Description |" in md
        assert "| name | string | Yes | - | The name to greet |" in md
        assert "| count | integer | No | 1 | Number of greetings |" in md

    def test_includes_examples_in_description(
        self, exporter: SchemaExporter, descriptor_with_examples: FakeDescriptor
    ) -> None:
        result = exporter.export_markdown([descriptor_with_examples])
        _, md = result[0]
        assert "deploy --env staging" in md
        assert "deploy --env prod" in md

    def test_includes_annotations_section(
        self, exporter: SchemaExporter, descriptor_with_examples: FakeDescriptor
    ) -> None:
        result = exporter.export_markdown([descriptor_with_examples])
        _, md = result[0]
        assert "## Annotations" in md
        assert "**tags**" in md
        assert "deploy" in md

    def test_includes_enum_choices_in_description(
        self, exporter: SchemaExporter, descriptor_with_examples: FakeDescriptor
    ) -> None:
        result = exporter.export_markdown([descriptor_with_examples])
        _, md = result[0]
        assert "choices:" in md
        assert "dev" in md
        assert "staging" in md
        assert "prod" in md


# ===========================================================================
# export_openai tests (Requirement 19.3)
# ===========================================================================


class TestExportOpenAI:
    """Tests for export_openai — OpenAI function calling JSON format."""

    def test_produces_valid_json_array(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_openai([simple_descriptor])
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_entry_has_type_function(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_openai([simple_descriptor])
        parsed = json.loads(result)
        assert parsed[0]["type"] == "function"

    def test_function_has_name_description_parameters(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_openai([simple_descriptor])
        parsed = json.loads(result)
        fn = parsed[0]["function"]
        assert fn["name"] == "greet_user"
        assert "Greet a user by name" in fn["description"]
        assert fn["parameters"]["type"] == "object"
        assert "name" in fn["parameters"]["properties"]

    def test_parameters_include_required_array(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_openai([simple_descriptor])
        parsed = json.loads(result)
        params = parsed[0]["function"]["parameters"]
        assert "name" in params["required"]
        assert "count" not in params.get("required", [])


# ===========================================================================
# export_typescript tests (Requirement 19.4)
# ===========================================================================


class TestExportTypescript:
    """Tests for export_typescript — TypeScript type definitions."""

    def test_produces_interface_definition(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_typescript([simple_descriptor])
        assert "export interface GreetUserConfig" in result

    def test_required_fields_are_not_optional(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_typescript([simple_descriptor])
        # Required field "name" should not have ?
        assert "name: string;" in result

    def test_optional_fields_have_question_mark(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_typescript([simple_descriptor])
        # Optional field "count" should have ?
        assert "count?: number;" in result

    def test_includes_jsdoc_comment(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_typescript([simple_descriptor])
        assert "/**" in result
        assert "Greet a user by name" in result
        assert " */" in result

    def test_includes_field_description_comments(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_typescript([simple_descriptor])
        assert "/** The name to greet */" in result
        assert "/** Number of greetings */" in result

    def test_includes_auto_generated_header(
        self, exporter: SchemaExporter, simple_descriptor: FakeDescriptor
    ) -> None:
        result = exporter.export_typescript([simple_descriptor])
        assert "// Auto-generated TypeScript definitions" in result

    def test_enum_fields_produce_union_types(
        self, exporter: SchemaExporter, descriptor_with_examples: FakeDescriptor
    ) -> None:
        result = exporter.export_typescript([descriptor_with_examples])
        # Enum choices should become string literal union
        assert '"dev" | "staging" | "prod"' in result

    def test_boolean_field_maps_to_boolean_type(
        self, exporter: SchemaExporter, descriptor_with_examples: FakeDescriptor
    ) -> None:
        result = exporter.export_typescript([descriptor_with_examples])
        assert "dry_run?: boolean;" in result

    def test_pascal_case_conversion(self, exporter: SchemaExporter) -> None:
        desc = FakeDescriptor(
            name="my_complex_job_name",
            docstring="A complex job.",
            config_fields=[
                FakeField(name="x", type_annotation="str", required=True),
            ],
            declaration=SimpleNamespace(
                extra_description=None,
                category=None,
                examples=None,
                tags=None,
                visibility=None,
            ),
        )
        result = exporter.export_typescript([desc])
        assert "export interface MyComplexJobNameConfig" in result

    def test_multiple_interfaces_for_multiple_descriptors(
        self,
        exporter: SchemaExporter,
        simple_descriptor: FakeDescriptor,
        descriptor_with_examples: FakeDescriptor,
    ) -> None:
        result = exporter.export_typescript(
            [simple_descriptor, descriptor_with_examples]
        )
        assert "export interface GreetUserConfig" in result
        assert "export interface DeployAppConfig" in result

    def test_empty_descriptors_produces_header_only(
        self, exporter: SchemaExporter
    ) -> None:
        result = exporter.export_typescript([])
        assert "// Auto-generated TypeScript definitions" in result
        assert "export interface" not in result

    def test_array_type_fields(self, exporter: SchemaExporter) -> None:
        desc = FakeDescriptor(
            name="batch_job",
            docstring="Process items.",
            config_fields=[
                FakeField(
                    name="items",
                    type_annotation="list[str]",
                    required=True,
                    description="Items to process",
                ),
            ],
            declaration=SimpleNamespace(
                extra_description=None,
                category=None,
                examples=None,
                tags=None,
                visibility=None,
            ),
        )
        result = exporter.export_typescript([desc])
        assert "items: string[];" in result


# ===========================================================================
# CLI command integration tests (Requirement 19.5)
# ===========================================================================


class TestCLICommandRegistration:
    """Tests that schema and tools CLI commands are registered correctly."""

    def test_schema_command_is_registered_by_plugin(self) -> None:
        """MCPAdapterPlugin registers 'schema' command under 'mcp' group."""
        from unittest.mock import MagicMock, patch

        from functualize_mcp._plugin import MCPAdapterPlugin

        plugin = MCPAdapterPlugin()
        app = MagicMock()
        app.resolve_model.return_value = MagicMock(
            transport="stdio", host="127.0.0.1", port=8080
        )

        # Mock MCPServer to avoid full initialization
        with patch("functualize_mcp._server.MCPServer"):
            plugin._on_app_ready(app)

        # register_plugin_command called with "schema" and namespace="mcp"
        schema_calls = [
            call
            for call in app.register_plugin_command.call_args_list
            if len(call[0]) > 0 and call[0][0] == "schema"
        ]
        assert len(schema_calls) == 1

    def test_tools_command_is_registered_by_plugin(self) -> None:
        """MCPAdapterPlugin registers 'tools' command under 'mcp' namespace."""
        from unittest.mock import MagicMock, patch

        from functualize_mcp._plugin import MCPAdapterPlugin

        plugin = MCPAdapterPlugin()
        app = MagicMock()
        app.resolve_model.return_value = MagicMock(
            transport="stdio", host="127.0.0.1", port=8080
        )

        with patch("functualize_mcp._server.MCPServer"):
            plugin._on_app_ready(app)

        tools_calls = [
            call
            for call in app.register_plugin_command.call_args_list
            if len(call[0]) > 0 and call[0][0] == "tools"
        ]
        assert len(tools_calls) == 1
