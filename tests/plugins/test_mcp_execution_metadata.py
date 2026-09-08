"""Every MCP execution door reports the scope it just created.

The defect: an agent called `run_job` on a workflow, received `"Blocked"`, and
had no way to learn which scope was its own. The executor built
`{workflow_scope, workflow_status, blocked_on, blocked_reason}` all along and
every door dropped it at the boundary, so the agent's honest next move was to
list *every* live scope in the project and guess.

These tests drive a real workflow through the real doors. A fake result object
would assert that a dict-copy works, which is not the thing that was broken.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import anyio
import pytest
from functualize_mcp._config import MCPConfig
from functualize_mcp._server import _execute_job
from functualize_mcp._tools import MCPToolRegistry
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.workflow import END, Edge, Gate, Step, workflow

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    yield


class Approval(BaseModel):
    approved: bool


@pytest.fixture
def app() -> FunctualizeApp:
    instance = FunctualizeApp(name="testapp")

    def build() -> str:
        return "artifact-v2"

    @workflow(
        steps=[Step("build"), Gate(name="approve", awaits=Approval)],
        edges=[
            Edge(source="build", target="approve"),
            Edge(source="approve", target=END),
        ],
    )
    def release() -> str:
        return "shipped"

    def plain() -> str:
        return "ok"

    instance.register_dynamic_job("build", build)
    instance.register_dynamic_job("release", release)
    instance.register_dynamic_job("plain", plain)
    return instance


class TestRunJobCarriesTheScopeId:
    """AC-1."""

    async def test_a_blocked_workflow_reports_its_own_scope(self, app) -> None:
        registry = MCPToolRegistry(app, config=MCPConfig())
        result = await registry._run_job("release")

        assert result["status"] == "blocked"
        scope = result["metadata"].get("workflow_scope")
        assert scope, "the agent cannot address the run it just created"
        assert result["metadata"]["workflow_status"] == "blocked"
        assert result["metadata"]["blocked_on"] == "approve"

    async def test_metadata_is_present_even_when_empty(self, app) -> None:
        """A key that appears only sometimes reproduces the defect: a caller
        that must test for its presence will eventually forget to."""
        registry = MCPToolRegistry(app, config=MCPConfig())
        result = await registry._run_job("plain")

        assert "metadata" in result
        assert isinstance(result["metadata"], dict)


class TestEveryDoorAgrees:
    """AC-2, AC-3. `pitfalls.md` §23 — two dispatch paths, one contract."""

    async def test_the_generic_door_and_the_per_job_funnel_agree(self, app) -> None:
        registry = MCPToolRegistry(app, config=MCPConfig())
        generic = await registry._run_job("release")
        funnelled = _execute_job(app, "release", {})

        # Two invocations with no scope id are two *different* runs, so the
        # ids differ by design. What must agree is the shape of the answer —
        # that is what diverged, and what a caller writes code against.
        assert set(generic) == set(funnelled)
        assert generic["status"] == funnelled["status"] == "blocked"
        assert set(generic["metadata"]) == set(funnelled["metadata"])
        assert funnelled["metadata"]["workflow_scope"]
        assert (
            funnelled["metadata"]["workflow_scope"]
            != generic["metadata"]["workflow_scope"]
        ), "two separate runs somehow reported one scope id"

    async def test_status_is_a_string_on_the_funnel(self, app) -> None:
        """`_execute_job` returned the raw Enum object into a JSON dict."""
        result = _execute_job(app, "release", {})
        assert isinstance(result["status"], str)

    async def test_the_wire_value_is_lowercase(self, app) -> None:
        """`docs/guides/mcp.md` says `blocked`; the enum value is `Blocked`."""
        registry = MCPToolRegistry(app, config=MCPConfig())
        assert (await registry._run_job("release"))["status"] == "blocked"
        assert _execute_job(app, "release", {})["status"] == "blocked"

    async def test_async_status_reports_the_same_metadata(self, app) -> None:
        registry = MCPToolRegistry(app, config=MCPConfig())
        started = await registry._run_job_async("release")
        execution_id = started["execution_id"]

        # The worker is an OS thread, so the event loop must actually yield.
        for _ in range(200):
            status = await registry._get_execution_status(execution_id)
            if status["status"] != "running":
                break
            await anyio.sleep(0.02)
        else:  # pragma: no cover - defensive
            pytest.fail("async execution never settled")

        assert status["status"] == "blocked"
        assert status["metadata"]["workflow_scope"]
        assert status["metadata"]["blocked_on"] == "approve"
