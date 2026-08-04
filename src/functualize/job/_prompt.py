"""Prompt capability — re-exported for the ``functualize.job`` public API.

The Prompt capability lives in ``functualize._engine.capabilities.prompt``
and its supporting types in ``functualize._types.interactivity``. This module
re-exports them so job authors keep importing from ``functualize.job``.
"""

from functualize._engine.capabilities.prompt import Prompt
from functualize._types.interactivity import (
    PromptChoice,
    PromptRequest,
    PromptResponse,
)

__all__ = [
    "Prompt",
    "PromptChoice",
    "PromptRequest",
    "PromptResponse",
]
