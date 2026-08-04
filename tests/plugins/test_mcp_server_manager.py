"""Unit tests for ServerManager (multi-server management)."""

from __future__ import annotations

import json
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from functualize_mcp._server_manager import ServerInfo, ServerManager

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
def manager(tmp_state_dir: Path) -> ServerManager:
    """Create a ServerManager with a temporary state directory."""
    return ServerManager(state_dir=tmp_state_dir)


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a fake project directory."""
    project = tmp_path / "my-project"
    project.mkdir()
    return project


# ---------------------------------------------------------------------------
# Tests for ServerInfo
# ---------------------------------------------------------------------------


class TestServerInfo:
    """Tests for the ServerInfo dataclass."""

    def test_to_dict_round_trip(self):
        """ServerInfo serializes and deserializes correctly."""
        info = ServerInfo(
            name="test-server",
            directory="/tmp/project",
            port=8080,
            pid=12345,
            status="running",
            started_at="2024-01-01T00:00:00+0000",
        )
        data = info.to_dict()
        restored = ServerInfo.from_dict(data)
        assert restored.name == info.name
        assert restored.directory == info.directory
        assert restored.port == info.port
        assert restored.pid == info.pid
        assert restored.status == info.status
        assert restored.started_at == info.started_at

    def test_from_dict_defaults(self):
        """ServerInfo.from_dict handles missing optional fields."""
        data = {"name": "x", "directory": "/tmp", "port": 8080, "pid": 1}
        info = ServerInfo.from_dict(data)
        assert info.status == "running"
        assert info.started_at == ""


# ---------------------------------------------------------------------------
# Tests for ServerManager.start
# ---------------------------------------------------------------------------


class TestServerManagerStart:
    """Tests for the start method."""

    def test_start_validates_directory_exists(self, manager: ServerManager):
        """start raises ValueError if directory does not exist."""
        with pytest.raises(ValueError, match="Directory does not exist"):
            manager.start("/nonexistent/path", "my-server", 8080)

    def test_start_validates_port_range_low(
        self, manager: ServerManager, project_dir: Path
    ):
        """start raises ValueError for port below 1024."""
        with pytest.raises(ValueError, match="Port must be between"):
            manager.start(str(project_dir), "my-server", 1023)

    def test_start_validates_port_range_high(
        self, manager: ServerManager, project_dir: Path
    ):
        """start raises ValueError for port above 65535."""
        with pytest.raises(ValueError, match="Port must be between"):
            manager.start(str(project_dir), "my-server", 65536)

    def test_start_rejects_duplicate_name(
        self, manager: ServerManager, project_dir: Path
    ):
        """start raises ValueError if name is already in use."""
        # Pre-populate state with an existing server
        state_file = manager._state_file
        existing = [
            ServerInfo(
                name="existing",
                directory=str(project_dir),
                port=8080,
                pid=99999,
                status="running",
            ).to_dict()
        ]
        state_file.write_text(json.dumps(existing))

        with pytest.raises(ValueError, match="already exists"):
            manager.start(str(project_dir), "existing", 9090)

    @patch("functualize_mcp._server_manager.subprocess.Popen")
    def test_start_returns_server_info(
        self, mock_popen: MagicMock, manager: ServerManager, project_dir: Path
    ):
        """start returns a valid ServerInfo on success."""
        mock_process = MagicMock()
        mock_process.pid = 42
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        info = manager.start(str(project_dir), "my-server", 8080)

        assert info.name == "my-server"
        assert info.port == 8080
        assert info.pid == 42
        assert info.status == "running"
        assert info.directory == str(project_dir.resolve())
        assert info.started_at != ""

    @patch("functualize_mcp._server_manager.subprocess.Popen")
    def test_start_persists_state(
        self, mock_popen: MagicMock, manager: ServerManager, project_dir: Path
    ):
        """start persists the server info to disk."""
        mock_process = MagicMock()
        mock_process.pid = 42
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        manager.start(str(project_dir), "my-server", 8080)

        data = json.loads(manager._state_file.read_text())
        assert len(data) == 1
        assert data[0]["name"] == "my-server"
        assert data[0]["pid"] == 42

    @patch("functualize_mcp._server_manager.subprocess.Popen")
    def test_start_raises_on_immediate_exit(
        self, mock_popen: MagicMock, manager: ServerManager, project_dir: Path
    ):
        """start raises RuntimeError if process exits immediately."""
        mock_process = MagicMock()
        mock_process.pid = 42
        mock_process.poll.return_value = 1  # exited with code 1
        mock_process.returncode = 1
        mock_popen.return_value = mock_process

        with pytest.raises(RuntimeError, match="exited immediately"):
            manager.start(str(project_dir), "my-server", 8080)


# ---------------------------------------------------------------------------
# Tests for ServerManager.list
# ---------------------------------------------------------------------------


class TestServerManagerList:
    """Tests for the list method."""

    def test_list_returns_empty_when_no_servers(self, manager: ServerManager):
        """list returns empty list when no servers exist."""
        assert manager.list() == []

    def test_list_returns_persisted_servers(
        self, manager: ServerManager, project_dir: Path
    ):
        """list returns servers from the state file."""
        servers = [
            ServerInfo(
                name="srv1",
                directory=str(project_dir),
                port=8080,
                pid=100,
                status="running",
            ).to_dict(),
            ServerInfo(
                name="srv2",
                directory=str(project_dir),
                port=9090,
                pid=200,
                status="running",
            ).to_dict(),
        ]
        manager._state_file.write_text(json.dumps(servers))

        result = manager.list()
        assert len(result) == 2
        assert result[0].name == "srv1"
        assert result[1].name == "srv2"

    @patch("functualize_mcp._server_manager.os.kill")
    def test_list_updates_status_when_process_dead(
        self, mock_kill: MagicMock, manager: ServerManager, project_dir: Path
    ):
        """list updates status to 'stopped' when process is gone."""
        mock_kill.side_effect = ProcessLookupError("No such process")

        servers = [
            ServerInfo(
                name="dead-server",
                directory=str(project_dir),
                port=8080,
                pid=99999,
                status="running",
            ).to_dict()
        ]
        manager._state_file.write_text(json.dumps(servers))

        result = manager.list()
        assert len(result) == 1
        assert result[0].status == "stopped"

        # Verify state was persisted with updated status
        data = json.loads(manager._state_file.read_text())
        assert data[0]["status"] == "stopped"

    @patch("functualize_mcp._server_manager.os.kill")
    def test_list_keeps_running_status_when_process_alive(
        self, mock_kill: MagicMock, manager: ServerManager, project_dir: Path
    ):
        """list keeps 'running' status when process is alive."""
        mock_kill.return_value = None  # os.kill(pid, 0) succeeds

        servers = [
            ServerInfo(
                name="alive-server",
                directory=str(project_dir),
                port=8080,
                pid=12345,
                status="running",
            ).to_dict()
        ]
        manager._state_file.write_text(json.dumps(servers))

        result = manager.list()
        assert len(result) == 1
        assert result[0].status == "running"


# ---------------------------------------------------------------------------
# Tests for ServerManager.stop
# ---------------------------------------------------------------------------


class TestServerManagerStop:
    """Tests for the stop method."""

    def test_stop_raises_for_unknown_name(self, manager: ServerManager):
        """stop raises ValueError for non-existent server name."""
        with pytest.raises(ValueError, match="No server found"):
            manager.stop("nonexistent")

    @patch("functualize_mcp._server_manager.os.kill")
    def test_stop_terminates_process(
        self, mock_kill: MagicMock, manager: ServerManager, project_dir: Path
    ):
        """stop sends SIGTERM to the server process."""
        # First call is SIGTERM, subsequent calls to check if dead
        mock_kill.side_effect = [None, ProcessLookupError("gone")]

        servers = [
            ServerInfo(
                name="my-server",
                directory=str(project_dir),
                port=8080,
                pid=12345,
                status="running",
            ).to_dict()
        ]
        manager._state_file.write_text(json.dumps(servers))

        manager.stop("my-server")

        # Verify SIGTERM was sent
        mock_kill.assert_any_call(12345, signal.SIGTERM)

    @patch("functualize_mcp._server_manager.os.kill")
    def test_stop_removes_from_state(
        self, mock_kill: MagicMock, manager: ServerManager, project_dir: Path
    ):
        """stop removes the server from the persisted state."""
        mock_kill.side_effect = [None, ProcessLookupError("gone")]

        servers = [
            ServerInfo(
                name="keep-this",
                directory=str(project_dir),
                port=8080,
                pid=111,
                status="running",
            ).to_dict(),
            ServerInfo(
                name="remove-this",
                directory=str(project_dir),
                port=9090,
                pid=222,
                status="running",
            ).to_dict(),
        ]
        manager._state_file.write_text(json.dumps(servers))

        manager.stop("remove-this")

        data = json.loads(manager._state_file.read_text())
        assert len(data) == 1
        assert data[0]["name"] == "keep-this"


# ---------------------------------------------------------------------------
# Tests for ServerManager.stop_all
# ---------------------------------------------------------------------------


class TestServerManagerStopAll:
    """Tests for the stop_all method."""

    @patch("functualize_mcp._server_manager.os.kill")
    def test_stop_all_terminates_all_servers(
        self, mock_kill: MagicMock, manager: ServerManager, project_dir: Path
    ):
        """stop_all sends SIGTERM to all tracked servers."""
        mock_kill.side_effect = [
            None,
            ProcessLookupError("gone"),  # first server SIGTERM + check
            None,
            ProcessLookupError("gone"),  # second server SIGTERM + check
        ]

        servers = [
            ServerInfo(
                name="srv1",
                directory=str(project_dir),
                port=8080,
                pid=111,
                status="running",
            ).to_dict(),
            ServerInfo(
                name="srv2",
                directory=str(project_dir),
                port=9090,
                pid=222,
                status="running",
            ).to_dict(),
        ]
        manager._state_file.write_text(json.dumps(servers))

        manager.stop_all()

        # Verify state is cleared
        data = json.loads(manager._state_file.read_text())
        assert data == []

    def test_stop_all_with_no_servers(self, manager: ServerManager):
        """stop_all does nothing when no servers exist."""
        manager.stop_all()
        # Should not raise

    @patch("functualize_mcp._server_manager.os.kill")
    def test_stop_all_handles_already_dead_processes(
        self, mock_kill: MagicMock, manager: ServerManager, project_dir: Path
    ):
        """stop_all gracefully handles already-terminated processes."""
        mock_kill.side_effect = ProcessLookupError("gone")

        servers = [
            ServerInfo(
                name="dead-srv",
                directory=str(project_dir),
                port=8080,
                pid=99999,
                status="running",
            ).to_dict()
        ]
        manager._state_file.write_text(json.dumps(servers))

        # Should not raise
        manager.stop_all()

        data = json.loads(manager._state_file.read_text())
        assert data == []


# ---------------------------------------------------------------------------
# Tests for state persistence
# ---------------------------------------------------------------------------


class TestServerManagerStatePersistence:
    """Tests for state file loading and saving."""

    def test_load_state_handles_missing_file(self, manager: ServerManager):
        """_load_state returns empty list when file doesn't exist."""
        assert manager._load_state() == []

    def test_load_state_handles_corrupt_json(self, manager: ServerManager):
        """_load_state returns empty list on corrupt JSON."""
        manager._state_file.write_text("not valid json{{{")
        assert manager._load_state() == []

    def test_save_state_creates_directory(self, tmp_path: Path):
        """_save_state creates the state directory if needed."""
        new_dir = tmp_path / "new" / "nested" / "dir"
        mgr = ServerManager(state_dir=new_dir)
        mgr._save_state([])
        assert new_dir.exists()
        assert mgr._state_file.exists()

    @patch("functualize_mcp._server_manager.subprocess.Popen")
    def test_multiple_starts_accumulate(
        self, mock_popen: MagicMock, manager: ServerManager, tmp_path: Path
    ):
        """Multiple start() calls accumulate servers in state."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        dir1 = tmp_path / "project1"
        dir1.mkdir()
        dir2 = tmp_path / "project2"
        dir2.mkdir()

        mock_process.pid = 10
        manager.start(str(dir1), "srv1", 8080)
        mock_process.pid = 20
        manager.start(str(dir2), "srv2", 9090)

        data = json.loads(manager._state_file.read_text())
        assert len(data) == 2
        names = {d["name"] for d in data}
        assert names == {"srv1", "srv2"}
