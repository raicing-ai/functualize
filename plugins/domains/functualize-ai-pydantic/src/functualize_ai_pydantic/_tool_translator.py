"""ToolScope Translator — Converts ToolDefs to PydanticAI native toolsets.

Translates the provider-agnostic ToolDef instances produced by
ToolScope.to_tool_defs() into PydanticAI's native Tool format using
Tool.from_schema() for dynamic tool definitions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai import Tool

if TYPE_CHECKING:
    from functualize_ai._types import ToolDef

__all__ = ["ToolScopeTranslator"]


class ToolScopeTranslator:
    """Translates ToolScope.to_tool_defs() output to PydanticAI native format.

    Converts functualize's provider-agnostic ToolDef instances into
    PydanticAI Tool objects using Tool.from_schema() for use with the
    PydanticAI agent.
    """

    def translate(self, tool_defs: list[ToolDef]) -> list[Tool[Any]]:
        """Translate a list of ToolDef instances into PydanticAI Tool objects.

        Each ToolDef is converted into a PydanticAI Tool using Tool.from_schema(),
        which allows specifying a custom name, description, and JSON schema
        independently of the function signature.

        Args:
            tool_defs: The list of provider-agnostic ToolDef instances to translate.

        Returns:
            A list of PydanticAI Tool objects ready for use with an Agent.
        """
        tools: list[Tool[Any]] = []
        for tool_def in tool_defs:
            pydantic_tool = self._translate_single(tool_def)
            if pydantic_tool is not None:
                tools.append(pydantic_tool)
        return tools

    def _translate_single(self, tool_def: ToolDef) -> Tool[Any] | None:
        """Translate a single ToolDef into a PydanticAI Tool.

        Uses Tool.from_schema() to create a tool with a custom schema that
        matches the functualize ToolDef's parameters_schema.

        Args:
            tool_def: The ToolDef to translate.

        Returns:
            A PydanticAI Tool, or None if no callable function is available.
        """
        if tool_def.function is None:
            return None

        # Build JSON schema for Tool.from_schema
        # ToolDef.parameters_schema is a JSON Schema dict describing the tool params
        json_schema = tool_def.parameters_schema or {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

        # Ensure the schema has required top-level keys
        if "type" not in json_schema:
            json_schema = {"type": "object", **json_schema}
        if "additionalProperties" not in json_schema:
            json_schema = {**json_schema, "additionalProperties": False}

        # Create a wrapper function that receives **kwargs and calls the
        # original function. Tool.from_schema passes args as keyword arguments.
        original_fn = tool_def.function

        def _wrapper(**kwargs: Any) -> Any:
            return original_fn(**kwargs)

        # Give the wrapper a useful name for debugging
        _wrapper.__name__ = tool_def.name
        _wrapper.__qualname__ = tool_def.name

        return Tool.from_schema(
            function=_wrapper,
            name=tool_def.name,
            description=tool_def.description or None,
            json_schema=json_schema,
            takes_ctx=False,
        )
