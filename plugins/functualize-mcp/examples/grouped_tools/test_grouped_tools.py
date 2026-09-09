"""Live harness for the grouped_tools example: the served surface, not the
job functions.

Spawns a real `func mcp serve` over the example project and drives it with an
MCP stdio client, asserting the contracts an agent would observe:

- grouped external jobs appear as tools under their dotted full names
  (`probe.echo`, not `echo`);
- a typed argument survives into the tool's input schema;
- `visibility="internal"` jobs never appear;
- calling a tool round-trips the functualize result envelope;
- a docstring containing triple quotes and backslashes (the source-injection
  regression) neither breaks registration nor corrupts the description.

This harness doubles as the regression gate for the codegen fix: before it,
the server died during tool registration with
`SyntaxError: expected '('` on `async def probe.echo(...)`.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

EXAMPLE_DIR = Path(__file__).resolve().parent

_XDG_BASE: Path | None = None


@pytest.fixture(scope="module", autouse=True)
def _xdg_base() -> None:
    """XDG isolation lives in a temp dir, never inside the example."""
    global _XDG_BASE
    with tempfile.TemporaryDirectory(prefix="functualize-mcp-grouped-") as tmp:
        _XDG_BASE = Path(tmp)
        yield


def _env() -> dict[str, str]:
    assert _XDG_BASE is not None, "xdg fixture not initialized"
    env = dict(os.environ)
    for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
        env[var] = str(_XDG_BASE / var.split("_", 1)[1].lower())
    return env


@pytest.fixture
def func_bin() -> str:
    path = shutil.which("func")
    if not path:
        pytest.skip("func console script not on PATH")
    return path


def _tools_and_call(
    func_bin: str, tool: str, arguments: dict[str, str] | None
) -> tuple[list[object], str]:
    async def exercise() -> tuple[list[object], str]:
        params = StdioServerParameters(
            command=func_bin,
            args=["--discovery-depth", "1", "mcp", "serve"],
            env=_env(),
            cwd=str(EXAMPLE_DIR),
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write, read_timeout_seconds=60) as session,
        ):
            await session.initialize()
            tools = (await session.list_tools()).tools
            result = await session.call_tool(tool, arguments or {})
            return tools, result.content[0].text

    return asyncio.run(exercise())


def test_grouped_external_jobs_are_served_under_dotted_names(
    func_bin: str,
) -> None:
    tools, _ = _tools_and_call(func_bin, "probe.ping", None)
    names = [t.name for t in tools]

    assert "probe.ping" in names
    assert "probe.echo" in names
    assert "probe.quote" in names
    assert "probe.secret" not in names


def test_typed_argument_survives_in_tool_schema(func_bin: str) -> None:
    tools, _ = _tools_and_call(func_bin, "probe.echo", {"text": "schema"})
    echo = next(t for t in tools if t.name == "probe.echo")
    schema = getattr(echo, "input_schema", None) or getattr(echo, "inputSchema", None)
    assert schema is not None
    assert schema.get("properties", {}).get("text") == {"type": "string"}
    assert "text" in schema.get("required", [])


def test_no_arg_job_round_trips_envelope(func_bin: str) -> None:
    _, text = _tools_and_call(func_bin, "probe.ping", None)
    envelope = json.loads(text)
    assert envelope["status"] == "Success"
    assert envelope["return_value"] == "pong"


def test_typed_job_round_trips_envelope(func_bin: str) -> None:
    _, text = _tools_and_call(func_bin, "probe.echo", {"text": "hello from mcp"})
    envelope = json.loads(text)
    assert envelope["status"] == "Success"
    assert envelope["return_value"] == "hello from mcp"


def test_hostile_docstring_job_serves_with_description_intact(
    func_bin: str,
) -> None:
    tools, text = _tools_and_call(func_bin, "probe.quote", {"text": "hi"})
    quote = next(t for t in tools if t.name == "probe.quote")
    assert quote.description.startswith("Wrap text in quotes.")
    envelope = json.loads(text)
    assert envelope["status"] == "Success"
    assert envelope["return_value"] == "'hi'"
