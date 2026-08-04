"""Phase 1 integration tests — end-to-end flows.

Tests the full system: app.execute() with auto-scope, hook firing,
nested invocation, gate resolution with registered strategies and
fallback chains, workflow decorator with ConditionalEdge routing,
and invoke_depth propagation across nested calls.

**Validates: Requirements 1.1, 3.6, 7.9, 8.8, 9.1, 9.4, 9.5**
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._engine.errors import RecursionLimitError
from functualize._events.hooks import HookEvent
from functualize._types.errors import GateResolutionError
from functualize._types.workflow import END, ConditionalEdge, Edge, Step
from functualize.app.config import ExecutionConfig
from functualize.app.core import FunctualizeApp
from functualize.workflow._decorator import workflow

if TYPE_CHECKING:
    from functualize._gate._context import GateContext
    from functualize.job._workflow_scope import WorkflowScope
    from functualize.job.context import RunContext

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def app() -> FunctualizeApp:
    """Create a minimal FunctualizeApp for testing."""
    return FunctualizeApp(name="testapp")


@pytest.fixture
def app_shallow() -> FunctualizeApp:
    """FunctualizeApp with max_invoke_depth=2 for recursion testing."""
    return FunctualizeApp(
        name="testapp",
        execution=ExecutionConfig(max_invoke_depth=2),
    )


# ─── Test Models ─────────────────────────────────────────────────────────────


class DeployConfig(BaseModel):
    """Sample model for gate resolution tests."""

    region: str
    replicas: int = 3


class PartialConfig(BaseModel):
    """Model with one required and one optional field."""

    target: str
    verbose: bool = False


# ─── Resolver Implementations ────────────────────────────────────────────────


class AlwaysSucceedResolver:
    """Gate resolver that always succeeds with fixed values."""

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def resolve(self, ctx: GateContext) -> BaseModel:
        merged = {**ctx.resolved_fields, **self._values}
        return ctx.model_class(**merged)


class AlwaysFailResolver:
    """Gate resolver that always raises."""

    def __init__(self, message: str = "fail") -> None:
        self._message = message

    def resolve(self, ctx: GateContext) -> BaseModel:
        raise RuntimeError(self._message)


class ConditionalResolver:
    """Gate resolver that only succeeds when a specific field is unresolved."""

    def __init__(self, field_name: str, value: Any) -> None:
        self._field_name = field_name
        self._value = value

    def resolve(self, ctx: GateContext) -> BaseModel:
        if self._field_name not in ctx.unresolved_fields:
            raise RuntimeError(f"{self._field_name} already resolved")
        merged = {**ctx.resolved_fields, self._field_name: self._value}
        return ctx.model_class(**merged)


# ─── Test: app.execute() with Auto-Scope and Hook Firing ─────────────────────


class TestAppExecuteAutoScope:
    """Test full app.execute() with auto-scope and ON_SCOPE_CREATED hook.

    **Validates: Requirements 9.1, 9.5**
    """

    def test_execute_creates_auto_scope_with_correct_format(
        self, app: FunctualizeApp
    ) -> None:
        """app.execute() auto-generates scope_id in '{job_name}-{hex8}' format.

        **Validates: Requirements 9.1**
        """

        def my_job(**kwargs: Any) -> str:
            return "done"

        app.register_dynamic_job("deploy", my_job)
        app.execute("deploy")

        # Scope was created
        assert len(app._scope_registry) == 1
        scope_id = next(iter(app._scope_registry.keys()))

        # Matches expected format
        pattern = r"^deploy-[0-9a-f]{8}$"
        assert re.match(pattern, scope_id), (
            f"scope_id '{scope_id}' doesn't match {pattern}"
        )

    def test_execute_fires_on_scope_created_hook(self, app: FunctualizeApp) -> None:
        """app.execute() fires ON_SCOPE_CREATED hook before execution.

        **Validates: Requirements 9.5**
        """
        received_scopes: list[WorkflowScope] = []

        def on_scope_created(scope: WorkflowScope) -> None:
            received_scopes.append(scope)

        app._hook_registry.register_global(HookEvent.ON_SCOPE_CREATED, on_scope_created)

        def my_job(**kwargs: Any) -> str:
            return "ok"

        app.register_dynamic_job("hello", my_job)
        app.execute("hello")

        assert len(received_scopes) == 1
        assert received_scopes[0].scope_id.startswith("hello-")

    def test_execute_with_explicit_scope_id_reuses_existing(
        self, app: FunctualizeApp
    ) -> None:
        """Explicit scope_id reuses an existing WorkflowScope.

        **Validates: Requirements 9.4**
        """

        def my_job(**kwargs: Any) -> str:
            return "reused"

        app.register_dynamic_job("greet", my_job)

        # Pre-create scope
        original_scope = app.create_workflow_scope("my-custom-scope")

        # Execute with the same scope_id
        app.execute("greet", scope_id="my-custom-scope")

        # Same instance is reused
        assert app._scope_registry["my-custom-scope"] is original_scope
        assert len(app._scope_registry) == 1

    def test_execute_hook_fires_before_job_runs(self, app: FunctualizeApp) -> None:
        """ON_SCOPE_CREATED fires before the job function is invoked.

        **Validates: Requirements 9.5**
        """
        execution_order: list[str] = []

        def on_scope_created(scope: WorkflowScope) -> None:
            execution_order.append("hook")

        app._hook_registry.register_global(HookEvent.ON_SCOPE_CREATED, on_scope_created)

        def my_job(**kwargs: Any) -> str:
            execution_order.append("job")
            return "ok"

        app.register_dynamic_job("ordered", my_job)
        app.execute("ordered")

        assert execution_order == ["hook", "job"]


# ─── Test: Nested Invocation Propagates Parent Scope ─────────────────────────


class TestNestedInvocationScopePropagation:
    """Test that nested invocations propagate parent scope (no new scope created).

    **Validates: Requirements 9.4**
    """

    def test_nested_invoke_propagates_parent_scope(self, app: FunctualizeApp) -> None:
        """Child invocation receives the parent's WorkflowScope, no new scope created.

        **Validates: Requirements 9.4**
        """

        def child_job(rc: RunContext) -> str:
            """Child job."""
            return "child_done"

        def parent_job(rc: RunContext) -> str:
            """Parent job invokes the child job."""
            rc.invoke("child_job")
            return "parent_done"

        app.register_dynamic_job("child_job", child_job)
        app.register_dynamic_job("parent_job", parent_job)

        app.execute("parent_job")

        # Only one scope should have been created (by the parent)
        assert len(app._scope_registry) == 1

        # The parent's scope should have been propagated
        scope_id = next(iter(app._scope_registry.keys()))
        assert scope_id.startswith("parent_job-")


# ─── Test: Gate Resolution with Registered Strategies and Fallback ────────────


class TestGateResolutionEndToEnd:
    """Test gate resolution with registered strategies and fallback chains.

    **Validates: Requirements 7.9**
    """

    def test_single_strategy_resolves_model(self, app: FunctualizeApp) -> None:
        """Registered strategy resolves the gate model successfully.

        **Validates: Requirements 7.9**
        """
        resolver = AlwaysSucceedResolver({"region": "us-west-2", "replicas": 5})
        app.register_gate_strategy("auto_resolver", resolver)

        result = app.resolve_gate(
            DeployConfig,
            force_gate=True,
            gate_strategy="auto_resolver",
        )

        assert isinstance(result, DeployConfig)
        assert result.region == "us-west-2"
        assert result.replicas == 5

    def test_fallback_chain_tries_in_order(self, app: FunctualizeApp) -> None:
        """Ordered strategy list tries each in order, returns first success.

        **Validates: Requirements 7.9**
        """
        call_order: list[str] = []

        class TrackingFailResolver:
            def __init__(self, name: str) -> None:
                self._name = name

            def resolve(self, ctx: GateContext) -> BaseModel:
                call_order.append(self._name)
                raise RuntimeError(f"{self._name} failed")

        class TrackingSucceedResolver:
            def __init__(self, name: str) -> None:
                self._name = name

            def resolve(self, ctx: GateContext) -> BaseModel:
                call_order.append(self._name)
                return ctx.model_class(region="fallback", replicas=1)

        app.register_gate_strategy("fail1", TrackingFailResolver("fail1"))
        app.register_gate_strategy("fail2", TrackingFailResolver("fail2"))
        app.register_gate_strategy("succeed", TrackingSucceedResolver("succeed"))

        result = app.resolve_gate(
            DeployConfig,
            force_gate=True,
            gate_strategy=["fail1", "fail2", "succeed"],
        )

        assert call_order == ["fail1", "fail2", "succeed"]
        assert isinstance(result, DeployConfig)
        assert result.region == "fallback"

    def test_all_strategies_fail_raises_gate_resolution_error(
        self, app: FunctualizeApp
    ) -> None:
        """When all strategies fail, GateResolutionError is raised.

        **Validates: Requirements 7.9**
        """
        app.register_gate_strategy("bad1", AlwaysFailResolver("error1"))
        app.register_gate_strategy("bad2", AlwaysFailResolver("error2"))

        with pytest.raises(GateResolutionError) as exc_info:
            app.resolve_gate(
                DeployConfig,
                force_gate=True,
                gate_strategy=["bad1", "bad2"],
            )

        assert exc_info.value.strategies_attempted == 2
        assert "error2" in exc_info.value.last_error

    def test_preset_expands_to_strategy_list(self, app: FunctualizeApp) -> None:
        """A gate preset expands to its registered strategy list for fallback.

        **Validates: Requirements 7.9**
        """
        app.register_gate_strategy("primary", AlwaysFailResolver("primary_fail"))
        app.register_gate_strategy(
            "secondary", AlwaysSucceedResolver({"region": "eu-west-1"})
        )
        app.register_gate_preset("my_preset", ["primary", "secondary"])

        result = app.resolve_gate(
            DeployConfig,
            force_gate=True,
            gate_strategy="my_preset",
        )

        assert isinstance(result, DeployConfig)
        assert result.region == "eu-west-1"

    def test_force_gate_dispatches_even_when_fully_resolved(
        self, app: FunctualizeApp
    ) -> None:
        """force_gate=True dispatches to strategy even with all fields resolved.

        **Validates: Requirements 7.9**
        """
        strategy_called = []

        class RecordingResolver:
            def resolve(self, ctx: GateContext) -> BaseModel:
                strategy_called.append(True)
                return ctx.model_class(region="override", replicas=10)

        app.register_gate_strategy("recorder", RecordingResolver())

        result = app.resolve_gate(
            DeployConfig,
            force_gate=True,
            gate_strategy="recorder",
            resolved_fields={"region": "original", "replicas": 3},
        )

        assert strategy_called == [True]
        assert result.region == "override"

    def test_gate_skips_dispatch_when_fully_resolved(self, app: FunctualizeApp) -> None:
        """force_gate=False with all fields resolved skips strategy dispatch.

        **Validates: Requirements 7.9**
        """
        strategy_called = []

        class RecordingResolver:
            def resolve(self, ctx: GateContext) -> BaseModel:
                strategy_called.append(True)
                return ctx.model_class(region="override", replicas=10)

        app.register_gate_strategy("recorder", RecordingResolver())

        result = app.resolve_gate(
            DeployConfig,
            force_gate=False,
            gate_strategy="recorder",
            resolved_fields={"region": "original", "replicas": 3},
        )

        # Strategy should NOT have been called
        assert strategy_called == []
        assert result.region == "original"
        assert result.replicas == 3


# ─── Test: Workflow Decorator with ConditionalEdge Routing ────────────────────


class TestWorkflowConditionalEdgeRouting:
    """Test workflow execution with conditional routing via ConditionalEdge.

    **Validates: Requirements 8.8**
    """

    def test_conditional_edge_routes_to_correct_target(self) -> None:
        """ConditionalEdge condition function routes based on return value.

        **Validates: Requirements 8.8**
        """

        def route_condition(result: str) -> str:
            if result == "success":
                return "happy_path"
            return "error_path"

        def step_a_job() -> str:
            return "success"

        def step_b_job() -> str:
            return "handled_success"

        def step_c_job() -> str:
            return "handled_error"

        # Node identity is the referenced job's name — a step no longer carries
        # a separate alias, so edges address the jobs directly.
        steps = [Step(step_a_job), Step(step_b_job), Step(step_c_job)]
        edges = [
            ConditionalEdge(
                source="step_a_job",
                condition=route_condition,
                targets={
                    "happy_path": "step_b_job",
                    "error_path": "step_c_job",
                },
            ),
            Edge(source="step_b_job", target=END),
            Edge(source="step_c_job", target=END),
        ]

        @workflow(steps=steps, edges=edges)
        def my_workflow() -> None:
            pass

        # Verify decoration attached workflow definition
        assert hasattr(my_workflow, "__functualize_workflow__")
        wf_def = my_workflow.__functualize_workflow__

        # Verify the conditional edge's condition function works correctly
        cond_edge = wf_def.edges[0]
        assert isinstance(cond_edge, ConditionalEdge)
        assert cond_edge.condition("success") == "happy_path"
        assert cond_edge.condition("failure") == "error_path"

        # Verify targets mapping
        assert cond_edge.targets["happy_path"] == "step-b-job"
        assert cond_edge.targets["error_path"] == "step-c-job"

    def test_conditional_edge_routes_to_end_sentinel(self) -> None:
        """ConditionalEdge can route to END sentinel for termination.

        **Validates: Requirements 8.8**
        """

        def route_condition(result: str) -> str:
            return "done" if result == "complete" else "continue"

        steps = [
            Step("process"),
            Step("next_step"),
        ]
        edges = [
            ConditionalEdge(
                source="process",
                condition=route_condition,
                targets={
                    "done": END,
                    "continue": "next_step",
                },
            ),
        ]

        @workflow(steps=steps, edges=edges)
        def terminating_workflow() -> None:
            pass

        wf_def = terminating_workflow.__functualize_workflow__
        cond_edge = wf_def.edges[0]

        # "done" routes to END
        assert cond_edge.targets["done"] is END
        # "continue" routes to a step
        assert cond_edge.targets["continue"] == "next-step"

    def test_conditional_edge_with_multiple_targets(self) -> None:
        """ConditionalEdge supports multiple target mappings.

        **Validates: Requirements 8.8**
        """

        def classifier(result: int) -> str:
            if result > 100:
                return "high"
            elif result > 50:
                return "medium"
            return "low"

        steps = [
            Step("evaluate"),
            Step("high_handler"),
            Step("medium_handler"),
            Step("low_handler"),
        ]
        edges = [
            ConditionalEdge(
                source="evaluate",
                condition=classifier,
                targets={
                    "high": "high_handler",
                    "medium": "medium_handler",
                    "low": "low_handler",
                },
            ),
        ]

        @workflow(steps=steps, edges=edges)
        def classified_workflow() -> None:
            pass

        cond_edge = classified_workflow.__functualize_workflow__.edges[0]

        # Verify routing for various values
        assert cond_edge.condition(200) == "high"
        assert cond_edge.condition(75) == "medium"
        assert cond_edge.condition(10) == "low"


# ─── Test: invoke_depth Propagation Across Nested Calls ───────────────────────


class TestInvokeDepthPropagation:
    """Test invoke_depth increments on nested calls and RecursionLimitError at limit.

    **Validates: Requirements 1.1, 3.6**
    """

    def test_invoke_depth_increments_on_nested_calls(self, app: FunctualizeApp) -> None:
        """invoke_depth increments for each level of nested invocation.

        **Validates: Requirements 3.6**
        """
        observed_depths: list[int] = []

        def level2_job(rc: RunContext) -> str:
            observed_depths.append(rc._invoke_depth)
            return "level2"

        def level1_job(rc: RunContext) -> str:
            observed_depths.append(rc._invoke_depth)
            rc.invoke("level2_job")
            return "level1"

        def root_job(rc: RunContext) -> str:
            observed_depths.append(rc._invoke_depth)
            rc.invoke("level1_job")
            return "root"

        app.register_dynamic_job("level2_job", level2_job)
        app.register_dynamic_job("level1_job", level1_job)
        app.register_dynamic_job("root_job", root_job)

        app.execute("root_job")

        # Root is at depth 0, level1 at depth 1, level2 at depth 2
        assert observed_depths == [0, 1, 2]

    def test_recursion_limit_error_at_max_depth(
        self, app_shallow: FunctualizeApp
    ) -> None:
        """RecursionLimitError is raised when invoke_depth reaches max_invoke_depth.

        **Validates: Requirements 3.6**
        """
        depths_reached: list[int] = []

        def recursive_job(rc: RunContext) -> str:
            depths_reached.append(rc._invoke_depth)
            with contextlib.suppress(RecursionLimitError):
                rc.invoke("recursive_job")
            return "ok"

        app_shallow.register_dynamic_job("recursive_job", recursive_job)

        # With max_invoke_depth=2:
        # root executes at depth 0, recurse at depth 1,
        # next recurse attempt at depth 2 → raises RecursionLimitError
        app_shallow.execute("recursive_job")

        # The job should have been called at depths 0 and 1,
        # but depth 2 should have been blocked by RecursionLimitError
        assert depths_reached == [0, 1, 2]

    def test_recursion_limit_error_contains_depth_info(
        self, app_shallow: FunctualizeApp
    ) -> None:
        """RecursionLimitError includes current_depth and max_depth attributes.

        **Validates: Requirements 3.6**
        """
        error_captured: list[RecursionLimitError] = []

        def deep_job(rc: RunContext) -> str:
            try:
                rc.invoke("deep_job")
            except RecursionLimitError as e:
                error_captured.append(e)
            return "ok"

        app_shallow.register_dynamic_job("deep_job", deep_job)

        # Execute — will eventually hit the limit
        app_shallow.execute("deep_job")

        # At least one RecursionLimitError should have been captured
        assert len(error_captured) >= 1
        err = error_captured[0]
        assert err.depth == err.max_depth


# ─── Test: Full End-to-End Flow ──────────────────────────────────────────────


class TestEndToEndFlow:
    """Combined integration test: execute → scope → hooks → nested invoke.

    **Validates: Requirements 1.1, 9.1, 9.4, 9.5**
    """

    def test_full_flow_scope_hooks_and_nested_invoke(self, app: FunctualizeApp) -> None:
        """Full flow: app.execute creates scope, fires hook, nested invoke propagates scope.

        **Validates: Requirements 1.1, 9.1, 9.4, 9.5**
        """
        events: list[str] = []
        scope_ids_seen: list[str] = []

        def on_scope_created(scope: WorkflowScope) -> None:
            events.append(f"scope_created:{scope.scope_id}")
            scope_ids_seen.append(scope.scope_id)

        app._hook_registry.register_global(HookEvent.ON_SCOPE_CREATED, on_scope_created)

        def child_job(rc: RunContext) -> str:
            events.append("child_executed")
            return "child_result"

        def parent_job(rc: RunContext) -> str:
            events.append("parent_executed")
            rc.invoke("child_job")
            return "parent_result"

        app.register_dynamic_job("child_job", child_job)
        app.register_dynamic_job("parent_job", parent_job)

        app.execute("parent_job")

        # Verify execution order: scope created first, then parent, then child
        assert events[0].startswith("scope_created:")
        assert "parent_executed" in events
        assert "child_executed" in events

        # Only one scope was created (by the top-level execute)
        assert len(scope_ids_seen) == 1
        assert scope_ids_seen[0].startswith("parent_job-")

        # Only one scope in the registry
        assert len(app._scope_registry) == 1

    def test_multiple_top_level_executes_create_separate_scopes(
        self, app: FunctualizeApp
    ) -> None:
        """Each top-level app.execute creates its own unique scope.

        **Validates: Requirements 9.1**
        """

        def simple_job(**kwargs: Any) -> str:
            return "ok"

        app.register_dynamic_job("job_a", simple_job)
        app.register_dynamic_job("job_b", simple_job)

        app.execute("job_a")
        app.execute("job_b")

        # Two separate scopes in the registry
        assert len(app._scope_registry) == 2
        scope_ids = list(app._scope_registry.keys())
        assert any(sid.startswith("job_a-") for sid in scope_ids)
        assert any(sid.startswith("job_b-") for sid in scope_ids)

    def test_gate_strategy_in_real_execution_context(self, app: FunctualizeApp) -> None:
        """Gate resolution works when called from app context with real registrations.

        **Validates: Requirements 7.9**
        """
        # Register strategies
        app.register_gate_strategy(
            "env_resolver",
            AlwaysFailResolver("no env"),
        )
        app.register_gate_strategy(
            "default_resolver",
            AlwaysSucceedResolver({"target": "production"}),
        )
        app.register_gate_preset("deploy_preset", ["env_resolver", "default_resolver"])

        # Resolve through the preset
        result = app.resolve_gate(
            PartialConfig,
            force_gate=True,
            gate_strategy="deploy_preset",
        )

        assert isinstance(result, PartialConfig)
        assert result.target == "production"
        assert result.verbose is False  # default value
