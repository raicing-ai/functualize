"""MCP management meta-tools — manage background MCP servers via MCP.

Provides mcp_start_server, mcp_list_servers, mcp_stop_server, and
mcp_get_server_tools tools. These tools are only exposed when
``enable_management=True`` in MCPConfig (or ``--enable-management``
CLI flag).

These tools allow an external AI agent to manage background MCP servers:
start new servers for project directories, list running servers, stop
servers by name, and discover tools available on a managed server.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from functualize_mcp._server_manager import ServerManager

if TYPE_CHECKING:
    from functualize_mcp._config import MCPConfig

__all__ = ["MCPManagementToolRegistry"]

logger = logging.getLogger(__name__)


class MCPManagementToolRegistry:
    """Registers MCP management meta-tools when enable_management is True.

    Provides four tools for managing background MCP servers:
    - mcp_start_server: Start a new background MCP server
    - mcp_list_servers: List all managed servers
    - mcp_stop_server: Stop a server by name
    - mcp_get_server_tools: Discover tools on a managed server

    Args:
        config: MCPConfig instance controlling whether management is enabled.
        server_manager: Optional ServerManager instance. If not provided,
            a default one is created.
    """

    def __init__(
        self,
        config: MCPConfig,
        *,
        server_manager: ServerManager | None = None,
    ) -> None:
        self._config = config
        self._server_manager = server_manager or ServerManager()

    def register_tools(self, mcp: Any) -> None:
        """Register management tools with the FastMCP server instance.

        Only registers if ``config.enable_management`` is True.

        Args:
            mcp: The FastMCP instance to register tools with.
        """
        if not self._config.enable_management:
            logger.debug(
                "MCPManagementToolRegistry: Management tools disabled "
                "(enable_management=False)."
            )
            return

        mcp.add_tool(self._mcp_start_server)
        mcp.add_tool(self._mcp_list_servers)
        mcp.add_tool(self._mcp_stop_server)
        mcp.add_tool(self._mcp_get_server_tools)
        logger.info("MCPManagementToolRegistry: Registered 4 management meta-tools")

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _mcp_start_server(
        self,
        directory: str,
        name: str,
        port: int = 8080,
    ) -> dict[str, Any]:
        """Start a new background MCP HTTP server for a project directory.

        Launches a new background process serving MCP tools for the
        functualize project at the given directory. The server is tracked
        by name and can be stopped later.

        Args:
            directory: Path to the functualize project directory.
            name: User-assigned name for this server instance.
            port: HTTP port to bind the server on (1024-65535, default 8080).

        Returns:
            Dict with server info (name, directory, port, pid, status)
            on success, or an error response on failure.
        """
        try:
            info = self._server_manager.start(directory, name, port)
            return {
                "name": info.name,
                "directory": info.directory,
                "port": info.port,
                "pid": info.pid,
                "status": info.status,
                "started_at": info.started_at,
            }
        except ValueError as e:
            return _error_response("invalid_input", str(e))
        except RuntimeError as e:
            return _error_response("start_failed", str(e))

    _mcp_start_server.__name__ = "mcp_start_server"
    _mcp_start_server.__qualname__ = "mcp_start_server"
    _mcp_start_server.__doc__ = (
        "Start a new background MCP HTTP server for a functualize project. "
        "The server exposes tools from the project at the given directory. "
        "Args: directory — path to the project; name — unique server name; "
        "port — HTTP port (1024-65535, default 8080)."
    )

    async def _mcp_list_servers(self) -> dict[str, Any]:
        """List all managed MCP servers with their current status.

        Returns a list of all tracked servers with up-to-date status
        (checks if processes are still alive).

        Returns:
            Dict with "servers" key containing list of server info dicts.
        """
        servers = self._server_manager.list()
        return {
            "servers": [
                {
                    "name": s.name,
                    "directory": s.directory,
                    "port": s.port,
                    "pid": s.pid,
                    "status": s.status,
                    "started_at": s.started_at,
                }
                for s in servers
            ]
        }

    _mcp_list_servers.__name__ = "mcp_list_servers"
    _mcp_list_servers.__qualname__ = "mcp_list_servers"
    _mcp_list_servers.__doc__ = (
        "List all managed MCP servers with their current status. "
        "Returns server name, directory, port, PID, and status for each."
    )

    async def _mcp_stop_server(self, name: str) -> dict[str, Any]:
        """Stop a managed MCP server by name.

        Sends SIGTERM to the server process and removes it from the
        tracked server list.

        Args:
            name: The name of the server to stop.

        Returns:
            Dict with "stopped" key on success, or an error response
            if the server is not found.
        """
        try:
            self._server_manager.stop(name)
            return {"stopped": True, "name": name}
        except ValueError as e:
            return _error_response("server_not_found", str(e))

    _mcp_stop_server.__name__ = "mcp_stop_server"
    _mcp_stop_server.__qualname__ = "mcp_stop_server"
    _mcp_stop_server.__doc__ = (
        "Stop a managed MCP server by name. Terminates the server process "
        "and removes it from the tracked list. "
        "Args: name — the name of the server to stop."
    )

    async def _mcp_get_server_tools(self, name: str) -> dict[str, Any]:
        """Discover tools available on a named managed server.

        Proxies a discover_jobs call to the specified managed server
        via HTTP and returns its tool list.

        Args:
            name: The name of the managed server to query.

        Returns:
            Dict with "tools" key containing the server's tool list,
            or an error response if the server is not found or unreachable.
        """
        # Find the server by name
        servers = self._server_manager.list()
        target = None
        for server in servers:
            if server.name == name:
                target = server
                break

        if target is None:
            return _error_response(
                "server_not_found",
                f"No server found with name '{name}'. "
                "Use mcp_list_servers to see running servers.",
            )

        if target.status != "running":
            return _error_response(
                "server_not_running",
                f"Server '{name}' is not running (status: {target.status}).",
            )

        # Proxy discover_jobs to the managed server via HTTP
        try:
            tools = await self._proxy_discover_tools(target.port)
            return {"server": name, "tools": tools}
        except Exception as e:
            logger.error(
                "MCPManagementToolRegistry: Error querying server '%s': %s",
                name,
                e,
            )
            return _error_response(
                "server_unreachable",
                f"Failed to query server '{name}' on port {target.port}: {e}",
            )

    _mcp_get_server_tools.__name__ = "mcp_get_server_tools"
    _mcp_get_server_tools.__qualname__ = "mcp_get_server_tools"
    _mcp_get_server_tools.__doc__ = (
        "Discover tools available on a named managed server. Proxies a "
        "discover_jobs call to the server and returns its tool list. "
        "Args: name — the name of the managed server to query."
    )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _proxy_discover_tools(self, port: int) -> list[dict[str, Any]]:
        """Proxy a tool discovery request to a managed server via HTTP.

        Makes an HTTP request to the managed server's MCP endpoint to
        discover available tools.

        Args:
            port: The HTTP port of the managed server.

        Returns:
            A list of tool dicts with name and description.

        Raises:
            Exception: If the HTTP request fails or the response is invalid.
        """
        import json as json_mod
        import urllib.request

        url = f"http://127.0.0.1:{port}/mcp/tools"

        try:
            # Use stdlib urllib to avoid extra dependencies
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "application/json")

            with urllib.request.urlopen(req, timeout=5) as response:
                data = json_mod.loads(response.read().decode("utf-8"))
                # Expect either a list of tools or a dict with "tools" key
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "tools" in data:
                    return data["tools"]
                elif isinstance(data, dict) and "jobs" in data:
                    # Fallback: discover_jobs returns {"jobs": [...]}
                    return data["jobs"]
                else:
                    return [data] if data else []
        except urllib.error.URLError:
            # Fallback: try the SSE/MCP endpoint format
            # MCP servers may not have a simple REST endpoint,
            # so we attempt an alternative approach
            return await self._proxy_discover_via_mcp_client(port)

    async def _proxy_discover_via_mcp_client(self, port: int) -> list[dict[str, Any]]:
        """Attempt tool discovery via MCP client protocol.

        Falls back to using the MCP client SDK if a simple HTTP GET
        doesn't work. If the MCP client is not available, returns an
        empty list with a note about the limitation.

        Args:
            port: The HTTP port of the managed server.

        Returns:
            A list of tool dicts, or empty list if discovery fails.
        """
        try:
            from fastmcp import Client

            async with Client(f"http://127.0.0.1:{port}/sse") as client:
                tools = await client.list_tools()
                return [
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                    }
                    for tool in tools
                ]
        except ImportError:
            logger.warning(
                "MCPManagementToolRegistry: fastmcp Client not available "
                "for proxied tool discovery."
            )
            return []
        except Exception as e:
            logger.warning(
                "MCPManagementToolRegistry: MCP client discovery failed: %s", e
            )
            raise


def _error_response(error_code: str, message: str) -> dict[str, Any]:
    """Build a structured error response dict.

    Args:
        error_code: Machine-readable error code.
        message: Human-readable error message.

    Returns:
        Dict with "error" key containing code and message.
    """
    return {
        "error": {
            "code": error_code,
            "message": message,
        }
    }
