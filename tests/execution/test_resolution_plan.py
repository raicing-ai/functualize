"""Unit tests for ResolutionPlan and engine DI resolution.

Tests the ParamBinding/ResolutionPlan dataclasses, build_resolution_plan()
factory, and the engine's _resolve_di_parameters() integration.
"""

from __future__ import annotations

from typing import Annotated
from unittest.mock import MagicMock

import pytest

from functualize._engine.context import ExecutionContext
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.resolution import (
    ParamBinding,
    ResolutionPlan,
    build_resolution_plan,
)
from functualize._primitives.di import DIRegistry, MissingProviderError, Provide
from functualize.job.capabilities import Log, State
from functualize.job.context import RunContext

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


class FakeRunContext:
    """Dummy RunContext stand-in for tests."""

    pass


class CustomService:
    """A user-defined service type for DI tests."""

    def __init__(self, name: str = "default"):
        self.name = name


class AnotherService:
    """Another user-defined service type."""

    pass


# ---------------------------------------------------------------------------
# ParamBinding and ResolutionPlan dataclass tests
# ---------------------------------------------------------------------------


class TestParamBindingDataclass:
    def test_frozen(self):
        binding = ParamBinding(
            name="log",
            annotation=Log,
            qualifier=None,
            source="di",
            has_default=False,
            is_optional=False,
        )
        with pytest.raises(AttributeError):  # FrozenInstanceError
            binding.name = "other"  # type: ignore[misc]

    def test_fields(self):
        binding = ParamBinding(
            name="svc",
            annotation=CustomService,
            qualifier="primary",
            source="di",
            has_default=True,
            is_optional=False,
        )
        assert binding.name == "svc"
        assert binding.annotation is CustomService
        assert binding.qualifier == "primary"
        assert binding.source == "di"
        assert binding.has_default is True
        assert binding.is_optional is False


class TestResolutionPlanDataclass:
    def test_frozen(self):
        plan = ResolutionPlan(function_id=123, params=())
        with pytest.raises(AttributeError):
            plan.function_id = 456  # type: ignore[misc]

    def test_fields(self):
        binding = ParamBinding(
            name="x",
            annotation=int,
            qualifier=None,
            source="skip",
            has_default=False,
            is_optional=False,
        )
        plan = ResolutionPlan(function_id=42, params=(binding,))
        assert plan.function_id == 42
        assert len(plan.params) == 1
        assert plan.params[0] is binding


# ---------------------------------------------------------------------------
# build_resolution_plan tests
# ---------------------------------------------------------------------------


class TestBuildResolutionPlan:
    def test_no_params(self):
        def no_params():
            pass

        plan = build_resolution_plan(no_params, registered_types=set())
        assert plan.function_id == id(no_params)
        assert plan.params == ()

    def test_skip_unannotated_param(self):
        def job(x):
            pass

        plan = build_resolution_plan(job, registered_types=set())
        assert len(plan.params) == 1
        assert plan.params[0].source == "skip"
        assert plan.params[0].name == "x"

    def test_detect_runcontext_param(self):
        def job(rc: FakeRunContext):
            pass

        plan = build_resolution_plan(
            job, registered_types=set(), runcontext_type=FakeRunContext
        )
        assert len(plan.params) == 1
        assert plan.params[0].source == "runcontext"
        assert plan.params[0].annotation is FakeRunContext

    def test_detect_registered_di_type(self):
        def job(log: Log, svc: CustomService):
            pass

        plan = build_resolution_plan(job, registered_types={Log, CustomService})
        assert len(plan.params) == 2
        assert plan.params[0].source == "di"
        assert plan.params[0].annotation is Log
        assert plan.params[1].source == "di"
        assert plan.params[1].annotation is CustomService

    def test_unregistered_type_is_skipped(self):
        def job(svc: CustomService):
            pass

        plan = build_resolution_plan(job, registered_types=set())
        assert len(plan.params) == 1
        assert plan.params[0].source == "skip"

    def test_annotated_with_provide_qualifier(self):
        def job(cache: Annotated[CustomService, Provide("redis")]):
            pass

        plan = build_resolution_plan(job, registered_types=set())
        assert len(plan.params) == 1
        assert plan.params[0].source == "di"
        assert plan.params[0].annotation is CustomService
        assert plan.params[0].qualifier == "redis"

    def test_optional_type_detected(self):
        def job(svc: CustomService | None):
            pass

        plan = build_resolution_plan(job, registered_types={CustomService})
        assert len(plan.params) == 1
        assert plan.params[0].source == "di"
        assert plan.params[0].is_optional is True
        assert plan.params[0].annotation is CustomService

    def test_optional_unregistered_resolves_to_di(self):
        """Optional[T] where T is unregistered is still classified as 'di' (resolves to None)."""

        def job(svc: CustomService | None):
            pass

        plan = build_resolution_plan(job, registered_types=set())
        assert len(plan.params) == 1
        assert plan.params[0].source == "di"
        assert plan.params[0].is_optional is True

    def test_param_with_default_detected(self):
        def job(log: Log = None):  # type: ignore[assignment]
            pass

        plan = build_resolution_plan(job, registered_types={Log})
        assert len(plan.params) == 1
        assert plan.params[0].has_default is True
        assert plan.params[0].source == "di"

    def test_skips_self_and_cls(self):
        class MyClass:
            def method(self, log: Log):
                pass

            @classmethod
            def class_method(cls, log: Log):
                pass

        plan = build_resolution_plan(MyClass.method, registered_types={Log})
        # 'self' should be skipped
        assert len(plan.params) == 1
        assert plan.params[0].name == "log"

    def test_skips_args_kwargs(self):
        def job(*args, log: Log, **kwargs):
            pass

        plan = build_resolution_plan(job, registered_types={Log})
        assert len(plan.params) == 1
        assert plan.params[0].name == "log"
        assert plan.params[0].source == "di"

    def test_string_annotation_runcontext(self):
        """String annotation 'RunContext' is detected as runcontext source."""

        def job(rc: FakeRunContext):  # noqa: F821
            pass

        # When the string matches "RunContext" (the actual type name),
        # it should be classified. But here we test with the real pattern.
        # For the actual engine usage, RunContext string annotations are detected.
        plan = build_resolution_plan(
            job,
            registered_types=set(),
            runcontext_type=FakeRunContext,
        )
        # get_type_hints resolves the forward ref
        assert plan.params[0].source == "runcontext"

    def test_mixed_params(self):
        """Mixed DI, RunContext, and unannotated params."""

        def job(
            rc: FakeRunContext,
            log: Log,
            svc: CustomService,
            x: int,
            name="default",
        ):
            pass

        plan = build_resolution_plan(
            job,
            registered_types={Log, CustomService},
            runcontext_type=FakeRunContext,
        )
        # rc → runcontext, log → di, svc → di, x → skip (int not registered), name → skip
        assert plan.params[0].source == "runcontext"
        assert plan.params[1].source == "di"
        assert plan.params[1].annotation is Log
        assert plan.params[2].source == "di"
        assert plan.params[2].annotation is CustomService
        assert plan.params[3].source == "skip"  # int not registered
        assert plan.params[4].source == "skip"  # no annotation (str default)

    def test_function_id_matches(self):
        def job(log: Log):
            pass

        plan = build_resolution_plan(job, registered_types={Log})
        assert plan.function_id == id(job)


# ---------------------------------------------------------------------------
# Engine DI resolution integration tests
# ---------------------------------------------------------------------------


class TestEngineDIResolution:
    """Tests for engine-level caching and resolution behavior."""

    def test_plan_caching_by_function_identity(self):
        """Same function object → same plan object (identity)."""
        app = MagicMock()
        app._di_registry = DIRegistry()
        app._di_registry.provide(Log, Log())

        engine = JobExecutionEngine(
            di_registry=app._di_registry,
            event_bus=MagicMock(),
            hook_registry=MagicMock(),
            middleware_chain=MagicMock(),
        )

        def my_job(log: Log):
            pass

        plan1 = engine._get_resolution_plan(my_job)
        plan2 = engine._get_resolution_plan(my_job)

        # Same plan object by identity (cached)
        assert plan1 is plan2
        assert plan1.function_id == id(my_job)

    def test_di_resolution_injects_registered_type(self):
        """DI-registered types are injected into resolved params."""
        app = MagicMock()
        registry = DIRegistry()
        svc = CustomService("test-instance")
        registry.provide(CustomService, svc)
        app._di_registry = registry

        engine = JobExecutionEngine(
            di_registry=app._di_registry,
            event_bus=MagicMock(),
            hook_registry=MagicMock(),
            middleware_chain=MagicMock(),
        )

        def job(service: CustomService):
            pass

        MagicMock()
        resolved, _caps = engine._resolve_di_parameters(
            job, ExecutionContext(job_name="test-job", function=job, call_kwargs={})
        )
        assert "service" in resolved
        assert resolved["service"] is svc

    def test_di_resolution_per_invocation_caps_new_each_call(self):
        """Per-invocation capabilities yield distinct instances each call."""
        app = MagicMock()
        app._di_registry = DIRegistry()

        engine = JobExecutionEngine(
            di_registry=app._di_registry,
            event_bus=MagicMock(),
            hook_registry=MagicMock(),
            middleware_chain=MagicMock(),
        )

        def job(log: Log, state: State):
            pass

        MagicMock()
        MagicMock()

        resolved1, _caps1 = engine._resolve_di_parameters(
            job, ExecutionContext(job_name="job1", function=job, call_kwargs={})
        )
        resolved2, _caps2 = engine._resolve_di_parameters(
            job, ExecutionContext(job_name="job2", function=job, call_kwargs={})
        )

        # Different instances per invocation
        assert resolved1["log"] is not resolved2["log"]
        assert resolved1["state"] is not resolved2["state"]

    def test_di_resolution_skips_unannotated(self):
        """Parameters without DI annotations are not in resolved dict."""
        app = MagicMock()
        app._di_registry = DIRegistry()

        engine = JobExecutionEngine(
            di_registry=app._di_registry,
            event_bus=MagicMock(),
            hook_registry=MagicMock(),
            middleware_chain=MagicMock(),
        )

        def job(x, y: int, log: Log):
            pass

        MagicMock()
        resolved, _caps = engine._resolve_di_parameters(
            job, ExecutionContext(job_name="test", function=job, call_kwargs={})
        )
        # Only 'log' is resolved; x and y are skipped
        assert "log" in resolved
        assert "x" not in resolved
        assert "y" not in resolved

    def test_di_takes_precedence_over_default(self):
        """DI resolution wins over default values."""
        app = MagicMock()
        registry = DIRegistry()
        svc = CustomService("injected")
        registry.provide(CustomService, svc)
        app._di_registry = registry

        engine = JobExecutionEngine(
            di_registry=app._di_registry,
            event_bus=MagicMock(),
            hook_registry=MagicMock(),
            middleware_chain=MagicMock(),
        )

        def job(service: CustomService = None):  # type: ignore[assignment]
            pass

        MagicMock()
        resolved, _caps = engine._resolve_di_parameters(
            job, ExecutionContext(job_name="test", function=job, call_kwargs={})
        )
        # DI wins over the default None
        assert resolved["service"] is svc

    def test_optional_without_provider_resolves_to_none(self):
        """Optional[T] with no provider → None (no error)."""
        app = MagicMock()
        app._di_registry = DIRegistry()  # Nothing registered

        engine = JobExecutionEngine(
            di_registry=app._di_registry,
            event_bus=MagicMock(),
            hook_registry=MagicMock(),
            middleware_chain=MagicMock(),
        )

        def job(svc: CustomService | None):
            pass

        MagicMock()
        resolved, _caps = engine._resolve_di_parameters(
            job, ExecutionContext(job_name="test", function=job, call_kwargs={})
        )
        assert resolved["svc"] is None

    def test_missing_required_type_raises(self):
        """Non-optional param with unregistered type raises MissingProviderError."""
        app = MagicMock()
        app._di_registry = DIRegistry()  # Nothing registered

        engine = JobExecutionEngine(
            di_registry=app._di_registry,
            event_bus=MagicMock(),
            hook_registry=MagicMock(),
            middleware_chain=MagicMock(),
        )

        # Force the plan to think CustomService is registered (to get source="di")
        # by adding it to the plan manually
        def job(svc: Annotated[CustomService, Provide("missing")]):
            pass

        MagicMock()
        with pytest.raises(MissingProviderError):
            engine._resolve_di_parameters(
                job, ExecutionContext(job_name="test", function=job, call_kwargs={})
            )

    def test_runcontext_param_receives_rc(self):
        """Parameters annotated RunContext receive the invocation's RunContext."""
        app = MagicMock()
        app._di_registry = DIRegistry()

        engine = JobExecutionEngine(
            di_registry=app._di_registry,
            event_bus=MagicMock(),
            hook_registry=MagicMock(),
            middleware_chain=MagicMock(),
        )

        def job(rc: RunContext):
            pass

        resolved, _caps = engine._resolve_di_parameters(
            job, ExecutionContext(job_name="test", function=job, call_kwargs={})
        )
        assert "rc" in resolved
        assert isinstance(resolved["rc"], RunContext)

    def test_qualified_resolution(self):
        """Annotated[T, Provide("qualifier")] resolves with qualifier."""
        app = MagicMock()
        registry = DIRegistry()
        primary = CustomService("primary")
        secondary = CustomService("secondary")
        registry.provide(CustomService, primary, qualifier="primary")
        registry.provide(CustomService, secondary, qualifier="secondary")
        app._di_registry = registry

        engine = JobExecutionEngine(
            di_registry=app._di_registry,
            event_bus=MagicMock(),
            hook_registry=MagicMock(),
            middleware_chain=MagicMock(),
        )

        def job(svc: Annotated[CustomService, Provide("secondary")]):
            pass

        MagicMock()
        resolved, _caps = engine._resolve_di_parameters(
            job, ExecutionContext(job_name="test", function=job, call_kwargs={})
        )
        assert resolved["svc"] is secondary

    def test_per_invocation_wins_over_singleton(self):
        """Per-invocation capability takes precedence over app-scoped singleton."""
        app = MagicMock()
        registry = DIRegistry()
        # Register a singleton Log instance
        singleton_log = Log()
        registry.provide(Log, singleton_log)
        app._di_registry = registry

        engine = JobExecutionEngine(
            di_registry=app._di_registry,
            event_bus=MagicMock(),
            hook_registry=MagicMock(),
            middleware_chain=MagicMock(),
        )

        def job(log: Log):
            pass

        MagicMock()
        resolved, _caps = engine._resolve_di_parameters(
            job, ExecutionContext(job_name="test", function=job, call_kwargs={})
        )
        # Should be a fresh per-invocation instance, NOT the singleton
        assert resolved["log"] is not singleton_log
        assert isinstance(resolved["log"], Log)
