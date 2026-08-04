"""Property-based tests for schema export format correctness.

Tests Property 33 from the Phase 2–5 Domain SDKs design document.

Property 33: Schema export format correctness —
For any list of JobDescriptors, `export_json` SHALL produce valid JSON conforming
to MCP tool definition format, `export_markdown` SHALL produce markdown files
containing a parameters table for each job, and `export_openai` SHALL produce
valid OpenAI function calling JSON.

**Validates: Requirements 19.1, 19.2, 19.3**
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from functualize_mcp._schema_export import SchemaExporter
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# ===========================================================================
# Test helpers — minimal descriptor fakes
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


# ===========================================================================
# Strategies
# ===========================================================================

# Valid job names (alphanumeric + underscore, starting with a letter)
job_names_st = st.text(
    alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_"),
    min_size=1,
    max_size=30,
)

# Valid field names (alphanumeric + underscore, starting with letter or _)
field_names_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=20,
).filter(lambda s: s[0].isalpha() or s[0] == "_")

# Type annotations that map to known JSON Schema types
type_annotations_st = st.sampled_from(
    ["str", "int", "float", "bool", "list", "dict", "list[str]", "list[int]"]
)

# Descriptions for fields (no control chars that would break JSON)
field_descriptions_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"), whitelist_characters=" "
    ),
    min_size=0,
    max_size=80,
)

# Tags for metadata
tag_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
)
tags_list_st = st.lists(tag_st, min_size=0, max_size=5, unique=True)

# First paragraph text (non-empty, no blank lines)
paragraph_line_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        whitelist_characters=" ",
    ),
    min_size=1,
    max_size=60,
).filter(lambda s: s.strip())

docstring_st = st.lists(paragraph_line_st, min_size=1, max_size=3).map(
    lambda lines: "\n".join(lines)
)


@st.composite
def fake_field_st(draw: st.DrawFn) -> FakeField:
    """Generate a fake config field."""
    name = draw(field_names_st)
    type_annotation = draw(type_annotations_st)
    required = draw(st.booleans())
    description = draw(field_descriptions_st)
    default = None if required else draw(st.text(min_size=1, max_size=20))
    return FakeField(
        name=name,
        type_annotation=type_annotation,
        required=required,
        description=description,
        default=default,
    )


@st.composite
def fake_fields_list_st(draw: st.DrawFn) -> list[FakeField]:
    """Generate a list of fake config fields with unique names."""
    fields = draw(st.lists(fake_field_st(), min_size=1, max_size=5))
    # Ensure unique names
    seen: set[str] = set()
    unique_fields: list[FakeField] = []
    for f in fields:
        if f.name not in seen:
            seen.add(f.name)
            unique_fields.append(f)
    assume(len(unique_fields) >= 1)
    return unique_fields


@st.composite
def fake_descriptor_st(draw: st.DrawFn) -> FakeDescriptor:
    """Generate a FakeDescriptor with fields and optional metadata."""
    name = draw(job_names_st)
    docstring = draw(docstring_st)
    fields = draw(fake_fields_list_st())
    tags = draw(tags_list_st)
    metadata = SimpleNamespace(
        extra_description=None,
        category=None,
        examples=None,
        tags=tags if tags else None,
        visibility=None,
    )
    return FakeDescriptor(
        name=name,
        docstring=docstring,
        config_fields=fields,
        declaration=metadata,
    )


@st.composite
def descriptor_list_st(draw: st.DrawFn) -> list[FakeDescriptor]:
    """Generate a list of unique-named FakeDescriptors."""
    descriptors = draw(st.lists(fake_descriptor_st(), min_size=1, max_size=5))
    # Ensure unique names
    seen: set[str] = set()
    unique: list[FakeDescriptor] = []
    for d in descriptors:
        if d.name not in seen:
            seen.add(d.name)
            unique.append(d)
    assume(len(unique) >= 1)
    return unique


# ===========================================================================
# Property 33: Schema export format correctness
# ===========================================================================


class TestSchemaExportJsonProperty:
    """Property 33 (JSON): export_json produces valid JSON array where each
    entry has name, description, and inputSchema fields.

    **Validates: Requirements 19.1**
    """

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_json_produces_valid_json(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of JobDescriptors, export_json SHALL produce valid JSON.

        **Validates: Requirements 19.1**
        """
        exporter = SchemaExporter()
        result = exporter.export_json(descriptors)

        # Must be valid JSON
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_json_array_length_matches_descriptors(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of N JobDescriptors, export_json SHALL produce a JSON
        array of exactly N entries.

        **Validates: Requirements 19.1**
        """
        exporter = SchemaExporter()
        result = exporter.export_json(descriptors)
        parsed = json.loads(result)

        assert len(parsed) == len(descriptors)

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_json_entries_have_required_mcp_fields(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of JobDescriptors, each entry in the JSON array SHALL
        have 'name', 'description', and 'inputSchema' fields.

        **Validates: Requirements 19.1**
        """
        exporter = SchemaExporter()
        result = exporter.export_json(descriptors)
        parsed = json.loads(result)

        for entry in parsed:
            assert "name" in entry, "MCP tool definition must have 'name'"
            assert "description" in entry, "MCP tool definition must have 'description'"
            assert "inputSchema" in entry, "MCP tool definition must have 'inputSchema'"

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_json_input_schema_is_valid_json_schema_object(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of JobDescriptors, each inputSchema SHALL be a valid
        JSON Schema object with type "object".

        **Validates: Requirements 19.1**
        """
        exporter = SchemaExporter()
        result = exporter.export_json(descriptors)
        parsed = json.loads(result)

        for entry in parsed:
            schema = entry["inputSchema"]
            assert isinstance(schema, dict)
            assert schema.get("type") == "object"
            assert "properties" in schema or schema.get("type") == "object"

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_json_names_match_descriptor_names(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of JobDescriptors, the names in the JSON array SHALL
        match the descriptor names in order.

        **Validates: Requirements 19.1**
        """
        exporter = SchemaExporter()
        result = exporter.export_json(descriptors)
        parsed = json.loads(result)

        for entry, desc in zip(parsed, descriptors, strict=False):
            assert entry["name"] == desc.name


class TestSchemaExportMarkdownProperty:
    """Property 33 (Markdown): export_markdown produces sections with
    parameter tables for each job.

    **Validates: Requirements 19.2**
    """

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_markdown_returns_tuple_per_descriptor(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of N JobDescriptors, export_markdown SHALL return
        exactly N (name, markdown) tuples.

        **Validates: Requirements 19.2**
        """
        exporter = SchemaExporter()
        result = exporter.export_markdown(descriptors)

        assert isinstance(result, list)
        assert len(result) == len(descriptors)
        for item in result:
            assert isinstance(item, tuple)
            assert len(item) == 2

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_markdown_names_match_descriptors(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of JobDescriptors, the name in each returned tuple
        SHALL match the corresponding descriptor name.

        **Validates: Requirements 19.2**
        """
        exporter = SchemaExporter()
        result = exporter.export_markdown(descriptors)

        for (name, _md), desc in zip(result, descriptors, strict=False):
            assert name == desc.name

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_markdown_contains_parameters_table(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any JobDescriptor with config_fields, the markdown output SHALL
        contain a parameters table with the standard header row.

        **Validates: Requirements 19.2**
        """
        exporter = SchemaExporter()
        result = exporter.export_markdown(descriptors)

        for (_name, md), desc in zip(result, descriptors, strict=False):
            if desc.config_fields:
                # Must have a parameters table header
                assert "| Name | Type | Required | Default | Description |" in md
                # Must have the separator row
                assert "|------|------|----------|---------|-------------|" in md

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_markdown_contains_heading_per_job(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any JobDescriptor, the markdown output SHALL contain a heading
        with the job name.

        **Validates: Requirements 19.2**
        """
        exporter = SchemaExporter()
        result = exporter.export_markdown(descriptors)

        for (_name, md), desc in zip(result, descriptors, strict=False):
            # Should have a heading with the job name
            assert f"# {desc.name}" in md

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_markdown_lists_all_field_names(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any JobDescriptor with config_fields, each field name SHALL
        appear in the markdown parameters table.

        **Validates: Requirements 19.2**
        """
        exporter = SchemaExporter()
        result = exporter.export_markdown(descriptors)

        for (_name, md), desc in zip(result, descriptors, strict=False):
            for f in desc.config_fields:
                assert f.name in md, f"Field '{f.name}' missing from markdown output"


class TestSchemaExportOpenAIProperty:
    """Property 33 (OpenAI): export_openai produces valid JSON matching
    OpenAI function calling format.

    **Validates: Requirements 19.3**
    """

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_openai_produces_valid_json(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of JobDescriptors, export_openai SHALL produce valid JSON.

        **Validates: Requirements 19.3**
        """
        exporter = SchemaExporter()
        result = exporter.export_openai(descriptors)

        parsed = json.loads(result)
        assert isinstance(parsed, list)

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_openai_array_length_matches_descriptors(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of N JobDescriptors, export_openai SHALL produce a
        JSON array of exactly N entries.

        **Validates: Requirements 19.3**
        """
        exporter = SchemaExporter()
        result = exporter.export_openai(descriptors)
        parsed = json.loads(result)

        assert len(parsed) == len(descriptors)

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_openai_entries_have_function_type(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of JobDescriptors, each OpenAI entry SHALL have
        type "function".

        **Validates: Requirements 19.3**
        """
        exporter = SchemaExporter()
        result = exporter.export_openai(descriptors)
        parsed = json.loads(result)

        for entry in parsed:
            assert entry.get("type") == "function"

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_openai_entries_have_function_object(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of JobDescriptors, each OpenAI entry SHALL have a
        'function' object with 'name', 'description', and 'parameters'.

        **Validates: Requirements 19.3**
        """
        exporter = SchemaExporter()
        result = exporter.export_openai(descriptors)
        parsed = json.loads(result)

        for entry in parsed:
            assert "function" in entry
            fn = entry["function"]
            assert "name" in fn, "OpenAI function must have 'name'"
            assert "description" in fn, "OpenAI function must have 'description'"
            assert "parameters" in fn, "OpenAI function must have 'parameters'"

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_openai_parameters_has_type_object(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of JobDescriptors, each OpenAI function's parameters
        SHALL have type "object".

        **Validates: Requirements 19.3**
        """
        exporter = SchemaExporter()
        result = exporter.export_openai(descriptors)
        parsed = json.loads(result)

        for entry in parsed:
            params = entry["function"]["parameters"]
            assert isinstance(params, dict)
            assert params.get("type") == "object"

    @given(descriptors=descriptor_list_st())
    @settings(max_examples=100)
    def test_export_openai_names_match_descriptor_names(
        self, descriptors: list[FakeDescriptor]
    ) -> None:
        """For any list of JobDescriptors, the function names in the OpenAI
        output SHALL match the descriptor names in order.

        **Validates: Requirements 19.3**
        """
        exporter = SchemaExporter()
        result = exporter.export_openai(descriptors)
        parsed = json.loads(result)

        for entry, desc in zip(parsed, descriptors, strict=False):
            assert entry["function"]["name"] == desc.name
