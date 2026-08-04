"""Property-based tests for PydanticAI ToolScope translation.

Tests Property 20 from the Phase 2–5 Domain SDKs design document.

Property 20: PydanticAI ToolScope translation preserves tool definitions —
For any list of ToolDef instances with callable functions, the ToolScopeTranslator
SHALL produce PydanticAI Tool objects that preserve the tool name, description,
and schema.

**Validates: Requirements 11.3**
"""

from __future__ import annotations

from typing import Any

from functualize_ai._types import ToolDef
from functualize_ai_pydantic._tool_translator import ToolScopeTranslator
from hypothesis import given, settings
from hypothesis import strategies as st

# ===========================================================================
# Strategies
# ===========================================================================

# Valid tool names (alphanumeric + underscore, must start with a letter)
tool_names_st = st.text(
    alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_"),
    min_size=1,
    max_size=30,
)

# Tool descriptions (non-empty strings)
tool_descriptions_st = st.text(min_size=1, max_size=200)

# JSON Schema property types
json_schema_types = st.sampled_from(["string", "integer", "number", "boolean"])


# Strategy for a valid JSON Schema parameters_schema
@st.composite
def parameters_schema_st(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a valid JSON Schema for tool parameters."""
    num_props = draw(st.integers(min_value=0, max_value=5))
    prop_names = draw(
        st.lists(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("L",), whitelist_characters="_"
                ),
                min_size=1,
                max_size=15,
            ),
            min_size=num_props,
            max_size=num_props,
            unique=True,
        )
    )
    properties: dict[str, Any] = {}
    for name in prop_names:
        prop_type = draw(json_schema_types)
        properties[name] = {"type": prop_type}

    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }


def _make_callable(name: str) -> Any:
    """Create a simple callable function with the given name."""

    def _fn(**kwargs: Any) -> str:
        return f"executed {name}"

    _fn.__name__ = name
    _fn.__qualname__ = name
    return _fn


@st.composite
def tool_def_with_function_st(draw: st.DrawFn) -> ToolDef:
    """Generate a ToolDef with a callable function."""
    name = draw(tool_names_st)
    description = draw(tool_descriptions_st)
    schema = draw(parameters_schema_st())
    fn = _make_callable(name)
    return ToolDef(
        name=name,
        description=description,
        parameters_schema=schema,
        job_name=name,
        function=fn,
        config_class=None,
    )


@st.composite
def tool_def_without_function_st(draw: st.DrawFn) -> ToolDef:
    """Generate a ToolDef without a callable function (function=None)."""
    name = draw(tool_names_st)
    description = draw(tool_descriptions_st)
    schema = draw(parameters_schema_st())
    return ToolDef(
        name=name,
        description=description,
        parameters_schema=schema,
        job_name=name,
        function=None,
        config_class=None,
    )


@st.composite
def tool_def_list_st(draw: st.DrawFn) -> list[ToolDef]:
    """Generate a list of ToolDef instances, some with functions and some without."""
    num_with_fn = draw(st.integers(min_value=1, max_value=8))
    num_without_fn = draw(st.integers(min_value=0, max_value=3))

    with_fn = draw(
        st.lists(
            tool_def_with_function_st(),
            min_size=num_with_fn,
            max_size=num_with_fn,
        )
    )
    without_fn = draw(
        st.lists(
            tool_def_without_function_st(),
            min_size=num_without_fn,
            max_size=num_without_fn,
        )
    )

    # Combine and shuffle
    all_defs = with_fn + without_fn
    # Draw a permutation
    indices = list(range(len(all_defs)))
    shuffled = draw(st.permutations(indices))
    return [all_defs[i] for i in shuffled]


# ===========================================================================
# Property 20: PydanticAI ToolScope translation preserves tool definitions
# ===========================================================================


class TestToolScopeTranslationProperty:
    """Property 20: PydanticAI ToolScope translation preserves tool definitions.

    For any list of ToolDef instances with callable functions, the
    ToolScopeTranslator SHALL produce PydanticAI Tool objects that preserve
    the tool name, description, and schema.

    **Validates: Requirements 11.3**
    """

    @given(tool_defs=st.lists(tool_def_with_function_st(), min_size=1, max_size=8))
    @settings(max_examples=100)
    def test_translated_tools_preserve_names(self, tool_defs: list[ToolDef]) -> None:
        """Each translated PydanticAI Tool has the same name as the source ToolDef.

        **Validates: Requirements 11.3**
        """
        translator = ToolScopeTranslator()
        tools = translator.translate(tool_defs)

        assert len(tools) == len(tool_defs)
        for tool_def, pydantic_tool in zip(tool_defs, tools, strict=False):
            assert pydantic_tool.name == tool_def.name

    @given(tool_defs=st.lists(tool_def_with_function_st(), min_size=1, max_size=8))
    @settings(max_examples=100)
    def test_translated_tools_preserve_descriptions(
        self, tool_defs: list[ToolDef]
    ) -> None:
        """Each translated PydanticAI Tool has the same description as the source ToolDef.

        **Validates: Requirements 11.3**
        """
        translator = ToolScopeTranslator()
        tools = translator.translate(tool_defs)

        assert len(tools) == len(tool_defs)
        for tool_def, pydantic_tool in zip(tool_defs, tools, strict=False):
            assert pydantic_tool.description == tool_def.description

    @given(tool_defs=st.lists(tool_def_with_function_st(), min_size=1, max_size=8))
    @settings(max_examples=100)
    def test_translated_tools_preserve_schema(self, tool_defs: list[ToolDef]) -> None:
        """Each translated PydanticAI Tool preserves the parameters schema from the ToolDef.

        **Validates: Requirements 11.3**
        """
        translator = ToolScopeTranslator()
        tools = translator.translate(tool_defs)

        assert len(tools) == len(tool_defs)
        for tool_def, pydantic_tool in zip(tool_defs, tools, strict=False):
            # The tool_def property on PydanticAI Tool contains the json schema
            pydantic_tool_def = pydantic_tool.tool_def
            # The schema should preserve properties and structure
            original_schema = tool_def.parameters_schema
            translated_schema = pydantic_tool_def.parameters_json_schema

            # The translator may add "type" and "additionalProperties" if missing,
            # but the original already has them in our test data
            assert translated_schema.get("properties") == original_schema.get(
                "properties"
            )
            assert translated_schema.get("type") == "object"

    @given(tool_defs=tool_def_list_st())
    @settings(max_examples=100)
    def test_tool_defs_without_functions_are_skipped(
        self, tool_defs: list[ToolDef]
    ) -> None:
        """ToolDefs without a function (function=None) are skipped by the translator.

        **Validates: Requirements 11.3**
        """
        translator = ToolScopeTranslator()
        tools = translator.translate(tool_defs)

        # Count how many have functions
        expected_count = sum(1 for td in tool_defs if td.function is not None)
        assert len(tools) == expected_count

    @given(tool_defs=st.lists(tool_def_with_function_st(), min_size=1, max_size=8))
    @settings(max_examples=100)
    def test_translated_tools_produce_one_tool_per_tooldef(
        self, tool_defs: list[ToolDef]
    ) -> None:
        """The translator produces exactly one PydanticAI Tool per ToolDef with a function.

        **Validates: Requirements 11.3**
        """
        translator = ToolScopeTranslator()
        tools = translator.translate(tool_defs)

        assert len(tools) == len(tool_defs)

    @given(tool_defs=st.lists(tool_def_with_function_st(), min_size=1, max_size=5))
    @settings(max_examples=100)
    def test_translated_tools_are_callable(self, tool_defs: list[ToolDef]) -> None:
        """Each translated PydanticAI Tool has a callable function attribute.

        **Validates: Requirements 11.3**
        """
        translator = ToolScopeTranslator()
        tools = translator.translate(tool_defs)

        for pydantic_tool in tools:
            assert callable(pydantic_tool.function)
