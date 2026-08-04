"""MCP Server — FastMCP wrapper for functualize.

Wraps FastMCP server with functualize job discovery and tool registration.
Supports both stdio and HTTP+SSE transports.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

from functualize_mcp._history_tools import MCPHistoryToolRegistry
from functualize_mcp._management_tools import MCPManagementToolRegistry
from functualize_mcp._task_tools import MCPTaskToolRegistry
from functualize_mcp._tools import MCPToolRegistry
from functualize_mcp._translator import (
    JobToolTranslator,
    MCPToolDef,
    read_cached_group_options,
)
from functualize_mcp._workflow_tools import GateToolPolicy, WorkflowToolProvider

if TYPE_CHECKING:
    from functualize_mcp._config import MCPConfig

__all__ = ["MCPServer"]

logger = logging.getLogger(__name__)

# Mapping from JSON Schema type strings to Python type annotations
_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


class MCPServer:
    """Wraps FastMCP server with functualize job discovery.

    Translates registered functualize jobs into MCP tools and serves
    them via the configured transport (stdio or HTTP+SSE).

    Args:
        app: The FunctualizeApp instance providing job registry and DI.
        config: MCPConfig controlling transport, filtering, and features.
    """

    def __init__(self, app: Any, *, config: MCPConfig) -> None:
        self._app = app
        self._config = config
        self._translator = JobToolTranslator(read_cached_group_options())
        self._gate_tool_policy = GateToolPolicy(app)
        self._tool_registry = MCPToolRegistry(
            app, config=config, gate_policy=self._gate_tool_policy
        )
        self._task_tool_registry = MCPTaskToolRegistry(app)
        self._history_tool_registry = MCPHistoryToolRegistry(app)
        self._management_tool_registry = MCPManagementToolRegistry(config)
        self._workflow_tool_provider = WorkflowToolProvider(app)
        self._mcp = FastMCP(
            name="functualize-mcp",
            instructions="Functualize MCP server — exposes functualize jobs as tools.",
        )
        self._tools_registered = False

    def _register_tools(self) -> None:
        """Discover jobs from the app and register them as MCP tools.

        Uses the JobToolTranslator to convert JobDescriptors into MCP tool
        definitions, then registers callable wrappers with FastMCP.
        Also registers the core management tools (discover_jobs, get_job_schema,
        run_job, run_job_async, get_execution_status).
        """
        if self._tools_registered:
            return

        # Register core MCP tools first
        self._tool_registry.register_tools(self._mcp)

        # Register domain-specific tools (conditionally)
        self._task_tool_registry.register_tools(self._mcp)
        self._history_tool_registry.register_tools(self._mcp)

        # Register management meta-tools (conditionally, when enable_management=True)
        self._management_tool_registry.register_tools(self._mcp)

        # Workflow inspection and gate resume. Unconditional: these read the
        # state store, so they work for any workflow scope regardless of
        # which gate strategy produced it.
        self._workflow_tool_provider.register_tools(self._mcp)

        # Register per-job tools
        descriptors = self._app.get_jobs()
        tool_defs = self._translator.translate_all(descriptors, self._config)

        for tool_def in tool_defs:
            self._register_single_tool(tool_def)

        self._tools_registered = True
        logger.info(
            "MCPServer: Registered %d per-job tools + 5 core tools from %d discovered jobs",
            len(tool_defs),
            len(descriptors),
        )

    def _register_single_tool(self, tool_def: MCPToolDef) -> None:
        """Register a single job as an MCP tool with FastMCP.

        Dynamically creates a typed function matching the tool's input schema
        and registers it with FastMCP. The function executes the job via
        the app's execute method.

        Args:
            tool_def: The MCPToolDef with name, description, and schema.
        """
        job_name = tool_def.name
        app = self._app
        fn = _build_tool_function(job_name, tool_def, app, self._gate_tool_policy)
        self._mcp.add_tool(fn)

    def start_stdio(self) -> None:
        """Start the MCP server using stdio transport.

        This is the default transport for ``func mcp serve``.
        Registers all discovered job tools and runs the FastMCP server
        in stdio mode, reading from stdin and writing to stdout.
        """
        self._register_tools()
        logger.info("MCPServer: Starting stdio transport")
        self._mcp.run(transport="stdio")

    def start_http(self, host: str, port: int) -> None:
        """Start the MCP server using HTTP+SSE transport.

        Used when ``func mcp serve --http --port P`` is specified.
        Registers all discovered job tools and runs the FastMCP server
        in SSE mode on the specified host and port.

        Args:
            host: Bind address for the HTTP server.
            port: Port number for the HTTP server (1024-65535).
        """
        self._register_tools()
        logger.info("MCPServer: Starting HTTP+SSE transport on %s:%d", host, port)
        self._mcp.run(transport="sse", host=host, port=port)


def _build_tool_function(
    job_name: str, tool_def: MCPToolDef, app: Any, policy: Any = None
) -> Any:
    """Build a dynamically-typed async function for a job tool.

    Creates a function whose signature matches the tool's input schema,
    allowing FastMCP to expose properly typed parameters to MCP clients.
    Jobs with no parameters get a no-argument function.

    Args:
        job_name: The functualize job name.
        tool_def: The MCPToolDef containing the input schema.
        app: The FunctualizeApp for executing jobs.

    Returns:
        An async callable suitable for FastMCP.add_tool().
    """
    schema = tool_def.input_schema
    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    if not properties:
        # No parameters — simple wrapper
        async def _no_params_handler() -> dict:
            return _execute_job(app, job_name, {}, policy)

        _no_params_handler.__name__ = job_name
        _no_params_handler.__qualname__ = job_name
        _no_params_handler.__doc__ = (
            tool_def.description or f"Execute the {job_name} job."
        )
        return _no_params_handler

    # Build typed parameters for the function
    param_parts: list[str] = []
    for field_name, field_schema in properties.items():
        py_type = _TYPE_MAP.get(field_schema.get("type", ""), "Any")
        if field_name in required_fields:
            param_parts.append(f"{field_name}: {py_type}")
        else:
            default_val = repr(field_schema.get("default"))
            param_parts.append(f"{field_name}: {py_type} = {default_val}")

    params_str = ", ".join(param_parts)

    # Build the function source
    # We use exec to create a function with the exact signature FastMCP expects
    fn_source = (
        f"async def {job_name}({params_str}) -> dict:\n"
        f"    '''{tool_def.description or f'Execute the {job_name} job.'}'''\n"
        f"    import inspect as _inspect\n"
        f"    _frame = _inspect.currentframe()\n"
        f"    _kwargs = {{k: v for k, v in _frame.f_locals.items() if not k.startswith('_')}}\n"
        f"    return _execute(_app, _job_name, _kwargs, _policy, _group_names)\n"
    )

    # Execution namespace with closure references
    exec_ns: dict[str, Any] = {
        "_app": app,
        "_job_name": job_name,
        "_policy": policy,
        "_group_names": tool_def.group_option_names,
        "_execute": _execute_job,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "Any": Any,
    }

    exec(fn_source, exec_ns)  # noqa: S102
    return exec_ns[job_name]


def _execute_job(
    app: Any,
    job_name: str,
    kwargs: dict[str, Any],
    policy: Any = None,
    group_option_names: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Execute a functualize job and return a structured result dict.

    Every per-job MCP tool funnels through here, which is why the gate tool
    permission is enforced at this point: it is the one place a job-executing
    call cannot get past, so there is no version of the check a caller can
    forget to make.

    Args:
        app: The FunctualizeApp instance.
        job_name: Name of the job to execute.
        kwargs: Arguments to pass to the job.
        policy: GateToolPolicy governing which jobs may run while a workflow
            gate waits. None disables enforcement (used by direct callers that
            have no workflow state to consult).
        group_option_names: Which ``kwargs`` keys are the job's inherited
            group options (S6a) rather than its own parameters. They are split
            off here because they are not arguments of the job function —
            passing one through would fail argument validation.

    Returns:
        Dict with status, return_value, and duration_ms on success, or an
        error envelope — ``tool_not_permitted`` when a gate forbids the call,
        otherwise the raised error.
    """
    if policy is not None and not policy.permitted(job_name):
        logger.info(
            "MCPServer: refused '%s' — not permitted by a waiting gate", job_name
        )
        refusal: dict[str, Any] = policy.refusal(job_name)
        return refusal

    group_values = {k: v for k, v in kwargs.items() if k in group_option_names}
    job_kwargs = {k: v for k, v in kwargs.items() if k not in group_option_names}

    try:
        result = app.execute(
            job_name, group_option_values=group_values or None, **job_kwargs
        )
        return {
            "status": result.status,
            "return_value": result.return_value,
            "duration_ms": result.duration_ms,
        }
    except Exception as e:
        logger.error("MCPServer: Error executing job '%s': %s", job_name, e)
        return {"error": str(e), "job_name": job_name}
