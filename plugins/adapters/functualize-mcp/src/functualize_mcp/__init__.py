"""Functualize MCP Plugin — exposes jobs as MCP tools via FastMCP.

Provides an MCP delivery adapter that translates functualize jobs into
MCP tools, allowing external AI agents (Goose, Claude, Cursor) to discover
and invoke jobs through the Model Context Protocol.
"""

from functualize_mcp._plugin import MCPAdapterPlugin

__all__ = [
    "AI_OUTBOUND_PRESET_NAME",
    "AI_OUTBOUND_PRESET_STRATEGIES",
    "AI_OUTBOUND_STRATEGY_NAME",
    "AIOutboundGateResolver",
    "MCPAdapterPlugin",
    "MCPConfig",
    "MCPHistoryToolRegistry",
    "MCPManagementToolRegistry",
    "MCPServer",
    "MCPTaskToolRegistry",
    "MCPToolRegistry",
    "JobToolTranslator",
    "MCPToolDef",
    "SchemaExporter",
    "ServerInfo",
    "ServerManager",
    "WorkflowToolProvider",
    "register_ai_outbound_gate_strategy",
]


# Lazy loading for heavy symbols (PEP 562)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "MCPConfig": ("functualize_mcp._config", "MCPConfig"),
    "AI_OUTBOUND_PRESET_NAME": (
        "functualize_mcp._gate_strategy",
        "AI_OUTBOUND_PRESET_NAME",
    ),
    "AI_OUTBOUND_PRESET_STRATEGIES": (
        "functualize_mcp._gate_strategy",
        "AI_OUTBOUND_PRESET_STRATEGIES",
    ),
    "AI_OUTBOUND_STRATEGY_NAME": (
        "functualize_mcp._gate_strategy",
        "AI_OUTBOUND_STRATEGY_NAME",
    ),
    "AIOutboundGateResolver": (
        "functualize_mcp._gate_strategy",
        "AIOutboundGateResolver",
    ),
    "register_ai_outbound_gate_strategy": (
        "functualize_mcp._gate_strategy",
        "register_ai_outbound_gate_strategy",
    ),
    "MCPHistoryToolRegistry": (
        "functualize_mcp._history_tools",
        "MCPHistoryToolRegistry",
    ),
    "MCPManagementToolRegistry": (
        "functualize_mcp._management_tools",
        "MCPManagementToolRegistry",
    ),
    "SchemaExporter": ("functualize_mcp._schema_export", "SchemaExporter"),
    "MCPServer": ("functualize_mcp._server", "MCPServer"),
    "ServerInfo": ("functualize_mcp._server_manager", "ServerInfo"),
    "ServerManager": ("functualize_mcp._server_manager", "ServerManager"),
    "MCPTaskToolRegistry": ("functualize_mcp._task_tools", "MCPTaskToolRegistry"),
    "MCPToolRegistry": ("functualize_mcp._tools", "MCPToolRegistry"),
    "JobToolTranslator": ("functualize_mcp._translator", "JobToolTranslator"),
    "MCPToolDef": ("functualize_mcp._translator", "MCPToolDef"),
    "WorkflowToolProvider": ("functualize_mcp._workflow_tools", "WorkflowToolProvider"),
}


def __getattr__(name: str):
    """Lazy-load heavy symbols on first access (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        # Cache it on the module for subsequent fast access
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
