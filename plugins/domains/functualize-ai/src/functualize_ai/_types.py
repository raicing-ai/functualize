"""Shared types for the AI Domain SDK."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TokenUsage:
    """Token usage statistics for an AI call."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float | None = None


@dataclass(frozen=True)
class ToolCallRecord:
    """A record of a single tool call made during an AI run."""

    tool_name: str
    args: dict[str, Any]
    result: Any
    duration_ms: float


@dataclass(frozen=True)
class AIResult:
    """The result of an AI run, containing output, tool calls, usage, and duration."""

    output: Any
    tool_calls: list[ToolCallRecord]
    usage: TokenUsage
    duration_ms: float


@dataclass(frozen=True)
class AILimits:
    """Budget and constraint caps for AI calls."""

    max_tool_calls: int | None = None
    max_tokens: int | None = None
    budget_usd: float | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class ToolDef:
    """A provider-agnostic abstract tool definition."""

    name: str
    description: str
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    job_name: str | None = None
    function: Callable[..., Any] | None = None
    config_class: type | None = None
