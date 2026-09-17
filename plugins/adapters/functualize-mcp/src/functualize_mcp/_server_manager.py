"""Multi-server management for functualize MCP.

Manages multiple background MCP HTTP servers, allowing users to start,
list, stop, and stop-all servers from a single host. Server state is
persisted in a JSON file so that the server list survives process restarts.

Used by ``func mcp start``, ``func mcp list``, ``func mcp stop`` CLI commands.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["ServerManager", "ServerInfo"]

logger = logging.getLogger(__name__)

# Default location for the server state file
_DEFAULT_STATE_DIR = Path.home() / ".functualize"
_STATE_FILENAME = "mcp_servers.json"


@dataclass
class ServerInfo:
    """Information about a managed MCP server.

    Attributes:
        name: User-assigned name for this server.
        directory: Absolute path to the functualize project directory.
        port: HTTP port the server is listening on.
        pid: Process ID of the background server process.
        status: Current status — "running" or "stopped".
        started_at: ISO 8601 timestamp when the server was started.
    """

    name: str
    directory: str
    port: int
    pid: int
    status: str = "running"
    started_at: str = field(default_factory=lambda: "")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON persistence."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerInfo:
        """Deserialize from a plain dict."""
        return cls(
            name=data["name"],
            directory=data["directory"],
            port=data["port"],
            pid=data["pid"],
            status=data.get("status", "running"),
            started_at=data.get("started_at", ""),
        )


class ServerManager:
    """Manages multiple background MCP HTTP servers.

    Provides start, list, stop, and stop_all operations for background
    MCP servers. Each server is identified by a unique name.

    Server state is persisted in a JSON file at
    ``~/.functualize/mcp_servers.json`` so that server listings survive
    process restarts.

    Args:
        state_dir: Directory for the state file. Defaults to ``~/.functualize``.
    """

    def __init__(self, state_dir: Path | None = None) -> None:
        self._state_dir = state_dir or _DEFAULT_STATE_DIR
        self._state_file = self._state_dir / _STATE_FILENAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, directory: str, name: str, port: int) -> ServerInfo:
        """Start a background MCP HTTP server for a functualize project.

        Launches a new background process running ``func mcp serve --http``
        in the specified directory. The server is tracked by name and its
        PID is persisted.

        Args:
            directory: Path to the functualize project directory.
            name: User-assigned name for this server instance.
            port: HTTP port to bind the server on (1024-65535).

        Returns:
            A ServerInfo describing the started server.

        Raises:
            ValueError: If name is already in use, port is invalid,
                or directory does not exist.
            RuntimeError: If the server process fails to start.
        """
        # Validate inputs
        abs_directory = str(Path(directory).resolve())
        if not Path(abs_directory).is_dir():
            raise ValueError(f"Directory does not exist: {abs_directory}")

        if port < 1024 or port > 65535:
            raise ValueError(f"Port must be between 1024 and 65535, got {port}")

        # Check for name conflicts
        servers = self._load_state()
        for server in servers:
            if server.name == name:
                raise ValueError(
                    f"Server with name '{name}' already exists. "
                    "Stop it first or choose a different name."
                )

        # Start the background process
        pid = self._start_server_process(abs_directory, port)

        # Record the server info
        info = ServerInfo(
            name=name,
            directory=abs_directory,
            port=port,
            pid=pid,
            status="running",
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )
        servers.append(info)
        self._save_state(servers)

        logger.info(
            "ServerManager: Started server '%s' (PID=%d) on port %d for %s",
            name,
            pid,
            port,
            abs_directory,
        )
        return info

    def list(self) -> list[ServerInfo]:
        """List all managed servers with current status.

        Checks whether each tracked server process is still alive and
        updates the status accordingly.

        Returns:
            A list of ServerInfo objects with up-to-date status.
        """
        servers = self._load_state()
        changed = False

        for server in servers:
            actual_status = self._check_process_status(server.pid)
            if actual_status != server.status:
                server.status = actual_status
                changed = True

        if changed:
            self._save_state(servers)

        return servers

    def stop(self, name: str) -> None:
        """Stop a managed server by name.

        Sends SIGTERM to the server process and removes it from the
        tracked server list.

        Args:
            name: The name of the server to stop.

        Raises:
            ValueError: If no server with the given name is found.
        """
        servers = self._load_state()
        target = None
        remaining = []

        for server in servers:
            if server.name == name:
                target = server
            else:
                remaining.append(server)

        if target is None:
            raise ValueError(
                f"No server found with name '{name}'. "
                "Use 'func mcp list' to see running servers."
            )

        self._terminate_process(target.pid)
        self._save_state(remaining)

        logger.info(
            "ServerManager: Stopped server '%s' (PID=%d)",
            name,
            target.pid,
        )

    def stop_all(self) -> None:
        """Stop all managed servers.

        Sends SIGTERM to all tracked server processes and clears the
        server list.
        """
        servers = self._load_state()

        for server in servers:
            self._terminate_process(server.pid)
            logger.info(
                "ServerManager: Stopped server '%s' (PID=%d)",
                server.name,
                server.pid,
            )

        self._save_state([])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _start_server_process(self, directory: str, port: int) -> int:
        """Launch a background MCP HTTP server process.

        Args:
            directory: Working directory for the server process.
            port: HTTP port to bind.

        Returns:
            The PID of the started process.

        Raises:
            RuntimeError: If the process fails to start.
        """
        # Use sys.executable to ensure we use the same Python interpreter
        cmd = [
            sys.executable,
            "-m",
            "functualize._cli.main",
        ]
        # Construct the equivalent of `func mcp serve --http --port PORT`
        # We use a wrapper that starts the MCP server in HTTP mode
        cmd = [
            sys.executable,
            "-c",
            (
                "import sys; sys.path.insert(0, '.'); "
                "from functualize.app import FunctualizeApp; "
                "from functualize.app.utils import auto_discover; "
                "from functualize_mcp._config import MCPConfig; "
                "from functualize_mcp._server import MCPServer; "
                "from pathlib import Path; "
                f"job_sources = auto_discover(Path('{directory}')); "
                f"app = FunctualizeApp(name='mcp-server', job_sources=job_sources); "
                f"config = MCPConfig(transport='http', port={port}, host='127.0.0.1'); "
                "server = MCPServer(app, config=config); "
                f"server.start_http('127.0.0.1', {port})"
            ),
        ]

        try:
            process = subprocess.Popen(
                cmd,
                cwd=directory,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            # Give the process a moment to start and check it didn't crash immediately
            time.sleep(0.3)
            if process.poll() is not None:
                raise RuntimeError(
                    f"Server process exited immediately with code {process.returncode}"
                )
            return process.pid
        except OSError as e:
            raise RuntimeError(f"Failed to start server process: {e}") from e

    def _check_process_status(self, pid: int) -> str:
        """Check whether a process is still running.

        Args:
            pid: Process ID to check.

        Returns:
            "running" if the process is alive, "stopped" otherwise.
        """
        try:
            os.kill(pid, 0)
            return "running"
        except (OSError, ProcessLookupError):
            return "stopped"

    def _terminate_process(self, pid: int) -> None:
        """Terminate a process by PID.

        Sends SIGTERM first, waits briefly, then SIGKILL if needed.

        Args:
            pid: Process ID to terminate.
        """
        try:
            os.kill(pid, signal.SIGTERM)
            # Wait briefly for graceful shutdown
            for _ in range(10):
                time.sleep(0.1)
                try:
                    os.kill(pid, 0)
                except (OSError, ProcessLookupError):
                    return  # Process has exited
            # Force kill if still running
            with contextlib.suppress(OSError, ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            # Process already gone
            pass

    def _load_state(self) -> list[ServerInfo]:
        """Load the server state from disk.

        Returns:
            List of ServerInfo loaded from the state file.
            Returns empty list if the file doesn't exist.
        """
        if not self._state_file.exists():
            return []

        try:
            data = json.loads(self._state_file.read_text())
            return [ServerInfo.from_dict(entry) for entry in data]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("ServerManager: Failed to load state file: %s", e)
            return []

    def _save_state(self, servers: list[ServerInfo]) -> None:
        """Persist the server state to disk.

        Creates the state directory if it doesn't exist.

        Args:
            servers: List of ServerInfo to persist.
        """
        self._state_dir.mkdir(parents=True, exist_ok=True)
        data = [server.to_dict() for server in servers]
        self._state_file.write_text(json.dumps(data, indent=2))
