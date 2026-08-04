"""`Tool(job, **bound)` — narrowing a gate's offered jobs.

Ratified 2026-07-20 (resolved question 17). A tool *is* a registered job; a
`Tool` adds the one thing a job's own signature cannot express, because it is a
property of the usage rather than the job: which of its arguments this gate
fixes. The same `issue_refund` may be capped at $50 in a self-serve workflow
and uncapped in a supervisor one.

The narrowing is a **schema transform**, not a label. A pinned argument is
removed from what the agent is shown, so the forbidden call is inexpressible
rather than merely refused. If these tests only checked that a bad call is
rejected, they would pass against a design where the agent still sees the
parameter and gets an error — which is a materially weaker guarantee.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path

import pytest
from functualize_mcp._config import MCPConfig
from functualize_mcp._tools import MCPToolRegistry
from functualize_mcp._workflow_tools import GateToolPolicy, WorkflowToolProvider
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.app.utils import StateStore
from functualize.workflow import END, Edge, Gate, Step, Tool, workflow


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


class RefundDecision(BaseModel):
    approve: bool


def _store() -> StateStore:
    return StateStore.for_project(Path.cwd())


def _app(tools: list) -> FunctualizeApp:
    app = FunctualizeApp(name="refunds")
    calls: list[tuple[str, dict]] = []

    def load_ticket() -> str:
        return "ticket-9"

    def order_history(customer_id: str = "") -> str:
        calls.append(("order_history", {"customer_id": customer_id}))
        return "3 orders"

    def issue_refund(
        order_id: str = "", amount_cents: int = 0, cap_cents: int = 0
    ) -> str:
        calls.append(
            ("issue_refund", {"amount_cents": amount_cents, "cap_cents": cap_cents})
        )
        return f"refunded {min(amount_cents, cap_cents)}"

    def close_ticket() -> str:
        return "closed"

    @workflow(
        steps=[
            Step("load_ticket"),
            Gate(name="approval", awaits=RefundDecision, tools=tools),
            Step("close_ticket"),
        ],
        edges=[
            Edge(source="load_ticket", target="approval"),
            Edge(source="approval", target="close_ticket"),
            Edge(source="close_ticket", target=END),
        ],
    )
    def refund_request() -> str:
        return "done"

    for name, fn in [
        ("load_ticket", load_ticket),
        ("order_history", order_history),
        ("issue_refund", issue_refund),
        ("close_ticket", close_ticket),
        ("refund_request", refund_request),
    ]:
        app.register_dynamic_job(name, fn)
    app.calls = calls  # type: ignore[attr-defined]
    return app


def _blocked(tools: list) -> tuple[FunctualizeApp, WorkflowToolProvider]:
    app = _app(tools)
    app.execute("refund_request", scope_id="run-1")
    app.calls.clear()  # type: ignore[attr-defined]
    return app, WorkflowToolProvider(app, store=_store())


class TestDeclaration:
    def test_a_bare_reference_needs_no_wrapper(self) -> None:
        gate = Gate(name="g", awaits=RefundDecision, tools=["order_history"])
        assert [t.name for t in gate.tool_specs()] == ["order-history"]
        assert gate.tool_specs()[0].bound == {}

    def test_a_callable_reference_resolves_to_its_job_name(self) -> None:
        def order_history() -> None: ...

        gate = Gate(name="g", awaits=RefundDecision, tools=[order_history])
        assert gate.tool_specs()[0].name == "order-history"

    def test_bound_arguments_are_captured(self) -> None:
        tool = Tool("issue_refund", cap_cents=5000)
        assert tool.name == "issue-refund"
        assert tool.bound == {"cap_cents": 5000}

    def test_a_job_parameter_named_job_can_still_be_bound(self) -> None:
        """`job` is positional-only, so it does not shadow a bound argument."""
        tool = Tool("scheduler", job="nightly")
        assert tool.name == "scheduler"
        assert tool.bound == {"job": "nightly"}

    def test_a_tool_is_immutable(self) -> None:
        tool = Tool("issue_refund", cap_cents=5000)
        with pytest.raises(AttributeError):
            tool.job = "something_else"  # type: ignore[misc]

    def test_bound_is_a_copy(self) -> None:
        """Handing out the live dict would let a caller widen the policy."""
        tool = Tool("issue_refund", cap_cents=5000)
        tool.bound["cap_cents"] = 10**9
        assert tool.bound == {"cap_cents": 5000}

    def test_listing_one_job_twice_is_rejected(self) -> None:
        """Two entries for one job cannot both be honored — the second's
        bindings would silently lose at call time."""
        with pytest.raises(ValueError, match="more than once"):
            Gate(
                name="g",
                awaits=RefundDecision,
                tools=["issue_refund", Tool("issue_refund", cap_cents=1)],
            )


JOBS_MODULE = '''
from pydantic import BaseModel, Field

from functualize.job import job
from functualize.workflow import END, Edge, Gate, Step, Tool, workflow


class RefundDecision(BaseModel):
    approve: bool


@job
def load_ticket() -> str:
    """Load the ticket."""
    return "ticket-9"


@job
def issue_refund(order_id: str = "", amount_cents: int = 0, cap_cents: int = 0) -> str:
    """Refund an order, never above the cap."""
    return f"refunded {min(amount_cents, cap_cents)}"


@job
def close_ticket() -> str:
    """Close the ticket."""
    return "closed"


@workflow(
    steps=[
        Step(load_ticket),
        Gate(name="approval", awaits=RefundDecision,
             tools=[Tool(issue_refund, cap_cents=5000)]),
        Step(close_ticket),
    ],
    edges=[Edge(source="load_ticket", target="approval"),
           Edge(source="approval", target="close_ticket"),
           Edge(source="close_ticket", target=END)],
)
def refund_request() -> str:
    """Refund with approval."""
    return "done"
'''


def _discovered_app() -> FunctualizeApp:
    """A real discovered app.

    Discovery is what populates a descriptor's field information, and the
    published schema is built from it — a dynamically registered job carries
    none, so a schema assertion against one would pass no matter what this
    code did.
    """
    from functualize.app.core import JobSources

    Path("jobs.py").write_text(JOBS_MODULE)
    return FunctualizeApp(name="refunds", job_sources=JobSources(directories=["."]))


class TestPublishedSchema:
    """The crux: narrowing is a schema transform, not a label.

    Asserting only that `bound` lists the parameter would pass against a
    design where the agent still sees it and merely gets an error — a
    materially weaker guarantee. These assert on the schema itself.
    """

    def test_a_bound_argument_is_absent_from_the_agents_schema(self) -> None:
        app = _discovered_app()
        app.execute("refund_request", scope_id="run-1")
        tools = WorkflowToolProvider(app, store=_store())

        entry = asyncio.run(tools._get_workflow_state("run-1"))["pending_gates"][0][
            "tools"
        ][0]

        assert entry["tool"] == "issue-refund"
        assert entry["bound"] == ["cap_cents"]
        published = set(entry["input_schema"]["properties"])
        assert published == {"order_id", "amount_cents"}
        assert "cap_cents" not in published, (
            "the pinned argument is still in the agent's vocabulary — the "
            "narrowing is a label, not a permission"
        )

    def test_the_unpinned_arguments_survive(self) -> None:
        """Stripping too much would make the tool uncallable."""
        app = _discovered_app()
        app.execute("refund_request", scope_id="run-1")
        tools = WorkflowToolProvider(app, store=_store())

        entry = asyncio.run(tools._get_workflow_state("run-1"))["pending_gates"][0][
            "tools"
        ][0]
        assert entry["input_schema"]["properties"]["amount_cents"]["type"] == "integer"
        assert entry["description"] == "Refund an order, never above the cap."

    def test_the_transform_removes_from_required_too(self) -> None:
        """A bound name left in `required` would make the published schema
        unsatisfiable: the agent must supply what it cannot express."""
        from functualize_mcp._workflow_tools import _without

        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "required": ["a", "b"],
        }
        narrowed = _without(schema, ["b"])

        assert set(narrowed["properties"]) == {"a"}
        assert narrowed["required"] == ["a"]

    def test_an_unbound_tool_publishes_everything(self) -> None:
        _app_, tools = _blocked(["issue_refund"])

        entry = asyncio.run(tools._get_workflow_state("run-1"))["pending_gates"][0][
            "tools"
        ][0]
        assert entry["bound"] == []

    def test_a_listed_job_that_does_not_exist_is_flagged(self) -> None:
        """Silence here is a lockout with no explanation — the old failure mode
        for a typo'd tool name."""
        _app_, tools = _blocked(["no_such_job"])

        entry = asyncio.run(tools._get_workflow_state("run-1"))["pending_gates"][0][
            "tools"
        ][0]
        assert "unavailable" in entry


class TestCallGateTool:
    def test_a_permitted_call_runs_and_returns(self) -> None:
        app, tools = _blocked(["order_history"])

        result = asyncio.run(
            tools._call_gate_tool("run-1", "order_history", {"customer_id": "C-1"})
        )

        assert result["return_value"] == "3 orders"
        assert app.calls == [("order_history", {"customer_id": "C-1"})]  # type: ignore[attr-defined]

    def test_bound_values_are_applied_from_the_declaration(self) -> None:
        """Only the bound *names* are persisted; the values come from the live
        declaration at call time."""
        app, tools = _blocked([Tool("issue_refund", cap_cents=5000)])

        result = asyncio.run(
            tools._call_gate_tool(
                "run-1", "issue_refund", {"order_id": "A", "amount_cents": 9999}
            )
        )

        assert result["return_value"] == "refunded 5000"
        assert app.calls[0][1]["cap_cents"] == 5000  # type: ignore[attr-defined]

    def test_supplying_a_bound_argument_is_refused_not_overridden(self) -> None:
        """Silently ignoring it would leave the agent believing it set a cap."""
        app, tools = _blocked([Tool("issue_refund", cap_cents=5000)])

        result = asyncio.run(
            tools._call_gate_tool(
                "run-1",
                "issue_refund",
                {"order_id": "A", "amount_cents": 9999, "cap_cents": 10**9},
            )
        )

        assert result["error"] == "argument_not_permitted"
        assert app.calls == []  # type: ignore[attr-defined]

    def test_a_job_not_offered_by_the_gate_is_refused(self) -> None:
        app, tools = _blocked(["order_history"])

        result = asyncio.run(tools._call_gate_tool("run-1", "issue_refund", {}))

        assert result["error"] == "tool_not_permitted"
        assert result["allowed_tools"] == ["order-history"]
        assert app.calls == []  # type: ignore[attr-defined]

    def test_an_unknown_scope_is_an_error(self) -> None:
        _app_, tools = _blocked(["order_history"])
        result = asyncio.run(tools._call_gate_tool("nope", "order_history", {}))
        assert result["error"] == "workflow_not_found"

    def test_tools_are_unavailable_once_the_gate_is_answered(self) -> None:
        """The grant is scoped to the wait. A resolved gate offers nothing."""
        _app_, tools = _blocked(["order_history"])
        _store().deposit_gate_payload("run-1", "approval", {"approve": True})

        result = asyncio.run(tools._call_gate_tool("run-1", "order_history", {}))
        assert result["error"] == "tool_not_permitted"


class TestRecordedNotMemoized:
    def test_a_call_is_recorded(self) -> None:
        _app_, tools = _blocked(["order_history"])
        asyncio.run(
            tools._call_gate_tool("run-1", "order_history", {"customer_id": "C-1"})
        )

        calls = _store().get_tool_calls("run-1")
        assert len(calls) == 1
        assert calls[0]["tool"] == "order-history"
        assert calls[0]["args"] == {"customer_id": "C-1"}
        assert calls[0]["called_at"]

    def test_calling_twice_runs_twice(self) -> None:
        """Ratified: tool calls are exploration, not plan. An agent that calls
        a tool three times before deciding meant to, and must not be served a
        memoized answer."""
        app, tools = _blocked(["order_history"])

        for _ in range(3):
            asyncio.run(tools._call_gate_tool("run-1", "order_history", {}))

        assert len(app.calls) == 3  # type: ignore[attr-defined]
        assert len(_store().get_tool_calls("run-1")) == 3

    def test_tool_calls_do_not_become_step_records(self) -> None:
        """A tool call must not be mistaken for a completed step, or replay
        would skip the real step of the same name."""
        _app_, tools = _blocked(["order_history"])
        asyncio.run(tools._call_gate_tool("run-1", "order_history", {}))

        scope = _store().get_scope("run-1")
        assert scope is not None
        assert "order_history::" not in scope["steps"]

    def test_the_record_survives_for_an_auditor(self) -> None:
        """The agent's own context is gone; this is the only trace of what it
        did before approving."""
        _app_, tools = _blocked([Tool("issue_refund", cap_cents=5000)])
        asyncio.run(
            tools._call_gate_tool(
                "run-1", "issue_refund", {"order_id": "A", "amount_cents": 100}
            )
        )

        record = StateStore.for_project(Path.cwd()).get_tool_calls("run-1")[0]
        assert record["return_value"] == "refunded 100"
        assert record["status"] == "Success"


class TestGenericDoorsTakeTheSameLock:
    """`run_job` is another door to the same room. It was the bypass that made
    the first cut of gate enforcement decorative."""

    def _registry(self, app: FunctualizeApp) -> MCPToolRegistry:
        return MCPToolRegistry(
            app,
            config=MCPConfig(),
            gate_policy=GateToolPolicy(app, store=_store()),
        )

    def test_run_job_cannot_bypass_the_gate(self) -> None:
        app, _tools = _blocked(["order_history"])

        result = asyncio.run(self._registry(app)._run_job("issue_refund"))

        assert result["error"]["code"] == "tool_not_permitted"
        assert app.calls == []  # type: ignore[attr-defined]

    def test_run_job_async_cannot_bypass_the_gate(self) -> None:
        app, _tools = _blocked(["order_history"])

        result = asyncio.run(self._registry(app)._run_job_async("issue_refund"))

        assert result["error"]["code"] == "tool_not_permitted"

    def test_run_job_still_runs_a_permitted_job(self) -> None:
        app, _tools = _blocked(["order_history"])

        result = asyncio.run(self._registry(app)._run_job("order_history"))

        assert "error" not in result
        assert app.calls  # type: ignore[attr-defined]

    def test_run_job_is_unaffected_when_nothing_is_blocked(self) -> None:
        app = _app(["order_history"])
        result = asyncio.run(self._registry(app)._run_job("issue_refund"))
        assert "error" not in result


class TestPublishedResults:
    """What the agent learns about the run so far.

    The store has always held each step's return value and resolved inputs;
    publishing only node *names* meant an agent could see that a step ran and
    never what it produced, so the run's own results had to reach it out of
    band. That is the workflow asking the agent to be its plumbing.
    """

    def test_a_steps_return_value_is_published(self) -> None:
        _app_, tools = _blocked(["order_history"])

        results = asyncio.run(tools._get_workflow_state("run-1"))["results"]

        assert results["load-ticket"]["return_value"] == "ticket-9"
        assert results["load-ticket"]["status"] == "success"

    def test_resolved_inputs_are_published(self) -> None:
        """Not just what a step returned — what it was given. Otherwise a
        surprising result is unexplainable from the record alone."""
        app = _discovered_app()
        app.execute("refund_request", scope_id="run-1")
        tools = WorkflowToolProvider(app, store=_store())

        results = asyncio.run(tools._get_workflow_state("run-1"))["results"]

        assert "inputs" in results["load-ticket"]

    def test_secrets_are_masked_in_recorded_inputs(self) -> None:
        """These records go to disk *and* to an external agent. A resolved
        config that still held a token would leak it twice over."""
        from functualize._types.redaction import MASK, Secret, redacted_snapshot

        class Cfg(BaseModel):
            city: str = "Kyoto"
            token: Secret[str] = Secret("hunter2")
            flagged: str = "k-123"

            model_config = {"arbitrary_types_allowed": True}

        snapshot = redacted_snapshot({"config": Cfg()})

        assert snapshot["config"]["city"] == "Kyoto"
        assert snapshot["config"]["token"] == MASK
        assert "hunter2" not in str(snapshot)

    def test_an_unserializable_input_degrades_instead_of_raising(self) -> None:
        """A record that cannot be written is worse than one that says
        `<object at 0x…>`."""
        from functualize._types.redaction import redacted_snapshot

        class Opaque:
            pass

        snapshot = redacted_snapshot({"conn": Opaque()})
        assert isinstance(snapshot["conn"], str)

    def test_the_vfs_shape_works_end_to_end(self) -> None:
        """The motivating scenario's discoverable half: a step returns the
        files an agent may touch, and the agent can read that list.

        The enforcing half — binding a tool's allowlist *to* this value —
        shipped in S8/T33 as `FromStep`; see `TestBoundFromStep`.
        """
        app = FunctualizeApp(name="vfs")

        def setup_vfs() -> list[str]:
            return ["src/a.py", "src/b.py"]

        def teardown_vfs() -> str:
            return "unmounted"

        @workflow(
            steps=[
                Step("setup_vfs"),
                Gate(name="edit", awaits=RefundDecision),
                Step("teardown_vfs"),
            ],
            edges=[
                Edge(source="setup_vfs", target="edit"),
                Edge(source="edit", target="teardown_vfs"),
                Edge(source="teardown_vfs", target=END),
            ],
        )
        def vfs_session() -> str:
            return "done"

        for name, fn in [
            ("setup_vfs", setup_vfs),
            ("teardown_vfs", teardown_vfs),
            ("vfs_session", vfs_session),
        ]:
            app.register_dynamic_job(name, fn)
        app.execute("vfs_session", scope_id="run-1")

        tools = WorkflowToolProvider(app, store=_store())
        results = asyncio.run(tools._get_workflow_state("run-1"))["results"]

        assert results["setup-vfs"]["return_value"] == ["src/a.py", "src/b.py"]


class TestBoundFromStep:
    """A gate tool's argument bound to this walk's recorded result (Q20).

    The declaration already constructed before this shipped — `Tool(read_file,
    allowed=FromStep(...))` stored the marker — but `_bound_values` returned
    `spec.bound` verbatim, so the *marker object* was handed to the job as the
    argument value. The narrowing the gate exists to enforce silently did not
    happen.
    """

    def _vfs_app(self) -> tuple[FunctualizeApp, WorkflowToolProvider]:
        from functualize._types.from_job import FromStep

        app = FunctualizeApp(name="vfs-bound")

        def setup_vfs() -> list[str]:
            return ["src/a.py", "src/b.py"]

        def read_file(path: str, allowed: list[str] | None = None) -> str:
            if allowed is not None and path not in allowed:
                return f"REFUSED {path}"
            return f"contents of {path}"

        @workflow(
            steps=[
                Step("setup_vfs"),
                Gate(
                    name="edit",
                    awaits=RefundDecision,
                    tools=[Tool("read_file", allowed=FromStep("setup-vfs"))],
                ),
            ],
            edges=[
                Edge(source="setup_vfs", target="edit"),
                Edge(source="edit", target=END),
            ],
        )
        def vfs_session() -> str:
            return "done"

        for name, fn in [
            ("setup_vfs", setup_vfs),
            ("read_file", read_file),
            ("vfs_session", vfs_session),
        ]:
            app.register_dynamic_job(name, fn)
        app.execute("vfs_session", scope_id="run-1")
        return app, WorkflowToolProvider(app, store=_store())

    def test_from_job_is_refused_with_the_spelling_that_works(self) -> None:
        """`run=True` is not merely unused in a binding, it is unmeaningful:
        the step has already run, and running it here would execute it
        outside the walk's recording."""
        from functualize._types.from_job import FromJob

        with pytest.raises(TypeError) as excinfo:
            Tool("read_file", allowed=FromJob("setup-vfs"))

        message = str(excinfo.value)
        assert "FromStep" in message, "the error must name the working form"
        assert "setup-vfs" in message

    def test_the_agent_may_read_a_file_inside_the_vfs(self) -> None:
        _app_obj, tools = self._vfs_app()
        result = asyncio.run(
            tools._call_gate_tool("run-1", "read_file", {"path": "src/a.py"})
        )
        assert result["return_value"] == "contents of src/a.py"

    def test_a_file_outside_the_vfs_is_refused(self) -> None:
        """The allowlist came from the step's recorded return value, so the
        boundary is enforced rather than merely described."""
        _app_obj, tools = self._vfs_app()
        result = asyncio.run(
            tools._call_gate_tool("run-1", "read_file", {"path": "/etc/passwd"})
        )
        assert result["return_value"] == "REFUSED /etc/passwd"

    def test_the_marker_is_replaced_not_passed_through(self) -> None:
        from functualize._types.from_job import FromStep

        _app_obj, tools = self._vfs_app()
        scope = tools.store.get_scope("run-1") or {}
        resolved = tools._resolve_bound(scope, {"allowed": FromStep("setup-vfs")})

        assert resolved["allowed"] == ["src/a.py", "src/b.py"]

    def test_an_unrecorded_step_resolves_to_none(self) -> None:
        """The walk may legitimately not have reached it; the job's own
        signature is the right place for that to be an error."""
        from functualize._types.from_job import FromStep

        _app_obj, tools = self._vfs_app()
        scope = tools.store.get_scope("run-1") or {}

        assert tools._resolve_bound(scope, {"x": FromStep("no-such-step")}) == {
            "x": None
        }

    def test_plain_bound_values_are_untouched(self) -> None:
        _app_obj, tools = self._vfs_app()
        scope = tools.store.get_scope("run-1") or {}
        assert tools._resolve_bound(scope, {"cap": 5000}) == {"cap": 5000}

    def test_the_agent_cannot_override_the_allowlist(self) -> None:
        """The guarantee is not secrecy — it is that the value is not the
        agent's to set.

        The file list *is* visible, through published step results, and that
        is deliberate: an agent has to know which files it may touch. What it
        cannot do is supply `allowed` itself. A bound argument is refused
        rather than silently overridden, because an agent that believes it set
        a value and did not is worse off than one told no.
        """
        _app_obj, tools = self._vfs_app()
        result = asyncio.run(
            tools._call_gate_tool(
                "run-1",
                "read_file",
                {"path": "src/a.py", "allowed": ["/etc/passwd"]},
            )
        )
        assert result["error"] == "argument_not_permitted"
        assert "allowed" in result["message"]

    def test_the_bound_name_is_published_so_the_schema_can_strip_it(self) -> None:
        """Names travel, values do not: a reader strips `allowed` from the
        schema it shows without ever learning what it is fixed to."""
        _app_obj, tools = self._vfs_app()
        state = asyncio.run(tools._get_workflow_state("run-1"))

        gates = state.get("pending_gates") or []
        assert any(
            entry.get("bound") == ["allowed"]
            for gate in gates
            for entry in (gate.get("tools") or [])
        ), f"expected the bound name to be published, got {gates!r}"
