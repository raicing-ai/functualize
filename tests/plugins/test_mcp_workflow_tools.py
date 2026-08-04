"""Tests for WorkflowToolProvider — MCP tools over persisted workflow scopes.

Every scope these tests inspect is produced by *running a real workflow through
the engine*. The previous version of this file built `FakeScope`/`FakeStep`
duck-types by hand, which is why it passed unchanged through a breaking change
to the `Step` vocabulary: the fakes had no relationship to the real nodes, so
they could not notice that production code was reading an attribute that no
longer existed. Driving the real engine is what makes these tests able to fail.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from functualize_mcp._workflow_tools import WorkflowToolProvider
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.app.utils import StateStore
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
    """Each test gets its own state file, resolved from a fresh cwd."""
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    yield


class TripPreferences(BaseModel):
    budget: str
    nights: int = 2


class Approval(BaseModel):
    approved: bool


def _store() -> StateStore:
    return StateStore.for_project(Path.cwd())


def _gated_app(calls: list[str] | None = None) -> FunctualizeApp:
    """An app with one workflow that blocks at a gate between two steps."""
    seen = calls if calls is not None else []
    app = FunctualizeApp(name="testapp")

    def forecast() -> str:
        seen.append("forecast")
        return "sunny"

    def travel_plan() -> str:
        seen.append("travel_plan")
        return "packed"

    @workflow(
        steps=[
            Step("forecast"),
            Gate(name="preferences", awaits=TripPreferences, tools=["forecast"]),
            Step("travel_plan"),
        ],
        edges=[
            Edge(source="forecast", target="preferences"),
            Edge(source="preferences", target="travel_plan"),
            Edge(source="travel_plan", target=END),
        ],
    )
    def trip_planner() -> str:
        seen.append("body")
        return "itinerary"

    app.register_dynamic_job("forecast", forecast)
    app.register_dynamic_job("travel_plan", travel_plan)
    app.register_dynamic_job("trip_planner", trip_planner)
    return app


def _provider(app: FunctualizeApp) -> WorkflowToolProvider:
    return WorkflowToolProvider(app, store=_store())


class TestGetWorkflowState:
    async def test_unknown_scope_is_an_error(self) -> None:
        result = await _provider(_gated_app())._get_workflow_state("nope")
        assert result["error"] == "workflow_not_found"

    async def test_a_blocked_scope_reports_its_graph_and_progress(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")

        state = await _provider(app)._get_workflow_state("run-1")

        assert state["workflow"] == "trip_planner"
        assert state["status"] == "blocked"
        assert state["current_position"] == "preferences"
        # Full records, not just names: an agent that can see a step ran but
        # not what it produced has to be told the run's own results out of band.
        assert state["results"]["forecast"]["status"] == "success"
        assert state["results"]["forecast"]["return_value"] == "sunny"

    async def test_the_graph_comes_from_the_cached_shape(self) -> None:
        """Topology is reported without importing the declaring module — the
        same projection discovery caches."""
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")

        state = await _provider(app)._get_workflow_state("run-1")

        assert state["steps"] == [
            {"step": "forecast"},
            {"gate": "preferences", "model": "TripPreferences"},
            {"step": "travel-plan"},
        ]
        assert {"from": "forecast", "to": "preferences"} in state["edges"]

    async def test_a_pending_gate_carries_what_an_agent_needs(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")

        state = await _provider(app)._get_workflow_state("run-1")

        assert len(state["pending_gates"]) == 1
        gate = state["pending_gates"][0]
        assert gate["gate"] == "preferences"
        assert gate["model"] == "TripPreferences"
        # `budget` has no default and so must be supplied; `nights` does.
        assert gate["unresolved_fields"] == ["budget"]
        # A tool is a job: the entry carries what the agent needs to call it,
        # not just a name it would have to look up separately.
        assert [t["tool"] for t in gate["tools"]] == ["forecast"]
        assert gate["tools"][0]["bound"] == []
        assert gate["workflow_context"]["workflow"] == "trip_planner"

    async def test_an_answered_gate_is_no_longer_pending(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")
        _store().deposit_gate_payload("run-1", "preferences", {"budget": "high"})

        state = await _provider(app)._get_workflow_state("run-1")
        assert state["pending_gates"] == []

    async def test_a_completed_scope_reports_completed(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")
        _store().deposit_gate_payload("run-1", "preferences", {"budget": "high"})
        app.execute("trip_planner", scope_id="run-1")

        state = await _provider(app)._get_workflow_state("run-1")

        assert state["status"] == "completed"
        # The answered gate is recorded alongside both steps.
        assert sorted(state["results"]) == ["forecast", "preferences", "travel-plan"]
        assert state["results"]["travel-plan"]["return_value"] == "packed"
        assert state["pending_gates"] == []


class TestListActiveWorkflows:
    async def test_no_scopes_lists_nothing(self) -> None:
        result = await _provider(_gated_app())._list_active_workflows()
        assert result["workflows"] == []

    async def test_blocked_scopes_are_listed(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")
        app.execute("trip_planner", scope_id="run-2")

        result = await _provider(app)._list_active_workflows()

        assert {w["workflow_id"] for w in result["workflows"]} == {"run-1", "run-2"}

    async def test_finished_scopes_are_omitted(self) -> None:
        """The point of the tool is finding work that needs a human or an
        agent — a completed scope is noise."""
        app = _gated_app()
        app.execute("trip_planner", scope_id="done")
        _store().deposit_gate_payload("done", "preferences", {"budget": "high"})
        app.execute("trip_planner", scope_id="done")
        app.execute("trip_planner", scope_id="still-blocked")

        result = await _provider(app)._list_active_workflows()

        ids = [w["workflow_id"] for w in result["workflows"]]
        assert ids == ["still-blocked"]


class TestResumeGate:
    async def test_valid_input_is_accepted_and_deposited(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")

        result = await _provider(app)._resume_gate("preferences", {"budget": "high"})

        assert result["status"] == "input_accepted"
        assert result["workflow_id"] == "run-1"
        gate = _store().get_gate("run-1", "preferences")
        assert gate is not None
        assert gate["payload"] == {"budget": "high"}

    async def test_accepting_input_does_not_run_the_workflow(self) -> None:
        """Resume is replay: the deposit fills a slot, the caller runs the job.

        If this tool ran the workflow itself, an agent depositing input would
        block on the whole remaining graph inside one MCP call.
        """
        calls: list[str] = []
        app = _gated_app(calls)
        app.execute("trip_planner", scope_id="run-1")
        calls.clear()

        await _provider(app)._resume_gate("preferences", {"budget": "high"})

        assert calls == []

    async def test_the_deposit_is_what_actually_unblocks_the_run(self) -> None:
        """The end-to-end claim: deposit, then invoke, and the walk continues."""
        calls: list[str] = []
        app = _gated_app(calls)
        app.execute("trip_planner", scope_id="run-1")
        await _provider(app)._resume_gate("preferences", {"budget": "high"})

        result = app.execute("trip_planner", scope_id="run-1")

        assert result.return_value == "itinerary"
        assert calls == ["forecast", "travel_plan", "body"]

    async def test_invalid_input_is_rejected_and_deposits_nothing(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")

        result = await _provider(app)._resume_gate("preferences", {"nights": 3})

        assert result["error"] == "validation_error"
        gate = _store().get_gate("run-1", "preferences")
        assert gate is not None
        assert gate["payload"] is None

    async def test_a_rejected_deposit_leaves_the_run_blocked(self) -> None:
        """Not merely "payload stays None" — the workflow must still block."""
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")
        await _provider(app)._resume_gate("preferences", {"nights": 3})

        again = app.execute("trip_planner", scope_id="run-1")
        assert again.status.resumable

    async def test_wrong_type_is_a_validation_error(self) -> None:
        """Validation is the real model, not a required-keys check — a schema
        walk would accept this."""
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")

        result = await _provider(app)._resume_gate(
            "preferences", {"budget": "high", "nights": "not-a-number"}
        )
        assert result["error"] == "validation_error"

    async def test_an_unknown_gate_lists_the_real_ones(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")

        result = await _provider(app)._resume_gate("typo", {"budget": "high"})

        assert result["error"] == "gate_not_found"
        assert [g["gate"] for g in result["pending_gates"]] == ["preferences"]

    async def test_the_same_gate_in_two_scopes_is_ambiguous(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")
        app.execute("trip_planner", scope_id="run-2")

        result = await _provider(app)._resume_gate("preferences", {"budget": "high"})

        assert result["error"] == "ambiguous_gate"
        assert sorted(result["workflow_ids"]) == ["run-1", "run-2"]

    async def test_an_already_answered_gate_is_not_found(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")
        _store().deposit_gate_payload("run-1", "preferences", {"budget": "high"})

        result = await _provider(app)._resume_gate("preferences", {"budget": "low"})
        assert result["error"] == "gate_not_found"


class TestResumeWorkflow:
    async def test_scope_addressed_deposit_works(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")

        result = await _provider(app)._resume_workflow("run-1", {"budget": "high"})

        assert result["status"] == "input_accepted"
        assert result["gate"] == "preferences"

    async def test_it_disambiguates_where_resume_gate_cannot(self) -> None:
        """Two scopes blocked on the same gate: naming the scope resolves it."""
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")
        app.execute("trip_planner", scope_id="run-2")

        result = await _provider(app)._resume_workflow("run-2", {"budget": "high"})

        assert result["status"] == "input_accepted"
        store = _store()
        untouched = store.get_gate("run-1", "preferences")
        assert untouched is not None
        assert untouched["payload"] is None
        answered = store.get_gate("run-2", "preferences")
        assert answered is not None
        assert answered["payload"] == {"budget": "high"}

    async def test_unknown_scope_is_an_error(self) -> None:
        result = await _provider(_gated_app())._resume_workflow("nope", {})
        assert result["error"] == "workflow_not_found"

    async def test_a_scope_with_no_pending_gate_is_not_paused(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")
        _store().deposit_gate_payload("run-1", "preferences", {"budget": "high"})
        app.execute("trip_planner", scope_id="run-1")

        result = await _provider(app)._resume_workflow("run-1", {"budget": "low"})
        assert result["error"] == "workflow_not_paused"

    async def test_invalid_input_is_rejected(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")

        result = await _provider(app)._resume_workflow("run-1", {"nights": 1})
        assert result["error"] == "validation_error"

    async def test_multiple_pending_gates_are_ambiguous(self) -> None:
        """A fan-out can leave two gates unanswered at once; the scope id is
        then not a unique address and the caller must name the gate."""
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")

        _store().put_gate(
            "run-1",
            "sign_off",
            {
                "model": "Approval",
                "input_schema": Approval.model_json_schema(),
                "tools": [],
                "payload": None,
                "blocked_at": "",
            },
        )

        result = await _provider(app)._resume_workflow("run-1", {"budget": "high"})

        assert result["error"] == "ambiguous_gate"
        assert sorted(result["pending_gates"]) == ["preferences", "sign_off"]


class TestCancelWorkflow:
    async def test_a_blocked_scope_can_be_cancelled(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")

        result = await _provider(app)._cancel_workflow("run-1")

        assert result["status"] == "cancelled"
        scope = _store().get_scope("run-1")
        assert scope is not None
        assert scope["status"] == "cancelled"

    async def test_a_cancelled_scope_drops_out_of_the_active_list(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")
        await _provider(app)._cancel_workflow("run-1")

        result = await _provider(app)._list_active_workflows()
        assert result["workflows"] == []

    async def test_cancelling_twice_is_an_error(self) -> None:
        app = _gated_app()
        app.execute("trip_planner", scope_id="run-1")
        provider = _provider(app)
        await provider._cancel_workflow("run-1")

        result = await provider._cancel_workflow("run-1")
        assert result["error"] == "workflow_not_active"

    async def test_unknown_scope_is_an_error(self) -> None:
        result = await _provider(_gated_app())._cancel_workflow("nope")
        assert result["error"] == "workflow_not_found"


class TestRegistration:
    def test_every_tool_is_registered(self) -> None:
        registered: list[str] = []

        class FakeMCP:
            def add_tool(self, fn: object) -> None:
                registered.append(fn.__name__)  # type: ignore[attr-defined]

        _provider(_gated_app()).register_tools(FakeMCP())

        assert registered == [
            "get_workflow_state",
            "list_active_workflows",
            "resume_gate",
            "resume_workflow",
            "call_gate_tool",
            "cancel_workflow",
        ]

    async def test_the_mcp_server_registers_the_workflow_tools(self) -> None:
        """The defect this guards: the provider existed and was fully tested
        while no MCP server ever instantiated it, so none of these tools were
        reachable over MCP at all.
        """
        from functualize_mcp._config import MCPConfig
        from functualize_mcp._server import MCPServer

        server = MCPServer(_gated_app(), config=MCPConfig())
        server._register_tools()

        names = {tool.name for tool in await server._mcp.list_tools()}
        assert {"get_workflow_state", "resume_gate", "cancel_workflow"} <= names


class TestTopologyFallback:
    """D2-b / F3: a workflow declared inside a **plugin** reports its real graph.

    `descriptor.workflow` (the cached shape) is written only by directory
    discovery. A `JobProvider` builds descriptors by hand and has no public
    projection to populate it (`workflow_shape_of` is internal), so the field is
    None and `_topology` used to report `{"steps": [], "edges": []}` over MCP —
    an agent could advance a workflow it could not see. The fix reads the live
    declaration on `descriptor.function` when the cached shape is absent.

    These use a real `JobDescriptor` with a real `@workflow` function — the same
    objects a provider yields, not a duck-typed fake.
    """

    def _provider_flow_descriptor(self):
        from functualize._types.descriptors import JobDescriptor

        @workflow(
            steps=[Step("a"), Step("b")],
            edges=[Edge(source="a", target="b"), Edge(source="b", target=END)],
        )
        def plugin_flow() -> str:
            return "done"

        # group is required positionally; a provider sets it explicitly.
        return JobDescriptor(name="plugin-flow", group=None, function=plugin_flow)

    class _AppReturning:
        def __init__(self, descriptor) -> None:
            self._descriptor = descriptor

        def get_job(self, name: str):
            return self._descriptor if name == "plugin-flow" else None

    def test_provider_workflow_reports_its_real_graph(self) -> None:
        descriptor = self._provider_flow_descriptor()
        assert descriptor.workflow is None, "premise: provider cannot cache the shape"

        provider = WorkflowToolProvider(self._AppReturning(descriptor), store=_store())
        topo = provider._topology("plugin-flow")

        assert topo["steps"] == [{"step": "a"}, {"step": "b"}]
        assert {"from": "a", "to": "b"} in topo["edges"]
        assert {"from": "b", "to": None} in topo["edges"]

    def test_cached_shape_still_wins_when_present(self) -> None:
        """The directory-scanned path is untouched: a present cached shape is
        used verbatim, and the live function is never consulted."""
        descriptor = self._provider_flow_descriptor()
        from functualize._types.workflow import workflow_shape_of

        # Simulate a directory-scanned descriptor: cached shape populated.
        object.__setattr__(
            descriptor, "workflow", workflow_shape_of(descriptor.function)
        )
        # And a function that would raise if the fallback were reached.
        object.__setattr__(descriptor, "function", None)

        provider = WorkflowToolProvider(self._AppReturning(descriptor), store=_store())
        topo = provider._topology("plugin-flow")
        assert topo["steps"] == [{"step": "a"}, {"step": "b"}]

    def test_unknown_job_is_empty_not_an_error(self) -> None:
        """A scope outliving its declaration still renders, never raises."""
        provider = WorkflowToolProvider(self._AppReturning(None), store=_store())
        assert provider._topology("gone") == {"steps": [], "edges": []}

    def test_a_job_with_no_workflow_is_empty_not_an_error(self) -> None:
        from functualize._types.descriptors import JobDescriptor

        def plain() -> str:
            return "x"

        descriptor = JobDescriptor(name="plain", group=None, function=plain)
        provider = WorkflowToolProvider(self._AppReturning(descriptor), store=_store())
        assert provider._topology("plain") == {"steps": [], "edges": []}
