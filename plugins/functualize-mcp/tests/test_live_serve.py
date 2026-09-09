"""Capability test: real ``func mcp serve`` over stdio with a grouped project.

Regression guard for probe finding F1 at the production call path: a grouped
parameterized job (dotted functualize name) must register as an MCP tool and
execute end-to-end. Against the pre-fix codegen this test fails at server
boot: ``async def probe.echo(...)`` raises ``SyntaxError`` during tool
registration and the server never serves anything (probe-verified,
`f1-grouped-crash.log`).

Also covers B3 (no banner/update check on boot) indirectly via the unit
assertions in test_server.py — the SDK client cannot capture the child
process's stderr, and the settings mechanism is the deterministic seam.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

JOBS_PY = '''\
"""Grouped jobs exercising the F1 surface: no-arg, typed-arg, internal,
and a docstring that would break naive source interpolation (F1b).
"""
from __future__ import annotations

from functualize.job import job, Log

JOB_GROUP = "probe"


@job
def ping(log: Log) -> str:
    """Return a fixed greeting."""
    log("ping: called")
    return "pong"


@job
def echo(log: Log, text: str) -> str:
    """Echo the text argument back."""
    log(f"echo: called with {text!r}")
    return text


@job(visibility="internal")
def secret(log: Log) -> str:
    """Internal-only — must never appear as a tool."""
    log("secret: called")
    return "hidden"


@job
def quote(log: Log, text: str) -> str:
    """Say: \'\'\' hostile \\\\ docstring with a newline
    spanning two lines."""
    log(f"quote: called with {text!r}")
    return f"'{text}'"
'''


def _server_env(project: Path) -> dict[str, str]:
    """Isolate XDG state so the spawned server touches nothing real."""
    env = dict(os.environ)
    for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
        env[var] = str(project / "xdg" / var.split("_", 1)[1].lower())
    return env


def _tool_property(tool: object, snake: str, camel: str) -> object:
    """Read a tool field tolerating the mcp SDK v2 snake_case rename."""
    for name in (snake, camel):
        if hasattr(tool, name):
            return getattr(tool, name)
    return None


def _run_exercise(project: Path, func_bin: str) -> tuple[list[str], dict]:
    async def exercise() -> tuple[list[str], dict]:
        params = StdioServerParameters(
            command=func_bin,
            args=["--discovery-depth", "1", "mcp", "serve"],
            env=_server_env(project),
            cwd=str(project),
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write, read_timeout_seconds=60) as session,
        ):
            await session.initialize()
            tools = (await session.list_tools()).tools
            result = await session.call_tool("probe.echo", {"text": "hello"})
            text = result.content[0].text
            return [t.name for t in tools], json.loads(text)

    return asyncio.run(exercise())


@pytest.fixture
def func_bin() -> str:
    path = shutil.which("func")
    if not path:
        pytest.skip("func console script not on PATH")
    return path


@pytest.fixture
def grouped_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "jobs.py").write_text(JOBS_PY)
    return project


def test_grouped_project_serves_dotted_tools_and_executes(
    func_bin: str, grouped_project: Path
) -> None:
    names, envelope = _run_exercise(grouped_project, func_bin)

    # B1.1/B1.2: grouped external jobs present under their dotted names.
    assert "probe.ping" in names
    assert "probe.echo" in names
    assert "probe.quote" in names
    # B1.5: internal stays hidden.
    assert "probe.secret" not in names

    # B1.4: envelope round-trip.
    assert envelope["status"] == "Success"
    assert envelope["return_value"] == "hello"


def test_grouped_typed_schema_survives_to_client(
    func_bin: str, grouped_project: Path
) -> None:
    async def exercise() -> None:
        params = StdioServerParameters(
            command=func_bin,
            args=["--discovery-depth", "1", "mcp", "serve"],
            env=_server_env(grouped_project),
            cwd=str(grouped_project),
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write, read_timeout_seconds=60) as session,
        ):
            await session.initialize()
            tools = (await session.list_tools()).tools
            echo = next(t for t in tools if t.name == "probe.echo")
            schema = _tool_property(echo, "input_schema", "inputSchema")
            assert schema is not None
            props = schema.get("properties", {})
            # B1.3: typed argument survives as a string property.
            assert props.get("text") == {"type": "string"}
            assert "text" in schema.get("required", [])
            quote = next(t for t in tools if t.name == "probe.quote")
            assert quote.description.startswith("Say: ''' hostile")

    asyncio.run(exercise())


def test_hostile_description_job_calls_end_to_end(
    func_bin: str, grouped_project: Path
) -> None:
    """F1b: the hostile-docstring job registers AND executes."""

    async def exercise() -> None:
        params = StdioServerParameters(
            command=func_bin,
            args=["--discovery-depth", "1", "mcp", "serve"],
            env=_server_env(grouped_project),
            cwd=str(grouped_project),
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write, read_timeout_seconds=60) as session,
        ):
            await session.initialize()
            result = await session.call_tool("probe.quote", {"text": "hi"})
            envelope = json.loads(result.content[0].text)
            assert envelope["status"] == "Success"
            assert envelope["return_value"] == "'hi'"

    asyncio.run(exercise())
