"""functualize-ai-pydantic — PydanticAI-backed AI implementation plugin.

Provides a full-featured AI implementation backed by PydanticAI and LiteLLM,
supporting tool calling, streaming, structured output, and multi-model access.

Registered via entry point `functualize.ai_providers` with name "pydantic".
"""

from functualize_ai_pydantic._plugin import PydanticAIPlugin
from functualize_ai_pydantic._provider import PydanticAIProvider
from functualize_ai_pydantic._pydantic_ai import PydanticAI
from functualize_ai_pydantic._tool_translator import ToolScopeTranslator

__all__ = [
    "PydanticAI",
    "PydanticAIPlugin",
    "PydanticAIProvider",
    "ToolScopeTranslator",
]
