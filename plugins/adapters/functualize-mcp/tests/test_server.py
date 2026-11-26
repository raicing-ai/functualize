"""Unit + registration tests for the per-job MCP tool.

Regression guards for probe findings F1 and F1b
(research/nooa-functualize-integration/01-probe-transcript.md):

- F1: grouped job names are dotted ("probe.echo"). They used to be compiled
  straight into ``async def {job_name}(...)`` source, which is a SyntaxError,
  killing ``func mcp serve`` for every grouped job with parameters.
- F1b: the tool description was interpolated into that same source inside
  triple quotes, so a description containing ``'''`` broke compilation too.

No source is generated any more: a job is a ``JobTool`` whose ``parameters``
is the job's published schema (contracts.md §6), so neither name nor
description reaches a compiler. The guards stay, because they are the cases
that broke ``func mcp serve`` before.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastmcp import FastMCP
from functualize_mcp._config import MCPConfig
from functualize_mcp._server import JobTool, MCPServer
from functualize_mcp._translator import MCPToolDef

from functualize._primitives.run_store import RunStore
from functualize.app.core import FunctualizeApp
from tests.conftest import (  # type: ignore[import-not-found]
    FakeApp,
    FakeJobResult,
)

HOSTILE_DESCRIPTION = "Triple ''' quote and backslash \\\\ and a newline\ninside."


def _call(tool: JobTool, **arguments: Any) -> Any:
    """Run ``tool`` as FastMCP does and return its result."""
    return asyncio.run(tool.run(arguments))


def test_generated_mcp_run_tool_records_project_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "mcp-tool"
    project.mkdir()
    (project / ".functualize.toml").write_text('[run]\ntags = ["door:mcp"]\n')
    monkeypatch.chdir(project)
    app = FunctualizeApp("mcp-tool")

    def greet() -> str:
        return "hello"

    app.register_dynamic_job("greet", greet)
    tool = JobTool.for_job(
        _tool_def("greet", "Greet.", {"type": "object", "properties": {}}), app
    )
    result = _call(tool)

    assert result.is_error is False
    assert result.structured_content["status"] == "success"
    store = RunStore(app.execution_engine._state_store().substrate)
    records = [store.get_run(run_id) for run_id in store.run_ids()]
    assert [record["run_tags"] for record in records if record] == [{"door": "mcp"}]


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
        self.calls: list[tuple[str, dict, dict | None]] = []

    def execute(self, request: object) -> FakeJobResult:
        # (name, job kwargs, group options) — three things, because on this
        # branch they *are* three things. `app.execute` used to take
        # `(job_name, **kwargs)`, so a group option arrived flattened in among
        # the job's own arguments; the request keeps them in separate fields
        # (run-request-entry/T15), which is what the assertions below now pin.
        self.calls.append(
            (
                request.job_name,  # type: ignore[attr-defined]
                dict(request.kwargs),  # type: ignore[attr-defined]
                request.group_option_values,  # type: ignore[attr-defined]
            )
        )
        return super().execute(request)


def test_grouped_name_with_params_builds_and_executes() -> None:
    """Dotted grouped name + typed param: registers under the dotted name, runs."""
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

    tool = JobTool.for_job(tool_def, app)

    assert tool.name == "probe.echo"
    result = _call(tool, text="hello").structured_content
    # Envelope contract on the served surface (master post-#35): status,
    # return_value, duration_ms. Assert the stable keys, not incidental
    # extra fields (upstream added metadata without breaking anything).
    assert result["status"] == "success"
    assert result["return_value"] == "executed probe.echo"
    assert result["duration_ms"] == 42.0
    # The job's own argument, and nothing else, in `kwargs`; group options
    # have their own field, so the job cannot receive one by accident.
    assert app.calls == [("probe.echo", {"text": "hello"}, None)]


def test_group_options_route_to_their_own_field() -> None:
    """A property the translator marked as inherited travels as a group layer."""
    app = RecordingApp()
    tool_def = MCPToolDef(
        name="probe.echo",
        description="Echo.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}, "env": {"type": "string"}},
        },
        group_option_names=frozenset({"env"}),
    )

    _call(JobTool.for_job(tool_def, app), text="hi", env="prod")

    assert app.calls == [("probe.echo", {"text": "hi"}, {"env": "prod"})]


def test_grouped_name_without_params_still_builds() -> None:
    """A job with no parameters registers and runs under a grouped name."""
    app = FakeApp()
    tool_def = _tool_def(
        "probe.ping",
        "Return a greeting.",
        {"type": "object", "properties": {}, "required": []},
    )

    tool = JobTool.for_job(tool_def, app)

    assert tool.name == "probe.ping"
    assert _call(tool).structured_content["return_value"] == "executed probe.ping"


def test_a_leading_digit_name_registers() -> None:
    """A job name starting with a digit needs no identifier: nothing is compiled."""
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

    tool = JobTool.for_job(tool_def, app)

    assert tool.name == "1job"
    assert _call(tool, x=1).structured_content["status"] == "success"


@pytest.mark.parametrize("description", [HOSTILE_DESCRIPTION, "Ordinary."])
def test_hostile_description_is_carried_verbatim(description: str) -> None:
    """F1b: the description is data on the tool, never source."""
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

    tool = JobTool.for_job(tool_def, app)

    assert tool.description == description
    assert _call(tool, text="x").structured_content["status"] == "success"


def test_registration_publishes_the_schema_as_given() -> None:
    """FastMCP lists the tool under the dotted job name with the job's schema."""
    app = FakeApp()
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "level": {"type": "integer", "enum": [1, 2]},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["text"],
    }
    server = FastMCP(name="test-server")
    server.add_tool(
        JobTool.for_job(_tool_def("probe.echo", "Echo text back.", schema), app)
    )

    tools = asyncio.run(server.list_tools())
    tool = next(t for t in tools if t.name == "probe.echo")
    assert tool.description == "Echo text back."
    assert tool.parameters == schema


@pytest.mark.parametrize(
    ("status", "error"),
    [("invalid", "Missing required argument 'text'"), ("failure", "boom")],
)
def test_a_refused_or_failed_run_is_an_error_with_its_reason(
    status: str, error: str
) -> None:
    """contracts.md §6: a refused call and a failed run are ``isError: true``."""

    class Refusing(FakeApp):
        def execute(self, request: object) -> FakeJobResult:
            result = FakeJobResult(status=status)
            result.exception = RuntimeError(error)  # type: ignore[attr-defined]
            return result

    tool = JobTool.for_job(
        _tool_def("probe.echo", "Echo.", {"type": "object", "properties": {}}),
        Refusing(),
    )
    result = _call(tool)

    assert result.is_error is True
    assert result.structured_content["error"] == error
    assert error in result.content[0].text


def test_an_accepted_call_is_not_an_error() -> None:
    tool = JobTool.for_job(
        _tool_def("probe.ping", "Ping.", {"type": "object", "properties": {}}),
        FakeApp(),
    )
    result = _call(tool)

    assert result.is_error is False
    assert "error" not in result.structured_content


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
