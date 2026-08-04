"""Tests for middleware DI parameter resolution.

Validates that middleware functions can declare type-annotated parameters
that are resolved from the DI registry using the same ResolutionPlan caching
mechanism as job functions.

Requirements validated:
- 21.1: MiddlewareChain resolves type-annotated middleware parameters from DIRegistry
- 21.2: Uses same ResolutionPlan caching (keyed by id(function)) for middleware functions
- 21.3: Per-invocation capability instances are shared between middleware and job
- 21.4: Middleware with RunContext parameter still receives the full RunContext (backward-compatible)
"""

# NOTE: Do NOT use `from __future__ import annotations` here.
# Middleware functions with locally-defined type annotations need runtime type objects
# (not strings) for DI resolution via get_type_hints() to work correctly.

from collections.abc import Generator
from typing import Any

from functualize._engine.resolution import ResolutionPlan
from functualize._primitives.di import DIRegistry
from functualize.job._middleware import (
    MiddlewareEntry,
    execute_middleware_chain,
)
from functualize.job.capabilities import Log, Perf
from functualize.job.context import RunContext

# --- Helpers ---


class FakeRunContext:
    """Minimal RunContext stand-in for testing backward compat."""

    pass


# Define at module level so get_type_hints can resolve it
class CustomService:
    """A custom service for testing DI resolution from registry."""

    pass


# --- Test: Requirement 21.1 - Middleware resolves type-annotated params ---


class TestMiddlewareDIResolution:
    """Tests that middleware functions receive DI-resolved parameters."""

    def test_middleware_receives_di_capability(self) -> None:
        """Middleware declaring Log param receives the Log instance from capabilities."""
        received: list[Any] = []

        def logging_middleware(log: Log) -> Generator[None]:
            received.append(log)
            yield

        log_instance = Log()
        capabilities: dict[type, Any] = {Log: log_instance}
        cache: dict[int, ResolutionPlan] = {}

        entry = MiddlewareEntry(logging_middleware, priority=0)
        entry._registration_order = 0

        def job() -> str:
            return "result"

        result = execute_middleware_chain(
            rc=None,
            middleware_entries=[entry],
            job_fn=job,
            job_args=(),
            job_kwargs={},
            capabilities=capabilities,
            di_registry=None,
            resolution_plan_cache=cache,
        )

        assert result == "result"
        assert len(received) == 1
        assert received[0] is log_instance

    def test_middleware_receives_multiple_capabilities(self) -> None:
        """Middleware declaring multiple DI params receives all of them."""
        received_log: list[Any] = []
        received_perf: list[Any] = []

        def multi_cap_middleware(log: Log, perf: Perf) -> Generator[None]:
            received_log.append(log)
            received_perf.append(perf)
            yield

        log_instance = Log()
        perf_instance = Perf()
        capabilities: dict[type, Any] = {Log: log_instance, Perf: perf_instance}
        cache: dict[int, ResolutionPlan] = {}

        entry = MiddlewareEntry(multi_cap_middleware, priority=0)
        entry._registration_order = 0

        def job() -> str:
            return "ok"

        execute_middleware_chain(
            rc=None,
            middleware_entries=[entry],
            job_fn=job,
            job_args=(),
            job_kwargs={},
            capabilities=capabilities,
            di_registry=None,
            resolution_plan_cache=cache,
        )

        assert received_log[0] is log_instance
        assert received_perf[0] is perf_instance

    def test_middleware_resolves_from_di_registry(self) -> None:
        """Middleware can resolve types registered in the DI registry (not just capabilities)."""
        received: list[Any] = []

        def service_middleware(svc: CustomService) -> Generator[None]:
            received.append(svc)
            yield

        service_instance = CustomService()
        registry = DIRegistry()
        registry.provide(CustomService, service_instance)

        capabilities: dict[type, Any] = {Log: Log()}
        cache: dict[int, ResolutionPlan] = {}

        entry = MiddlewareEntry(service_middleware, priority=0)
        entry._registration_order = 0

        def job() -> str:
            return "done"

        execute_middleware_chain(
            rc=None,
            middleware_entries=[entry],
            job_fn=job,
            job_args=(),
            job_kwargs={},
            capabilities=capabilities,
            di_registry=registry,
            resolution_plan_cache=cache,
        )

        assert received[0] is service_instance


# --- Test: Requirement 21.2 - ResolutionPlan caching ---


class TestMiddlewareResolutionPlanCaching:
    """Tests that middleware uses same ResolutionPlan caching mechanism."""

    def test_resolution_plan_cached_by_function_id(self) -> None:
        """The ResolutionPlan for a middleware function is cached by id(function)."""

        def my_middleware(log: Log) -> Generator[None]:
            yield

        capabilities: dict[type, Any] = {Log: Log()}
        cache: dict[int, ResolutionPlan] = {}

        entry = MiddlewareEntry(my_middleware, priority=0)
        entry._registration_order = 0

        def job() -> str:
            return "ok"

        # First call — plan should be built and cached
        execute_middleware_chain(
            rc=None,
            middleware_entries=[entry],
            job_fn=job,
            job_args=(),
            job_kwargs={},
            capabilities=capabilities,
            di_registry=None,
            resolution_plan_cache=cache,
        )

        assert id(my_middleware) in cache
        cached_plan = cache[id(my_middleware)]

        # Second call — same plan object should be reused (no re-inspection)
        execute_middleware_chain(
            rc=None,
            middleware_entries=[entry],
            job_fn=job,
            job_args=(),
            job_kwargs={},
            capabilities=capabilities,
            di_registry=None,
            resolution_plan_cache=cache,
        )

        assert cache[id(my_middleware)] is cached_plan

    def test_shared_cache_with_job_functions(self) -> None:
        """Middleware shares the same cache dict as job functions (passed from engine)."""
        # Simulate a pre-populated cache (as the engine would have from job resolution)
        cache: dict[int, ResolutionPlan] = {}

        def my_middleware(log: Log) -> Generator[None]:
            yield

        # Pre-populate cache with a fake job entry to verify sharing
        cache[999] = ResolutionPlan(function_id=999, params=())

        capabilities: dict[type, Any] = {Log: Log()}
        entry = MiddlewareEntry(my_middleware, priority=0)
        entry._registration_order = 0

        def job() -> str:
            return "ok"

        execute_middleware_chain(
            rc=None,
            middleware_entries=[entry],
            job_fn=job,
            job_args=(),
            job_kwargs={},
            capabilities=capabilities,
            di_registry=None,
            resolution_plan_cache=cache,
        )

        # Both the pre-existing job entry and new middleware entry are in cache
        assert 999 in cache
        assert id(my_middleware) in cache


# --- Test: Requirement 21.3 - Shared per-invocation instances ---


class TestMiddlewareSharedInstances:
    """Tests that middleware and job receive the same per-invocation capability instances."""

    def test_middleware_receives_same_instance_as_job(self) -> None:
        """The middleware receives the exact same capability instance the job would get."""
        middleware_log: list[Any] = []
        job_log: list[Any] = []

        log_instance = Log()
        capabilities: dict[type, Any] = {Log: log_instance}
        cache: dict[int, ResolutionPlan] = {}

        def timing_middleware(log: Log) -> Generator[None]:
            middleware_log.append(log)
            yield

        entry = MiddlewareEntry(timing_middleware, priority=0)
        entry._registration_order = 0

        def job() -> str:
            # In real usage, the job also receives the same Log instance via DI
            # We verify the middleware got the same object
            job_log.append(capabilities[Log])
            return "ok"

        execute_middleware_chain(
            rc=None,
            middleware_entries=[entry],
            job_fn=job,
            job_args=(),
            job_kwargs={},
            capabilities=capabilities,
            di_registry=None,
            resolution_plan_cache=cache,
        )

        # Same object identity
        assert middleware_log[0] is job_log[0]
        assert middleware_log[0] is log_instance

    def test_multiple_middleware_share_same_instance(self) -> None:
        """Multiple middleware functions receive the same capability instance."""
        received_instances: list[Any] = []

        def mw1(log: Log) -> Generator[None]:
            received_instances.append(("mw1", log))
            yield

        def mw2(log: Log) -> Generator[None]:
            received_instances.append(("mw2", log))
            yield

        log_instance = Log()
        capabilities: dict[type, Any] = {Log: log_instance}
        cache: dict[int, ResolutionPlan] = {}

        entries = [
            MiddlewareEntry(mw1, priority=0),
            MiddlewareEntry(mw2, priority=1),
        ]
        entries[0]._registration_order = 0
        entries[1]._registration_order = 1

        def job() -> str:
            return "ok"

        execute_middleware_chain(
            rc=None,
            middleware_entries=entries,
            job_fn=job,
            job_args=(),
            job_kwargs={},
            capabilities=capabilities,
            di_registry=None,
            resolution_plan_cache=cache,
        )

        assert received_instances[0][1] is log_instance
        assert received_instances[1][1] is log_instance


# --- Test: Requirement 21.4 - Backward compat with RunContext param ---


class TestMiddlewareRunContextBackwardCompat:
    """Tests that middleware with RunContext parameter still receives it."""

    def test_middleware_with_runcontext_param_receives_rc(self) -> None:
        """Middleware annotated with RunContext still gets the full RunContext."""
        received: list[Any] = []

        def legacy_middleware(rc: RunContext) -> Generator[None]:
            received.append(rc)
            yield

        fake_rc = FakeRunContext()
        capabilities: dict[type, Any] = {Log: Log()}
        cache: dict[int, ResolutionPlan] = {}

        entry = MiddlewareEntry(legacy_middleware, priority=0)
        entry._registration_order = 0

        def job() -> str:
            return "ok"

        execute_middleware_chain(
            rc=fake_rc,
            middleware_entries=[entry],
            job_fn=job,
            job_args=(),
            job_kwargs={},
            capabilities=capabilities,
            di_registry=None,
            resolution_plan_cache=cache,
        )

        assert received[0] is fake_rc

    def test_middleware_with_no_annotations_gets_rc_fallback(self) -> None:
        """Middleware without type annotations falls back to receiving rc positionally."""
        received: list[Any] = []

        def untyped_middleware(ctx) -> Generator[None]:
            received.append(ctx)
            yield

        fake_rc = FakeRunContext()
        capabilities: dict[type, Any] = {Log: Log()}
        cache: dict[int, ResolutionPlan] = {}

        entry = MiddlewareEntry(untyped_middleware, priority=0)
        entry._registration_order = 0

        def job() -> str:
            return "ok"

        execute_middleware_chain(
            rc=fake_rc,
            middleware_entries=[entry],
            job_fn=job,
            job_args=(),
            job_kwargs={},
            capabilities=capabilities,
            di_registry=None,
            resolution_plan_cache=cache,
        )

        # Falls back to legacy path: middleware(rc)
        assert received[0] is fake_rc

    def test_legacy_middleware_works_without_di_infrastructure(self) -> None:
        """When no DI infrastructure is provided, middleware works as before."""
        received: list[Any] = []

        def old_middleware(rc) -> Generator[None]:
            received.append(rc)
            yield

        fake_rc = FakeRunContext()

        entry = MiddlewareEntry(old_middleware, priority=0)
        entry._registration_order = 0

        def job() -> str:
            return "ok"

        # No capabilities/di_registry/cache — pure legacy path
        result = execute_middleware_chain(
            rc=fake_rc,
            middleware_entries=[entry],
            job_fn=job,
            job_args=(),
            job_kwargs={},
        )

        assert result == "ok"
        assert received[0] is fake_rc

    def test_mixed_middleware_di_and_legacy(self) -> None:
        """Mix of DI-aware and legacy middleware both work in same chain."""
        order: list[str] = []

        def di_middleware(log: Log) -> Generator[None]:
            order.append("di:pre")
            yield
            order.append("di:post")

        def legacy_middleware(rc: RunContext) -> Generator[None]:
            order.append("legacy:pre")
            yield
            order.append("legacy:post")

        log_instance = Log()
        fake_rc = FakeRunContext()
        capabilities: dict[type, Any] = {Log: log_instance}
        cache: dict[int, ResolutionPlan] = {}

        entries = [
            MiddlewareEntry(di_middleware, priority=0),
            MiddlewareEntry(legacy_middleware, priority=1),
        ]
        entries[0]._registration_order = 0
        entries[1]._registration_order = 1

        def job() -> str:
            order.append("job")
            return "ok"

        execute_middleware_chain(
            rc=fake_rc,
            middleware_entries=entries,
            job_fn=job,
            job_args=(),
            job_kwargs={},
            capabilities=capabilities,
            di_registry=None,
            resolution_plan_cache=cache,
        )

        assert order == ["di:pre", "legacy:pre", "job", "legacy:post", "di:post"]
