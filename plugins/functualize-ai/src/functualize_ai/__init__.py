"""functualize-ai — AI Domain SDK.

Provides the AI capability class, AIProvider protocol, ToolScope builder,
shared types, configuration, errors, event constants, gate strategy,
and testing doubles for LLM interaction capabilities.

Uses lazy imports via __getattr__ to avoid loading heavy dependencies
(pydantic, importlib.metadata) until first attribute access. This keeps
domain metadata discovery fast (~5ms instead of ~360ms).
"""

from __future__ import annotations

# Only domain_metadata is loaded eagerly (needed for entry point discovery)
from functualize_ai._metadata import domain_metadata

__all__ = [
    # Capability Class
    "AI",
    # Protocol
    "AIProvider",
    # ToolScope
    "ToolScope",
    # Types
    "AIResult",
    "TokenUsage",
    "ToolDef",
    "AILimits",
    "ToolCallRecord",
    # Config
    "AIConfig",
    # Errors
    "AINotAvailableError",
    "BudgetExceededError",
    "ToolNotPermittedError",
    # Event Constants
    "AI_CALL_STARTED",
    "AI_CALL_COMPLETED",
    "AI_CALL_FAILED",
    "AI_BUDGET_EXCEEDED",
    "AI_TOOL_CALLED",
    # Gate Strategy
    "AI_INBOUND_STRATEGY_NAME",
    "AI_INBOUND_PRESET_NAME",
    "AI_INBOUND_PRESET_STRATEGIES",
    "AI_PRESET_NAME",
    "AI_PRESET_STRATEGIES",
    "AIInboundGateResolver",
    "register_ai_inbound_gate_strategy",
    # State Fallback
    "EphemeralStateBackend",
    "StrictStateBackendWrapper",
    "resolve_ai_state_backend",
    # Provider Discovery
    "discover_ai_providers",
    "select_ai_provider",
    "resolve_ai_provider",
    # Metadata
    "domain_metadata",
]

# Lazy import mapping: attribute name → (module, name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # _ai
    "AI": ("functualize_ai._ai", "AI"),
    # _config
    "AIConfig": ("functualize_ai._config", "AIConfig"),
    # _errors
    "AINotAvailableError": ("functualize_ai._errors", "AINotAvailableError"),
    "BudgetExceededError": ("functualize_ai._errors", "BudgetExceededError"),
    "ToolNotPermittedError": ("functualize_ai._errors", "ToolNotPermittedError"),
    # _events
    "AI_BUDGET_EXCEEDED": ("functualize_ai._events", "AI_BUDGET_EXCEEDED"),
    "AI_CALL_COMPLETED": ("functualize_ai._events", "AI_CALL_COMPLETED"),
    "AI_CALL_FAILED": ("functualize_ai._events", "AI_CALL_FAILED"),
    "AI_CALL_STARTED": ("functualize_ai._events", "AI_CALL_STARTED"),
    "AI_TOOL_CALLED": ("functualize_ai._events", "AI_TOOL_CALLED"),
    # _gate_strategy
    "AI_INBOUND_PRESET_NAME": (
        "functualize_ai._gate_strategy",
        "AI_INBOUND_PRESET_NAME",
    ),
    "AI_INBOUND_PRESET_STRATEGIES": (
        "functualize_ai._gate_strategy",
        "AI_INBOUND_PRESET_STRATEGIES",
    ),
    "AI_INBOUND_STRATEGY_NAME": (
        "functualize_ai._gate_strategy",
        "AI_INBOUND_STRATEGY_NAME",
    ),
    "AI_PRESET_NAME": ("functualize_ai._gate_strategy", "AI_PRESET_NAME"),
    "AI_PRESET_STRATEGIES": ("functualize_ai._gate_strategy", "AI_PRESET_STRATEGIES"),
    "AIInboundGateResolver": (
        "functualize_ai._gate_strategy",
        "AIInboundGateResolver",
    ),
    "register_ai_inbound_gate_strategy": (
        "functualize_ai._gate_strategy",
        "register_ai_inbound_gate_strategy",
    ),
    # _protocols
    "AIProvider": ("functualize_ai._protocols", "AIProvider"),
    # _provider_discovery
    "discover_ai_providers": (
        "functualize_ai._provider_discovery",
        "discover_ai_providers",
    ),
    "resolve_ai_provider": (
        "functualize_ai._provider_discovery",
        "resolve_ai_provider",
    ),
    "select_ai_provider": (
        "functualize_ai._provider_discovery",
        "select_ai_provider",
    ),
    # _state_fallback
    "EphemeralStateBackend": (
        "functualize_ai._state_fallback",
        "EphemeralStateBackend",
    ),
    "StrictStateBackendWrapper": (
        "functualize_ai._state_fallback",
        "StrictStateBackendWrapper",
    ),
    "resolve_ai_state_backend": (
        "functualize_ai._state_fallback",
        "resolve_ai_state_backend",
    ),
    # _tool_scope
    "ToolScope": ("functualize_ai._tool_scope", "ToolScope"),
    # _types
    "AILimits": ("functualize_ai._types", "AILimits"),
    "AIResult": ("functualize_ai._types", "AIResult"),
    "TokenUsage": ("functualize_ai._types", "TokenUsage"),
    "ToolCallRecord": ("functualize_ai._types", "ToolCallRecord"),
    "ToolDef": ("functualize_ai._types", "ToolDef"),
}


def __getattr__(name: str) -> object:
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        # Cache in module globals to avoid repeated __getattr__ calls
        globals()[name] = value
        return value
    raise AttributeError(f"module 'functualize_ai' has no attribute {name!r}")
