"""Unit + registration tests for the MCP tool-function codegen.

Regression guards for probe findings F1 and F1b
(research/nooa-functualize-integration/01-probe-transcript.md):

- F1: grouped job names are dotted ("probe.echo"). They used to be compiled
  straight into ``async def {job_name}(...)`` source, which is a SyntaxError,
  killing ``func mcp serve`` for every grouped job with parameters.
- F1b: the tool description was interpolated into that same source inside
  triple quotes, so a description containing ``'''`` broke compilation too.
  Descriptions are now attached as ``__doc__`` after exec.

Both tests fail against the pre-fix codegen (``exec`` raises
``SyntaxError: expected '('``).
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import FastMCP
from functualize_mcp._config import MCPConfig
from functualize_mcp._server import MCPServer, _build_tool_function
from functualize_mcp._translator import MCPToolDef

from tests.conftest import (  # type: ignore[import-not-found]
    FakeApp,
    FakeJobResult,
)

HOSTILE_DESCRIPTION = "Triple ''' quote and backslash \\\\ and a newline\ninside."


def _tool_def(name: str, description: str, schema: dict) -> MCPToolDef:
    return MCPToolDef(
        name=name,
        description=description,
        input_schema=schema,
        annotations={"visibility": "external"},
    )


class RecordingApp(FakeApp):
    """FakeApp that records execute calls for argument-routing assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict]] = []

    def execute(self, job_name: str, **kwargs: object) -> FakeJobResult:
        self.calls.append((job_name, kwargs))
        return super().execute(job_name, **kwargs)


def test_grouped_name_with_params_builds_and_executes() -> None:
    """Dotted grouped name + typed param: builds, keeps dotted name, runs."""
    app = RecordingApp()
    tool_def = _tool_def(
        "probe.echo",
        "Echo text back.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    fn = _build_tool_function("probe.echo", tool_def, app)

    assert fn.__name__ == "probe.echo"
    assert fn.__qualname__ == "probe.echo"
    result = asyncio.run(fn(text="hello"))
    assert result == {
        "status": "success",
        "return_value": "executed probe.echo",
        "duration_ms": 42.0,
    }
    assert app.calls == [("probe.echo", {"group_option_values": None, "text": "hello"})]


def test_grouped_name_without_params_still_builds() -> None:
    """No-params branch (real closure) keeps working for grouped names."""
    app = FakeApp()
    tool_def = _tool_def(
        "probe.ping",
        "Return a greeting.",
        {"type": "object", "properties": {}, "required": []},
    )

    fn = _build_tool_function("probe.ping", tool_def, app)

    assert fn.__name__ == "probe.ping"
    result = asyncio.run(fn())
    assert result["return_value"] == "executed probe.ping"


def test_sanitized_identifier_handles_leading_digit() -> None:
    """A job name starting with a digit gets a valid identifier prefix."""
    app = FakeApp()
    tool_def = _tool_def(
        "1job",
        "Digit-leading name.",
        {
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        },
    )

    fn = _build_tool_function("1job", tool_def, app)

    assert fn.__name__ == "1job"
    assert asyncio.run(fn(x=1))["status"] == "success"


@pytest.mark.parametrize("description", [HOSTILE_DESCRIPTION, "Ordinary."])
def test_hostile_description_does_not_break_codegen(description: str) -> None:
    """F1b: descriptions attach as __doc__, never interpolate into source."""
    app = FakeApp()
    tool_def = _tool_def(
        "probe.quote",
        description,
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    fn = _build_tool_function("probe.quote", tool_def, app)

    assert fn.__doc__ == description
    assert asyncio.run(fn(text="x"))["status"] == "success"


def test_registration_exposes_dotted_tool_name() -> None:
    """FastMCP registers the tool under fn.__name__: the dotted job name."""
    app = FakeApp()
    tool_def = _tool_def(
        "probe.echo",
        "Echo text back.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    fn = _build_tool_function("probe.echo", tool_def, app)

    server = FastMCP(name="test-server")
    server.add_tool(fn)

    tools = asyncio.run(server.list_tools())
    names = [t.name for t in tools]
    assert "probe.echo" in names
    tool = next(t for t in tools if t.name == "probe.echo")
    assert tool.description == "Echo text back."
    props = tool.parameters.get("properties", {})
    assert props.get("text") == {"type": "string"}
    assert "text" in tool.parameters.get("required", [])


def test_internal_visibility_metadata_never_reaches_function() -> None:
    """Visibility filtering happens upstream; codegen ignores annotations."""
    app = FakeApp()
    tool_def = _tool_def(
        "probe.secret",
        "Hidden.",
        {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": [],
        },
    )

    fn = _build_tool_function("probe.secret", tool_def, app)

    # Codegen is annotation-agnostic — the translator filters internal jobs
    # before this function is ever called. Build must simply not raise.
    assert fn.__name__ == "probe.secret"


# ── F2: FastMCP update check + banner defaults ──────────────────────────


def test_constructor_sets_fastmcp_defaults_when_env_absent(monkeypatch) -> None:
    """No FASTMCP_* env: the plugin defaults both knobs off.

    `check_for_newer_version` returns None before any HTTP when the setting
    is "off" (fastmcp.utilities.version_check), so this is the egress seam:
    default boots never touch pypi.org.
    """
    import fastmcp

    monkeypatch.delenv("FASTMCP_CHECK_FOR_UPDATES", raising=False)
    monkeypatch.delenv("FASTMCP_SHOW_SERVER_BANNER", raising=False)
    # Force a non-default baseline so the constructor's set is observable;
    # monkeypatch restores the process-global after the test.
    monkeypatch.setattr(fastmcp.settings, "check_for_updates", "stable")
    monkeypatch.setattr(fastmcp.settings, "show_server_banner", True)

    MCPServer(app=FakeApp(), config=MCPConfig())

    assert fastmcp.settings.check_for_updates == "off"
    assert fastmcp.settings.show_server_banner is False


def test_constructor_respects_operator_env(monkeypatch) -> None:
    """FASTMCP_* env present: the plugin must not clobber operator choice."""
    import fastmcp

    monkeypatch.setenv("FASTMCP_CHECK_FOR_UPDATES", "stable")
    monkeypatch.setenv("FASTMCP_SHOW_SERVER_BANNER", "true")
    baseline_updates = fastmcp.settings.check_for_updates
    baseline_banner = fastmcp.settings.show_server_banner

    MCPServer(app=FakeApp(), config=MCPConfig())

    assert fastmcp.settings.check_for_updates == baseline_updates
    assert fastmcp.settings.show_server_banner == baseline_banner
