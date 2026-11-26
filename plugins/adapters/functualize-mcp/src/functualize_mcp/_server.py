"""MCP Server — FastMCP wrapper for functualize.

Wraps FastMCP server with functualize job discovery and tool registration.
Supports both stdio and HTTP+SSE transports.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import fastmcp
from fastmcp import FastMCP
from fastmcp.tools import Tool, ToolResult
from pydantic import PrivateAttr

from functualize._types.errors import ScopeCancelledError
from functualize.types import RunRequest
from functualize_mcp._history_tools import MCPHistoryToolRegistry
from functualize_mcp._management_tools import MCPManagementToolRegistry
from functualize_mcp._task_tools import MCPTaskToolRegistry
from functualize_mcp._tools import MCPToolRegistry, wire_metadata, wire_status
from functualize_mcp._translator import (
    JobToolTranslator,
    MCPToolDef,
    read_cached_group_options,
)
from functualize_mcp._workflow_tools import GateToolPolicy, WorkflowToolProvider

if TYPE_CHECKING:
    from functualize.plugin import PluginHost
    from functualize_mcp._config import MCPConfig

__all__ = ["JobTool", "MCPServer"]

logger = logging.getLogger(__name__)


class MCPServer:
    """Wraps FastMCP server with functualize job discovery.

    Translates registered functualize jobs into MCP tools and serves
    them via the configured transport (stdio or HTTP+SSE).

    Args:
        app: The FunctualizeApp instance providing job registry and DI.
        config: MCPConfig controlling transport, filtering, and features.
    """

    def __init__(self, app: PluginHost, *, config: MCPConfig) -> None:
        # functualize owns this server process: every boot is a tool-serving
        # automation event, and FastMCP's default update check would fire a
        # PyPI request (egress) plus an ASCII banner on each one. Default to
        # both off, but never override an explicit operator setting — the
        # documented FASTMCP_* env vars win when present.
        if "FASTMCP_CHECK_FOR_UPDATES" not in os.environ:
            fastmcp.settings.check_for_updates = "off"
        if "FASTMCP_SHOW_SERVER_BANNER" not in os.environ:
            fastmcp.settings.show_server_banner = False

        self._app = app
        self._config = config
        self._translator = JobToolTranslator(read_cached_group_options(app))
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

        The tool's parameters are the job's published schema; a call executes
        the job through the app (``JobTool.run``).

        Args:
            tool_def: The MCPToolDef with name, description, and schema.
        """
        self._mcp.add_tool(JobTool.for_job(tool_def, self._app, self._gate_tool_policy))

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


class JobTool(Tool):
    """One job as an MCP tool, registered from its one schema (contracts.md §6).

    ``parameters`` is the translator's ``input_schema`` — ``job_input_schema``
    with the group options merged — so the tool advertises exactly what
    ``func builtin info schema`` publishes, for every legal Python signature:
    no function is generated, so no parameter name, job name or description
    can fail to compile. FastMCP hands ``run`` the caller's arguments as sent;
    converting them is the binding door's job, as on every other surface
    (spec B-23), and a value it refuses comes back as ``isError: true``.
    """

    _app: Any = PrivateAttr()
    _policy: Any = PrivateAttr(default=None)
    _group_option_names: frozenset[str] = PrivateAttr(default=frozenset())

    @classmethod
    def for_job(
        cls, tool_def: MCPToolDef, app: PluginHost, policy: Any = None
    ) -> JobTool:
        """The tool for ``tool_def``, executing through ``app``."""
        tool = cls(
            name=tool_def.name,
            description=tool_def.description or f"Execute the {tool_def.name} job.",
            parameters=tool_def.input_schema or {"type": "object", "properties": {}},
        )
        tool._app = app
        tool._policy = policy
        tool._group_option_names = tool_def.group_option_names
        return tool

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Run the job; a refused or failed run is ``isError: true`` with its reason."""
        outcome = _execute_job(
            self._app,
            self.name,
            dict(arguments or {}),
            self._policy,
            self._group_option_names,
        )
        if _is_error(outcome):
            return ToolResult(
                content=str(outcome.get("error") or outcome.get("status")),
                structured_content=outcome,
                is_error=True,
            )
        return self.convert_result(outcome)


#: Run statuses a tool call reports as an error (contracts.md §6): the call was
#: refused at the binding door (``invalid``), or the run failed after starting.
_ERROR_STATUSES = frozenset({"invalid", "failure", "timeout"})


def _is_error(outcome: dict[str, Any]) -> bool:
    """Whether ``_execute_job``'s envelope is a refusal or a failure.

    A gate's ``tool_not_permitted`` refusal is not: it is the documented
    answer to a call made while a workflow waits, and carries its own code.
    """
    if outcome.get("error") == "tool_not_permitted":
        return False
    return "error" in outcome or outcome.get("status") in _ERROR_STATUSES


def _execute_job(
    app: PluginHost,
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
        Dict with status, return_value, duration_ms and metadata on success, or
        an error envelope — ``tool_not_permitted`` when a gate forbids the call,
        otherwise the raised error.

        ``status`` is a lowercase string. It used to be the raw ``RunStatus``
        enum object here and the ``.value`` string in ``run_job``, so the two
        doors into the same room disagreed about the shape of their answer.
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
            RunRequest(
                job_name=job_name,
                surface="mcp.tool",
                kwargs=job_kwargs,
                group_option_values=group_values or None,
            )
        )
        envelope: dict[str, Any] = {
            "status": wire_status(result.status),
            "return_value": result.return_value,
            "duration_ms": result.duration_ms,
            "metadata": wire_metadata(result),
        }
        # A refused or failed run carries its reason (F-31): the binding
        # door's refusal names the argument, a failure carries the error.
        exception = getattr(result, "exception", None)
        if envelope["status"] in _ERROR_STATUSES and exception is not None:
            envelope["error"] = str(exception)
        return envelope
    except ScopeCancelledError as e:
        # Same refusal, same code, as `run_job` — one error table, both doors.
        return {"error": "scope_cancelled", "message": str(e), "job_name": job_name}
    except Exception as e:
        logger.error("MCPServer: Error executing job '%s': %s", job_name, e)
        return {"error": str(e), "job_name": job_name}
