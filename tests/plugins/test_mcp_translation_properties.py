"""Property-based tests for MCP Job→Tool translation.

Tests Property 29 from the Phase 2–5 Domain SDKs design document.

Property 29: MCP Job→Tool translation preserves descriptor information —
For any JobDescriptor with a multi-paragraph docstring, config model fields,
and tags: the translated MCP tool SHALL have `description` equal to the first
paragraph of the docstring, `inputSchema` matching the config model's JSON Schema,
and annotations containing all tags.

**Validates: Requirements 17.1, 17.2, 17.3**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from functualize_mcp._translator import JobToolTranslator
from hypothesis import assume, given
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

# Valid field names (alphanumeric + underscore)
field_names_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=20,
).filter(lambda s: s[0].isalpha() or s[0] == "_")

# Type annotations that map to known JSON Schema types
type_annotations_st = st.sampled_from(
    ["str", "int", "float", "bool", "list", "dict", "list[str]", "list[int]"]
)

# Descriptions for fields
field_descriptions_st = st.text(min_size=0, max_size=100)

# Tags for metadata
tag_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
)
tags_list_st = st.lists(tag_st, min_size=1, max_size=5, unique=True)

# First paragraph text (non-empty, no blank lines)
paragraph_line_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        whitelist_characters=" ",
    ),
    min_size=1,
    max_size=80,
).filter(lambda s: s.strip())

first_paragraph_st = st.lists(paragraph_line_st, min_size=1, max_size=3).map(
    lambda lines: "\n".join(lines)
)

# Second paragraph text (optional, to make multi-paragraph docstrings)
second_paragraph_st = st.lists(paragraph_line_st, min_size=1, max_size=3).map(
    lambda lines: "\n".join(lines)
)


@st.composite
def multi_paragraph_docstring_st(draw: st.DrawFn) -> str:
    """Generate a multi-paragraph docstring with at least two paragraphs."""
    first = draw(first_paragraph_st)
    second = draw(second_paragraph_st)
    return f"{first}\n\n{second}"


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
    fields = draw(st.lists(fake_field_st(), min_size=1, max_size=6))
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
def descriptor_with_docstring_st(draw: st.DrawFn) -> FakeDescriptor:
    """Generate a FakeDescriptor with a multi-paragraph docstring."""
    name = draw(job_names_st)
    docstring = draw(multi_paragraph_docstring_st())
    return FakeDescriptor(name=name, docstring=docstring)


@st.composite
def descriptor_with_fields_st(draw: st.DrawFn) -> FakeDescriptor:
    """Generate a FakeDescriptor with config_fields."""
    name = draw(job_names_st)
    fields = draw(fake_fields_list_st())
    return FakeDescriptor(name=name, config_fields=fields)


@st.composite
def descriptor_with_tags_st(draw: st.DrawFn) -> FakeDescriptor:
    """Generate a FakeDescriptor with tags in metadata."""
    name = draw(job_names_st)
    tags = draw(tags_list_st)
    metadata = SimpleNamespace(
        extra_description=None,
        category=None,
        examples=None,
        tags=tags,
        visibility=None,
    )
    return FakeDescriptor(name=name, declaration=metadata)


@st.composite
def full_descriptor_st(draw: st.DrawFn) -> FakeDescriptor:
    """Generate a full FakeDescriptor with docstring, fields, and tags."""
    name = draw(job_names_st)
    docstring = draw(multi_paragraph_docstring_st())
    fields = draw(fake_fields_list_st())
    tags = draw(tags_list_st)
    metadata = SimpleNamespace(
        extra_description=None,
        category=None,
        examples=None,
        tags=tags,
        visibility=None,
    )
    return FakeDescriptor(
        name=name,
        docstring=docstring,
        config_fields=fields,
        declaration=metadata,
    )


# ===========================================================================
# Property 29: MCP Job→Tool translation preserves descriptor information
# ===========================================================================


class TestMCPJobToolTranslationProperty:
    """Property 29: MCP Job→Tool translation preserves descriptor information.

    For any JobDescriptor with a multi-paragraph docstring, config model fields,
    and tags: the translated MCP tool SHALL have `description` equal to the first
    paragraph of the docstring, `inputSchema` matching the config model's JSON Schema,
    and annotations containing all tags.

    **Validates: Requirements 17.1, 17.2, 17.3**
    """

    @given(descriptor=descriptor_with_docstring_st())
    def test_description_contains_first_paragraph_only(
        self, descriptor: FakeDescriptor
    ) -> None:
        """For any JobDescriptor with a docstring, the translated MCPToolDef.description
        contains the first paragraph.

        **Validates: Requirements 17.1**
        """
        translator = JobToolTranslator()
        result = translator.translate(descriptor)

        # Extract the expected first paragraph by splitting on blank lines
        paragraphs = descriptor.docstring.strip().split("\n\n")
        first_paragraph_lines = paragraphs[0].strip().splitlines()
        expected_words = " ".join(
            line.strip() for line in first_paragraph_lines if line.strip()
        )

        assert result.description == expected_words

    @given(descriptor=descriptor_with_docstring_st())
    def test_description_length_bounded_by_first_paragraph(
        self, descriptor: FakeDescriptor
    ) -> None:
        """For any JobDescriptor with a multi-paragraph docstring, the translated
        MCPToolDef.description length is bounded by the first paragraph content only.

        **Validates: Requirements 17.1**
        """
        translator = JobToolTranslator()
        result = translator.translate(descriptor)

        # The first paragraph joined as single line should exactly equal the description
        paragraphs = descriptor.docstring.strip().split("\n\n")
        first_paragraph_lines = paragraphs[0].strip().splitlines()
        first_paragraph_joined = " ".join(
            line.strip() for line in first_paragraph_lines if line.strip()
        )

        # Description equals exactly the first paragraph (not longer)
        assert result.description == first_paragraph_joined
        # If multi-paragraph, full docstring is longer than just the description
        if len(paragraphs) > 1:
            full_joined = " ".join(
                line.strip()
                for line in descriptor.docstring.strip().splitlines()
                if line.strip()
            )
            assert len(result.description) <= len(full_joined)

    @given(descriptor=descriptor_with_fields_st())
    def test_input_schema_contains_property_for_each_field(
        self, descriptor: FakeDescriptor
    ) -> None:
        """For any JobDescriptor with config_fields, the MCPToolDef.input_schema
        contains a JSON Schema property for each field.

        **Validates: Requirements 17.2**
        """
        translator = JobToolTranslator()
        result = translator.translate(descriptor)

        schema = result.input_schema
        assert schema["type"] == "object"
        assert "properties" in schema

        # Every config field should have a corresponding property in the schema
        for f in descriptor.config_fields:
            assert f.name in schema["properties"], (
                f"Field '{f.name}' missing from input_schema properties"
            )

    @given(descriptor=descriptor_with_fields_st())
    def test_input_schema_required_fields_match(
        self, descriptor: FakeDescriptor
    ) -> None:
        """For any JobDescriptor with config_fields, the MCPToolDef.input_schema
        'required' array contains exactly the required field names.

        **Validates: Requirements 17.2**
        """
        translator = JobToolTranslator()
        result = translator.translate(descriptor)

        schema = result.input_schema
        expected_required = [f.name for f in descriptor.config_fields if f.required]
        actual_required = schema.get("required", [])

        assert set(actual_required) == set(expected_required)

    @given(descriptor=descriptor_with_fields_st())
    def test_input_schema_field_types_are_valid_json_schema(
        self, descriptor: FakeDescriptor
    ) -> None:
        """For any JobDescriptor with config_fields, each property in the
        input_schema has a valid JSON Schema type.

        **Validates: Requirements 17.2**
        """
        valid_types = {"string", "integer", "number", "boolean", "array", "object"}
        translator = JobToolTranslator()
        result = translator.translate(descriptor)

        schema = result.input_schema
        for f in descriptor.config_fields:
            prop = schema["properties"][f.name]
            assert prop["type"] in valid_types, (
                f"Field '{f.name}' has invalid JSON Schema type: {prop['type']}"
            )

    @given(descriptor=descriptor_with_fields_st())
    def test_input_schema_preserves_field_descriptions(
        self, descriptor: FakeDescriptor
    ) -> None:
        """For any JobDescriptor with config_fields that have descriptions,
        the input_schema properties preserve those descriptions.

        **Validates: Requirements 17.2**
        """
        translator = JobToolTranslator()
        result = translator.translate(descriptor)

        schema = result.input_schema
        for f in descriptor.config_fields:
            prop = schema["properties"][f.name]
            if f.description:
                assert prop.get("description") == f.description

    @given(descriptor=descriptor_with_tags_st())
    def test_annotations_contain_all_tags(self, descriptor: FakeDescriptor) -> None:
        """For any JobDescriptor with tags in metadata, the MCPToolDef.annotations
        contain those tags.

        **Validates: Requirements 17.3**
        """
        translator = JobToolTranslator()
        result = translator.translate(descriptor)

        expected_tags = list(descriptor.declaration.tags)
        assert "tags" in result.annotations
        assert result.annotations["tags"] == expected_tags

    @given(descriptor=full_descriptor_st())
    def test_full_translation_preserves_all_descriptor_information(
        self, descriptor: FakeDescriptor
    ) -> None:
        """For any complete JobDescriptor (docstring + fields + tags), the translation
        preserves description from first paragraph, all field schemas, and all tags.

        **Validates: Requirements 17.1, 17.2, 17.3**
        """
        translator = JobToolTranslator()
        result = translator.translate(descriptor)

        # 1. Description is first paragraph of docstring
        paragraphs = descriptor.docstring.strip().split("\n\n")
        first_paragraph_lines = paragraphs[0].strip().splitlines()
        expected_desc = " ".join(
            line.strip() for line in first_paragraph_lines if line.strip()
        )
        assert result.description == expected_desc

        # 2. Input schema has a property for each field
        for f in descriptor.config_fields:
            assert f.name in result.input_schema["properties"]

        # 3. Annotations contain all tags
        expected_tags = list(descriptor.declaration.tags)
        assert result.annotations["tags"] == expected_tags
