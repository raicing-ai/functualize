"""Unit tests for MCP management meta-tools."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from functualize_mcp._config import MCPConfig
from functualize_mcp._management_tools import MCPManagementToolRegistry
from functualize_mcp._server_manager import ServerInfo, ServerManager

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def run(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for server state."""
    state_dir = tmp_path / ".functualize"
    state_dir.mkdir()
    return state_dir


@pytest.fixture
def server_manager(tmp_state_dir: Path) -> ServerManager:
    """Create a ServerManager with a temporary state directory."""
    return ServerManager(state_dir=tmp_state_dir)


@pytest.fixture
def enabled_config() -> MCPConfig:
    """MCPConfig with management enabled."""
    return MCPConfig(enable_management=True)


@pytest.fixture
def disabled_config() -> MCPConfig:
    """MCPConfig with management disabled."""
    return MCPConfig(enable_management=False)


@pytest.fixture
def registry(
    enabled_config: MCPConfig, server_manager: ServerManager
) -> MCPManagementToolRegistry:
    """Create a management tool registry with management enabled."""
    return MCPManagementToolRegistry(enabled_config, server_manager=server_manager)


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a fake project directory."""
    project = tmp_path / "my-project"
    project.mkdir()
    return project


# ---------------------------------------------------------------------------
# Tests for registration
# ---------------------------------------------------------------------------


class TestMCPManagementToolRegistration:
    """Tests for conditional tool registration."""

    def test_registers_tools_when_management_enabled(
        self, enabled_config: MCPConfig, server_manager: ServerManager
    ):
        """Tools are registered when enable_management is True."""
        reg = MCPManagementToolRegistry(enabled_config, server_manager=server_manager)
        mcp = MagicMock()

        reg.register_tools(mcp)

        assert mcp.add_tool.call_count == 4

    def test_does_not_register_tools_when_management_disabled(
        self, disabled_config: MCPConfig, server_manager: ServerManager
    ):
        """No tools registered when enable_management is False."""
        reg = MCPManagementToolRegistry(disabled_config, server_manager=server_manager)
        mcp = MagicMock()

        reg.register_tools(mcp)

        mcp.add_tool.assert_not_called()

    def test_registered_tool_names(
        self, enabled_config: MCPConfig, server_manager: ServerManager
    ):
        """The four expected management tools are registered."""
        reg = MCPManagementToolRegistry(enabled_config, server_manager=server_manager)
        mcp = MagicMock()

        reg.register_tools(mcp)

        registered_names = set()
        for call in mcp.add_tool.call_args_list:
            fn = call[0][0]
            registered_names.add(fn.__name__)

        assert registered_names == {
            "mcp_start_server",
            "mcp_list_servers",
            "mcp_stop_server",
            "mcp_get_server_tools",
        }


# ---------------------------------------------------------------------------
# Tests for mcp_start_server
# ---------------------------------------------------------------------------


class TestMCPStartServer:
    """Tests for the mcp_start_server tool."""

    @patch("functualize_mcp._server_manager.subprocess.Popen")
    def test_start_server_success(
        self,
        mock_popen: MagicMock,
        registry: MCPManagementToolRegistry,
        project_dir: Path,
    ):
        """mcp_start_server returns server info on success."""
        mock_process = MagicMock()
        mock_process.pid = 42
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        result = run(
            registry._mcp_start_server(
                directory=str(project_dir),
                name="test-server",
                port=9090,
            )
        )

        assert "error" not in result
        assert result["name"] == "test-server"
        assert result["port"] == 9090
        assert result["pid"] == 42
        assert result["status"] == "running"
        assert result["directory"] == str(project_dir.resolve())

    def test_start_server_invalid_directory(self, registry: MCPManagementToolRegistry):
        """mcp_start_server returns error for non-existent directory."""
        result = run(
            registry._mcp_start_server(
                directory="/nonexistent/path",
                name="test-server",
                port=8080,
            )
        )

        assert "error" in result
        assert result["error"]["code"] == "invalid_input"
        assert "does not exist" in result["error"]["message"]

    def test_start_server_invalid_port(
        self, registry: MCPManagementToolRegistry, project_dir: Path
    ):
        """mcp_start_server returns error for invalid port."""
        result = run(
            registry._mcp_start_server(
                directory=str(project_dir),
                name="test-server",
                port=80,  # Below 1024
            )
        )

        assert "error" in result
        assert result["error"]["code"] == "invalid_input"
        assert "Port must be between" in result["error"]["message"]

    @patch("functualize_mcp._server_manager.subprocess.Popen")
    def test_start_server_duplicate_name(
        self,
        mock_popen: MagicMock,
        registry: MCPManagementToolRegistry,
        project_dir: Path,
    ):
        """mcp_start_server returns error for duplicate name."""
        mock_process = MagicMock()
        mock_process.pid = 42
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        # Start the first server
        run(
            registry._mcp_start_server(
                directory=str(project_dir),
                name="my-server",
                port=8080,
            )
        )

        # Try to start another with the same name
        result = run(
            registry._mcp_start_server(
                directory=str(project_dir),
                name="my-server",
                port=9090,
            )
        )

        assert "error" in result
        assert result["error"]["code"] == "invalid_input"
        assert "already exists" in result["error"]["message"]


# ---------------------------------------------------------------------------
# Tests for mcp_list_servers
# ---------------------------------------------------------------------------


class TestMCPListServers:
    """Tests for the mcp_list_servers tool."""

    def test_list_servers_empty(self, registry: MCPManagementToolRegistry):
        """mcp_list_servers returns empty list when no servers exist."""
        result = run(registry._mcp_list_servers())

        assert "servers" in result
        assert result["servers"] == []

    @patch("functualize_mcp._server_manager.subprocess.Popen")
    @patch("functualize_mcp._server_manager.os.kill")
    def test_list_servers_returns_all(
        self,
        mock_kill: MagicMock,
        mock_popen: MagicMock,
        registry: MCPManagementToolRegistry,
        tmp_path: Path,
    ):
        """mcp_list_servers returns all tracked servers."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        mock_kill.return_value = None  # Process alive

        dir1 = tmp_path / "proj1"
        dir1.mkdir()
        dir2 = tmp_path / "proj2"
        dir2.mkdir()

        mock_process.pid = 10
        run(registry._mcp_start_server(str(dir1), "srv1", 8080))
        mock_process.pid = 20
        run(registry._mcp_start_server(str(dir2), "srv2", 9090))

        result = run(registry._mcp_list_servers())

        assert len(result["servers"]) == 2
        names = {s["name"] for s in result["servers"]}
        assert names == {"srv1", "srv2"}

    def test_list_servers_includes_status(
        self, registry: MCPManagementToolRegistry, tmp_state_dir: Path
    ):
        """mcp_list_servers includes current status for each server."""
        # Pre-populate state file
        state_file = tmp_state_dir / "mcp_servers.json"
        servers = [
            ServerInfo(
                name="alive",
                directory="/tmp",
                port=8080,
                pid=99999,
                status="running",
            ).to_dict()
        ]
        state_file.write_text(json.dumps(servers))

        with patch("functualize_mcp._server_manager.os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError("gone")
            result = run(registry._mcp_list_servers())

        assert len(result["servers"]) == 1
        assert result["servers"][0]["status"] == "stopped"


# ---------------------------------------------------------------------------
# Tests for mcp_stop_server
# ---------------------------------------------------------------------------


class TestMCPStopServer:
    """Tests for the mcp_stop_server tool."""

    def test_stop_server_not_found(self, registry: MCPManagementToolRegistry):
        """mcp_stop_server returns error when server not found."""
        result = run(registry._mcp_stop_server(name="nonexistent"))

        assert "error" in result
        assert result["error"]["code"] == "server_not_found"

    @patch("functualize_mcp._server_manager.subprocess.Popen")
    @patch("functualize_mcp._server_manager.os.kill")
    def test_stop_server_success(
        self,
        mock_kill: MagicMock,
        mock_popen: MagicMock,
        registry: MCPManagementToolRegistry,
        project_dir: Path,
    ):
        """mcp_stop_server stops the server and returns success."""
        mock_process = MagicMock()
        mock_process.pid = 42
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        # SIGTERM then process gone
        mock_kill.side_effect = [None, ProcessLookupError("gone")]

        # Start a server first
        run(registry._mcp_start_server(str(project_dir), "my-server", 8080))

        # Reset mock to track stop calls
        mock_kill.reset_mock()
        mock_kill.side_effect = [None, ProcessLookupError("gone")]

        result = run(registry._mcp_stop_server(name="my-server"))

        assert "error" not in result
        assert result["stopped"] is True
        assert result["name"] == "my-server"

    @patch("functualize_mcp._server_manager.subprocess.Popen")
    @patch("functualize_mcp._server_manager.os.kill")
    def test_stop_server_removes_from_list(
        self,
        mock_kill: MagicMock,
        mock_popen: MagicMock,
        registry: MCPManagementToolRegistry,
        project_dir: Path,
    ):
        """mcp_stop_server removes the server from the managed list."""
        mock_process = MagicMock()
        mock_process.pid = 42
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        mock_kill.side_effect = [None, ProcessLookupError("gone")]

        # Start then stop
        run(registry._mcp_start_server(str(project_dir), "my-server", 8080))
        mock_kill.reset_mock()
        mock_kill.side_effect = [None, ProcessLookupError("gone")]
        run(registry._mcp_stop_server(name="my-server"))

        # Verify list is empty
        mock_kill.reset_mock()
        result = run(registry._mcp_list_servers())
        assert result["servers"] == []


# ---------------------------------------------------------------------------
# Tests for mcp_get_server_tools
# ---------------------------------------------------------------------------


class TestMCPGetServerTools:
    """Tests for the mcp_get_server_tools tool."""

    def test_get_tools_server_not_found(self, registry: MCPManagementToolRegistry):
        """mcp_get_server_tools returns error when server not found."""
        result = run(registry._mcp_get_server_tools(name="nonexistent"))

        assert "error" in result
        assert result["error"]["code"] == "server_not_found"

    def test_get_tools_server_not_running(
        self, registry: MCPManagementToolRegistry, tmp_state_dir: Path
    ):
        """mcp_get_server_tools returns error when server is stopped."""
        state_file = tmp_state_dir / "mcp_servers.json"
        servers = [
            ServerInfo(
                name="dead-srv",
                directory="/tmp",
                port=8080,
                pid=99999,
                status="stopped",
            ).to_dict()
        ]
        state_file.write_text(json.dumps(servers))

        with patch("functualize_mcp._server_manager.os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError("gone")
            result = run(registry._mcp_get_server_tools(name="dead-srv"))

        assert "error" in result
        assert result["error"]["code"] == "server_not_running"

    @patch("functualize_mcp._server_manager.os.kill")
    def test_get_tools_proxies_to_server(
        self,
        mock_kill: MagicMock,
        registry: MCPManagementToolRegistry,
        tmp_state_dir: Path,
    ):
        """mcp_get_server_tools proxies tool discovery to the server."""
        mock_kill.return_value = None  # Process alive

        state_file = tmp_state_dir / "mcp_servers.json"
        servers = [
            ServerInfo(
                name="my-server",
                directory="/tmp",
                port=8080,
                pid=12345,
                status="running",
            ).to_dict()
        ]
        state_file.write_text(json.dumps(servers))

        mock_tools = [
            {"name": "tool1", "description": "First tool"},
            {"name": "tool2", "description": "Second tool"},
        ]

        async def run_test():
            with patch.object(
                registry, "_proxy_discover_tools", new_callable=AsyncMock
            ) as mock_proxy:
                mock_proxy.return_value = mock_tools
                result = await registry._mcp_get_server_tools(name="my-server")
            return result, mock_proxy

        result, mock_proxy = asyncio.run(run_test())

        assert "error" not in result
        assert result["server"] == "my-server"
        assert result["tools"] == mock_tools
        mock_proxy.assert_called_once_with(8080)

    @patch("functualize_mcp._server_manager.os.kill")
    def test_get_tools_handles_proxy_error(
        self,
        mock_kill: MagicMock,
        registry: MCPManagementToolRegistry,
        tmp_state_dir: Path,
    ):
        """mcp_get_server_tools returns error when proxy fails."""
        mock_kill.return_value = None  # Process alive

        state_file = tmp_state_dir / "mcp_servers.json"
        servers = [
            ServerInfo(
                name="my-server",
                directory="/tmp",
                port=8080,
                pid=12345,
                status="running",
            ).to_dict()
        ]
        state_file.write_text(json.dumps(servers))

        async def run_test():
            with patch.object(
                registry, "_proxy_discover_tools", new_callable=AsyncMock
            ) as mock_proxy:
                mock_proxy.side_effect = ConnectionError("Connection refused")
                result = await registry._mcp_get_server_tools(name="my-server")
            return result

        result = asyncio.run(run_test())

        assert "error" in result
        assert result["error"]["code"] == "server_unreachable"


# ---------------------------------------------------------------------------
# Tests for run_job proxy support
# ---------------------------------------------------------------------------


class TestMCPManagementRunJobProxy:
    """Tests for proxying run_job calls to named managed servers."""

    @patch("functualize_mcp._server_manager.subprocess.Popen")
    @patch("functualize_mcp._server_manager.os.kill")
    def test_get_server_tools_returns_discoverable_tools(
        self,
        mock_kill: MagicMock,
        mock_popen: MagicMock,
        registry: MCPManagementToolRegistry,
        project_dir: Path,
    ):
        """When a server is running, its tools can be discovered for proxying."""
        mock_process = MagicMock()
        mock_process.pid = 42
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        mock_kill.return_value = None  # Process alive

        run(registry._mcp_start_server(str(project_dir), "proxy-target", 8080))

        mock_tools = [
            {"name": "run_job", "description": "Execute a functualize job"},
        ]

        async def run_test():
            with patch.object(
                registry, "_proxy_discover_tools", new_callable=AsyncMock
            ) as mock_proxy:
                mock_proxy.return_value = mock_tools
                result = await registry._mcp_get_server_tools(name="proxy-target")
            return result

        result = asyncio.run(run_test())

        assert "error" not in result
        assert result["server"] == "proxy-target"
        assert any(t["name"] == "run_job" for t in result["tools"])
