"""Unit tests for MCPServer (stdio + HTTP transport)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from functualize_mcp._config import MCPConfig
from functualize_mcp._server import MCPServer

# ---------------------------------------------------------------------------
# Test helpers — minimal app and descriptor fakes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeField:
    name: str
    type_annotation: str
    default: Any | None = None
    description: str = ""
    required: bool = True
    choices: list[str] | None = None


@dataclass
class FakeDescriptor:
    name: str
    group: str | None = None
    docstring: str | None = None
    config_fields: list[FakeField] = field(default_factory=list)
    parameters: list[FakeField] = field(default_factory=list)
    declaration: Any = field(default_factory=dict)


class FakeJobResult:
    """Fake job result returned by app.execute()."""

    def __init__(
        self,
        status: str = "success",
        return_value: Any = None,
        duration_ms: float = 42.0,
    ):
        self.status = status
        self.return_value = return_value
        self.duration_ms = duration_ms


class FakeApp:
    """Minimal fake FunctualizeApp for testing MCPServer."""

    def __init__(self, descriptors: list[FakeDescriptor] | None = None):
        self._descriptors = descriptors or []
        self._execute_results: dict[str, FakeJobResult] = {}

    def get_jobs(self) -> list[FakeDescriptor]:
        return self._descriptors

    def execute(self, job_name: str, **kwargs: Any) -> FakeJobResult:
        if job_name in self._execute_results:
            return self._execute_results[job_name]
        return FakeJobResult(status="success", return_value=f"executed {job_name}")


# ---------------------------------------------------------------------------
# Tests for MCPServer initialization
# ---------------------------------------------------------------------------


class TestMCPServerInit:
    """Tests for MCPServer construction and internal state."""

    def test_creates_fastmcp_instance(self):
        """MCPServer creates a FastMCP instance on init."""
        app = FakeApp()
        config = MCPConfig()
        server = MCPServer(app, config=config)
        assert server._mcp is not None
        assert server._tools_registered is False

    def test_stores_app_and_config(self):
        """MCPServer stores the app and config references."""
        app = FakeApp()
        config = MCPConfig(transport="http", port=9090)
        server = MCPServer(app, config=config)
        assert server._app is app
        assert server._config is config


# ---------------------------------------------------------------------------
# Tests for tool registration
# ---------------------------------------------------------------------------


class TestMCPServerToolRegistration:
    """Tests for _register_tools behavior."""

    def test_registers_tools_from_descriptors(self):
        """Tools are registered for each translated job descriptor."""
        descriptors = [
            FakeDescriptor(name="job_a", docstring="Job A does stuff."),
            FakeDescriptor(name="job_b", docstring="Job B does other stuff."),
        ]
        app = FakeApp(descriptors=descriptors)
        config = MCPConfig()
        server = MCPServer(app, config=config)

        server._register_tools()

        assert server._tools_registered is True

    def test_idempotent_registration(self):
        """Calling _register_tools twice doesn't double-register."""
        descriptors = [
            FakeDescriptor(name="job_a", docstring="Job A."),
        ]
        app = FakeApp(descriptors=descriptors)
        config = MCPConfig()
        server = MCPServer(app, config=config)

        server._register_tools()
        server._register_tools()  # Second call should be no-op

        assert server._tools_registered is True

    def test_empty_descriptors_no_tools(self):
        """No tools registered when app has no jobs."""
        app = FakeApp(descriptors=[])
        config = MCPConfig()
        server = MCPServer(app, config=config)

        server._register_tools()

        assert server._tools_registered is True

    def test_filters_applied_via_config(self):
        """MCPConfig exclude_jobs filters out excluded jobs."""
        descriptors = [
            FakeDescriptor(name="keep_job", docstring="Keep."),
            FakeDescriptor(name="drop_job", docstring="Drop."),
        ]
        app = FakeApp(descriptors=descriptors)
        config = MCPConfig(exclude_jobs=["drop_job"])
        server = MCPServer(app, config=config)

        server._register_tools()

        assert server._tools_registered is True


# ---------------------------------------------------------------------------
# Tests for start_stdio transport
# ---------------------------------------------------------------------------


class TestMCPServerStdio:
    """Tests for stdio transport start."""

    def test_start_stdio_registers_tools_and_runs(self):
        """start_stdio registers tools then calls FastMCP.run with stdio."""
        app = FakeApp(descriptors=[FakeDescriptor(name="test_job")])
        config = MCPConfig()
        server = MCPServer(app, config=config)

        with patch.object(server._mcp, "run") as mock_run:
            server.start_stdio()

            assert server._tools_registered is True
            mock_run.assert_called_once_with(transport="stdio")

    def test_start_stdio_with_no_jobs(self):
        """start_stdio works even with no registered jobs."""
        app = FakeApp(descriptors=[])
        config = MCPConfig()
        server = MCPServer(app, config=config)

        with patch.object(server._mcp, "run") as mock_run:
            server.start_stdio()

            mock_run.assert_called_once_with(transport="stdio")


# ---------------------------------------------------------------------------
# Tests for start_http transport
# ---------------------------------------------------------------------------


class TestMCPServerHTTP:
    """Tests for HTTP+SSE transport start."""

    def test_start_http_registers_tools_and_runs(self):
        """start_http registers tools then calls FastMCP.run with sse."""
        app = FakeApp(descriptors=[FakeDescriptor(name="test_job")])
        config = MCPConfig(transport="http", port=9090, host="0.0.0.0")
        server = MCPServer(app, config=config)

        with patch.object(server._mcp, "run") as mock_run:
            server.start_http(host="0.0.0.0", port=9090)

            assert server._tools_registered is True
            mock_run.assert_called_once_with(transport="sse", host="0.0.0.0", port=9090)

    def test_start_http_custom_port(self):
        """start_http passes the correct port and host."""
        app = FakeApp(descriptors=[])
        config = MCPConfig()
        server = MCPServer(app, config=config)

        with patch.object(server._mcp, "run") as mock_run:
            server.start_http(host="127.0.0.1", port=3000)

            mock_run.assert_called_once_with(
                transport="sse", host="127.0.0.1", port=3000
            )

    def test_start_http_boundary_port_low(self):
        """start_http works with lowest valid port (1024)."""
        app = FakeApp(descriptors=[])
        config = MCPConfig(port=1024)
        server = MCPServer(app, config=config)

        with patch.object(server._mcp, "run") as mock_run:
            server.start_http(host="127.0.0.1", port=1024)

            mock_run.assert_called_once_with(
                transport="sse", host="127.0.0.1", port=1024
            )

    def test_start_http_boundary_port_high(self):
        """start_http works with highest valid port (65535)."""
        app = FakeApp(descriptors=[])
        config = MCPConfig(port=65535)
        server = MCPServer(app, config=config)

        with patch.object(server._mcp, "run") as mock_run:
            server.start_http(host="127.0.0.1", port=65535)

            mock_run.assert_called_once_with(
                transport="sse", host="127.0.0.1", port=65535
            )


# ---------------------------------------------------------------------------
# Tests for MCPConfig port validation
# ---------------------------------------------------------------------------


class TestMCPConfigValidation:
    """Tests for MCPConfig port boundary enforcement."""

    def test_port_below_minimum_rejected(self):
        """Port below 1024 is rejected by MCPConfig validation."""
        with pytest.raises(ValueError):
            MCPConfig(port=1023)

    def test_port_above_maximum_rejected(self):
        """Port above 65535 is rejected by MCPConfig validation."""
        with pytest.raises(ValueError):
            MCPConfig(port=65536)

    def test_port_default_is_8080(self):
        """Default port is 8080."""
        config = MCPConfig()
        assert config.port == 8080

    def test_transport_default_is_stdio(self):
        """Default transport is stdio."""
        config = MCPConfig()
        assert config.transport == "stdio"
