"""Gate strategy enum definitions.

Defines the named strategies available for resolving gate inputs
when a workflow step pauses for input.
"""

from __future__ import annotations

from enum import StrEnum


class GateStrategy(StrEnum):
    """Named strategies for resolving gate inputs."""

    RESOLVE = "resolve"  # Resolve from config chain only
    PROMPT = "prompt"  # Collect via interactive InputProvider
    AI_INBOUND = "ai_inbound"  # Resolve via AI/LLM generation
