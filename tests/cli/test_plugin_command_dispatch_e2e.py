"""End-to-end subprocess tests for plugin command dispatch from ``func``.

Exercises the full ``main()`` pipeline (pre-boot classification → routing →
handler → post-boot plugin dispatch) via ``uv run func`` in a temp project,
using the real installed ``mcp`` plugin. Marked slow (subprocess + full boot).

Complements the in-process tests in ``test_plugin_command_dispatch.py``, which
call the handlers directly and so skip ``detect_mode``/``main`` routing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _write_project(tmp_path: Path) -> Path:
    (tmp_path / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\n', encoding="utf-8"
    )
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "greet.py").write_text(
        'def greet(name: str = "World") -> None:\n'
        '    """Say hello."""\n'
        '    print(f"Hello, {name}!")\n',
        encoding="utf-8",
    )
    return tmp_path


def _run_func(
    *args: str, cwd: str | Path, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=timeout,
    )


@pytest.fixture(autouse=True)
def _require_mcp() -> None:
    pytest.importorskip("functualize_mcp")


class TestMcpDispatchE2E:
    def test_func_mcp_lists_commands(self, tmp_path: Path) -> None:
        proj = _write_project(tmp_path)
        result = _run_func("mcp", cwd=proj)
        assert result.returncode == 0, result.stderr
        for cmd in ("serve", "tools", "schema", "start", "list", "stop"):
            assert cmd in result.stdout

    def test_func_mcp_tools_cold(self, tmp_path: Path) -> None:
        """Cold boot (no cache): `func mcp tools` lists the job as a tool."""
        proj = _write_project(tmp_path)
        assert not (proj / ".functualize_cache.json").exists()
        result = _run_func("mcp", "tools", cwd=proj)
        assert result.returncode == 0, result.stderr
        assert "greet" in result.stdout

    def test_func_mcp_tools_after_warm_job_run(self, tmp_path: Path) -> None:
        """Running a job first (warming discovery) must not hide `func mcp`."""
        proj = _write_project(tmp_path)
        warm = _run_func("greet", "--name", "Bob", cwd=proj)
        assert warm.returncode == 0, warm.stderr
        result = _run_func("mcp", "tools", cwd=proj)
        assert result.returncode == 0, result.stderr
        assert "greet" in result.stdout

    def test_func_mcp_serve_help(self, tmp_path: Path) -> None:
        """`func mcp serve --help` exits 0 without binding a server."""
        proj = _write_project(tmp_path)
        result = _run_func("mcp", "serve", "--help", cwd=proj)
        assert result.returncode == 0, result.stderr
        assert "--http" in result.stdout
