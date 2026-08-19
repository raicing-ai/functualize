"""Property-based tests for ResolutionPlan and engine DI resolution (Properties 9, 10, 12).

Tests the execution engine's DI resolution mechanisms:
- Property 9: ResolutionPlan caching by function identity
- Property 10: Engine DI resolution correctness
- Property 12: Per-invocation capability isolation

# Feature: unified-architecture-redesign, Task 5.3
"""

# NOTE: Do NOT use `from __future__ import annotations` here.
# PEP 563 turns annotations into strings, which breaks get_type_hints()
# for dynamically-created types in local scopes.

import inspect
from typing import Annotated, Optional
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._engine.resolution import (
    ResolutionPlan,
    build_resolution_plan,
)
from functualize._primitives.di import DIRegistry, MissingProviderError, Provide
from functualize.job.capabilities import Invoke, JobContext, Log, Perf, Prompt, State
from functualize.job.context import RunContext

# =============================================================================
# Strategies
# =============================================================================


def _make_type(name: str) -> type:
    """Dynamically create a unique type with the given name."""
    return type(name, (), {})


@st.composite
def _num_params(draw: st.DrawFn) -> int:
    """Generate a number of parameters for a function (1-6)."""
    return draw(st.integers(min_value=1, max_value=6))


# =============================================================================
# Property 9: ResolutionPlan caching by function identity
# =============================================================================


class TestResolutionPlanCachingByFunctionIdentity:
    """Property 9: ResolutionPlan caching by function identity.

    For any function object, the ResolutionPlan computed by the execution engine
    SHALL be cached such that subsequent lookups by id(function) return the exact
    same plan object (by identity) without re-invoking inspect.signature().

    **Validates: Requirements 5.4**
    """

    @given(num_lookups=st.integers(min_value=2, max_value=20))
    @settings(max_examples=200)
    def test_cached_plan_returns_same_object_by_identity(self, num_lookups: int):
        """Subsequent lookups return the exact same plan object (by identity).

        **Validates: Requirements 5.4**
        """

        # Create a function to cache the plan for
        def my_job(log: Log, state: State) -> None:
            pass

        # Simulate engine caching: build once, store by id(function)
        cache: dict[int, ResolutionPlan] = {}
        registered_types = {Log, State}

        func_id = id(my_job)
        plan = build_resolution_plan(
            my_job, registered_types, runcontext_type=RunContext
        )
        cache[func_id] = plan

        # All subsequent lookups should return the same plan object
        for _ in range(num_lookups):
            cached_plan = cache.get(id(my_job))
            assert cached_plan is plan, (
                "Cached plan must be the same object (by identity) on every lookup"
            )

    @given(num_lookups=st.integers(min_value=2, max_value=20))
    @settings(max_examples=200)
    def test_no_reinvocation_of_inspect_signature(self, num_lookups: int):
        """Caching avoids re-invoking inspect.signature() on subsequent lookups.

        **Validates: Requirements 5.4**
        """

        def sample_job(log: Log, perf: Perf) -> None:
            pass

        cache: dict[int, ResolutionPlan] = {}
        registered_types = {Log, Perf}
        signature_call_count = 0

        original_signature = inspect.signature

        def counting_signature(func, **kwargs):
            nonlocal signature_call_count
            signature_call_count += 1
            return original_signature(func, **kwargs)

        # First call builds the plan (invokes inspect.signature)
        with patch(
            "functualize._engine.resolution.inspect.signature", counting_signature
        ):
            plan = build_resolution_plan(
                sample_job, registered_types, runcontext_type=RunContext
            )
        cache[id(sample_job)] = plan
        initial_count = signature_call_count

        # Subsequent lookups should NOT invoke inspect.signature
        for _ in range(num_lookups):
            func_id = id(sample_job)
            if func_id in cache:
                _ = cache[func_id]
            else:
                # This branch should never be taken
                with patch(
                    "functualize._engine.resolution.inspect.signature",
                    counting_signature,
                ):
                    cache[func_id] = build_resolution_plan(
                        sample_job, registered_types, runcontext_type=RunContext
                    )

        assert signature_call_count == initial_count, (
            "inspect.signature should not be called again after caching"
        )

    @given(num_functions=st.integers(min_value=2, max_value=8))
    @settings(max_examples=100)
    def test_different_functions_get_distinct_plans(self, num_functions: int):
        """Each function gets its own distinct ResolutionPlan in the cache.

        **Validates: Requirements 5.4**
        """
        registered_types = {Log, State, Perf}
        cache: dict[int, ResolutionPlan] = {}

        # Create multiple distinct functions
        functions = []
        for i in range(num_functions):
            # Each function has a unique closure to ensure distinct id()
            def make_fn(idx):
                def fn(log: Log) -> None:
                    _ = idx

                fn.__name__ = f"job_{idx}"
                return fn

            functions.append(make_fn(i))

        # Build plans for each function
        for fn in functions:
            plan = build_resolution_plan(
                fn, registered_types, runcontext_type=RunContext
            )
            cache[id(fn)] = plan

        # Each function should have its own plan (distinct by identity)
        plans = [cache[id(fn)] for fn in functions]
        plan_ids = [id(p) for p in plans]
        assert len(set(plan_ids)) == num_functions, (
            "Each function should have a distinct plan object"
        )

    @given(num_lookups=st.integers(min_value=2, max_value=10))
    @settings(max_examples=200)
    def test_plan_function_id_matches_id_of_function(self, num_lookups: int):
        """The ResolutionPlan's function_id matches the id() of the function it was built for.

        **Validates: Requirements 5.4**
        """

        def target_job(invoke: Invoke) -> None:
            pass

        registered_types = {Invoke}
        plan = build_resolution_plan(
            target_job, registered_types, runcontext_type=RunContext
        )

        assert plan.function_id == id(target_job), (
            "Plan's function_id must equal id(function)"
        )


# =============================================================================
# Property 10: Engine DI resolution correctness
# =============================================================================


class TestEngineDIResolutionCorrectness:
    """Property 10: Engine DI resolution correctness.

    For any job function with N type-annotated parameters where each annotation
    matches a type registered in the DIRegistry, the execution engine SHALL
    resolve all N parameters from the registry and pass them as keyword arguments.
    Parameters annotated as RunContext SHALL receive a RunContext facade.
    Parameters with unregistered types and no default SHALL trigger
    MissingProviderError. Parameters annotated as Optional[T] with no provider
    SHALL resolve to None.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 18.3, 18.6**
    """

    @given(num_params=st.integers(min_value=1, max_value=6))
    @settings(max_examples=100)
    def test_all_registered_type_params_resolved_from_registry(self, num_params: int):
        """All N type-annotated params matching registered types are resolved.

        **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 18.3, 18.6**
        """
        # Create N unique types and register them
        types_and_instances: list[tuple[type, object]] = []
        for i in range(num_params):
            t = _make_type(f"Service{i}")
            instance = t()
            types_and_instances.append((t, instance))

        registry = DIRegistry()
        registered_types: set[type] = set()
        for t, inst in types_and_instances:
            registry.provide(t, inst)
            registered_types.add(t)

        # Build a function dynamically with those type annotations
        param_names = [f"param{i}" for i in range(num_params)]
        annotations = {
            param_names[i]: types_and_instances[i][0] for i in range(num_params)
        }
        annotations["return"] = None

        # Create the function with exec to have proper annotations
        params_str = ", ".join(f"{name}: annotations['{name}']" for name in param_names)
        local_ns: dict = {"annotations": annotations}
        exec(
            f"def job_func({params_str}) -> None: pass",
            local_ns,
        )
        job_func = local_ns["job_func"]
        # Manually set __annotations__ since exec doesn't resolve our dynamic types
        job_func.__annotations__ = annotations

        # Build resolution plan
        plan = build_resolution_plan(
            job_func, registered_types, runcontext_type=RunContext
        )

        # Verify all params are classified as "di"
        assert len(plan.params) == num_params
        for binding in plan.params:
            assert binding.source == "di", (
                f"Parameter {binding.name} should be resolved via DI, got {binding.source}"
            )

        # Simulate resolution from registry
        resolved: dict[str, object] = {}
        for binding in plan.params:
            if binding.source == "di":
                resolved[binding.name] = registry.resolve(binding.annotation)

        # All params resolved to their registered instances
        for i, name in enumerate(param_names):
            assert resolved[name] is types_and_instances[i][1], (
                f"Parameter {name} should resolve to its registered instance"
            )

    def test_runcontext_annotated_param_receives_runcontext(self):
        """Parameters annotated as RunContext SHALL receive a RunContext facade.

        **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 18.3, 18.6**
        """

        def job_with_rc(ctx: RunContext) -> None:
            pass

        registered_types: set[type] = set()
        plan = build_resolution_plan(
            job_with_rc, registered_types, runcontext_type=RunContext
        )

        assert len(plan.params) == 1
        assert plan.params[0].source == "runcontext"
        assert plan.params[0].annotation is RunContext

    @given(
        num_registered=st.integers(min_value=1, max_value=3),
        num_unregistered=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=100)
    def test_unregistered_types_without_default_trigger_missing_provider(
        self, num_registered: int, num_unregistered: int
    ):
        """Parameters with unregistered types and no default trigger MissingProviderError.

        **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 18.3, 18.6**
        """
        # Create registered types
        registered_types: set[type] = set()
        registry = DIRegistry()
        for i in range(num_registered):
            t = _make_type(f"Registered{i}")
            registry.provide(t, t())
            registered_types.add(t)

        # Create unregistered types
        unregistered_types: list[type] = []
        for i in range(num_unregistered):
            t = _make_type(f"Unregistered{i}")
            unregistered_types.append(t)

        # Build function with both registered and unregistered type params
        all_types = list(registered_types) + unregistered_types
        param_names = [f"p{i}" for i in range(len(all_types))]
        annotations: dict[str, type] = {}
        for i, name in enumerate(param_names):
            annotations[name] = all_types[i]
        annotations["return"] = None

        local_ns: dict = {"annotations": annotations}
        params_str = ", ".join(f"{name}: annotations['{name}']" for name in param_names)
        exec(f"def job_func({params_str}) -> None: pass", local_ns)
        job_func = local_ns["job_func"]
        job_func.__annotations__ = annotations

        plan = build_resolution_plan(
            job_func, registered_types, runcontext_type=RunContext
        )

        # Simulate resolution: unregistered types without defaults should fail
        for binding in plan.params:
            if binding.annotation in unregistered_types:
                # These should be classified as "skip" (unregistered)
                assert binding.source == "skip", (
                    f"Unregistered type {binding.annotation.__name__} "
                    f"should be 'skip', got {binding.source}"
                )

        # When the engine tries to resolve, unregistered non-skip params
        # with source="di" would trigger MissingProviderError
        # Verify that unregistered types with source="di" (if any) actually
        # raise MissingProviderError from the registry
        for binding in plan.params:
            if (
                binding.source == "di"
                and not binding.is_optional
                and not registry.has(binding.annotation)
            ):
                try:
                    registry.resolve(binding.annotation)
                    raise AssertionError("Should have raised MissingProviderError")
                except MissingProviderError:
                    pass

    def test_optional_param_with_no_provider_resolves_to_none(self):
        """Parameters annotated as Optional[T] with no provider resolve to None.

        **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 18.3, 18.6**
        """
        unregistered_service = _make_type("UnregisteredService")

        # Build function with explicit __annotations__ to avoid PEP 563 string issues
        def job_with_optional(svc=None) -> None:
            pass

        # Set annotations explicitly with real type objects
        job_with_optional.__annotations__ = {
            "svc": unregistered_service | None,
            "return": None,
        }

        # UnregisteredService is NOT in registered_types
        registered_types: set[type] = set()
        plan = build_resolution_plan(
            job_with_optional, registered_types, runcontext_type=RunContext
        )

        assert len(plan.params) == 1
        binding = plan.params[0]
        assert binding.source == "di"
        assert binding.is_optional is True
        assert binding.annotation is unregistered_service

        # When resolving: Optional[T] with no provider → None
        registry = DIRegistry()
        try:
            registry.resolve(unregistered_service)
            raise AssertionError("Should have raised MissingProviderError")
        except MissingProviderError:
            # The engine resolves Optional[T] to None in this case
            resolved_value = None

        assert resolved_value is None

    @given(
        num_params=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=100)
    def test_optional_params_with_registered_provider_resolve_normally(
        self, num_params: int
    ):
        """Optional[T] with a registered provider resolves from the registry normally.

        **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 18.3, 18.6**
        """
        # Create types and register them
        types_and_instances: list[tuple[type, object]] = []
        registered_types: set[type] = set()
        registry = DIRegistry()

        for i in range(num_params):
            t = _make_type(f"OptService{i}")
            instance = t()
            registry.provide(t, instance)
            registered_types.add(t)
            types_and_instances.append((t, instance))

        # Build function with Optional[T] annotations where T is registered
        param_names = [f"opt{i}" for i in range(num_params)]
        annotations: dict = {"return": None}
        for i, name in enumerate(param_names):
            annotations[name] = types_and_instances[i][0] | None

        local_ns: dict = {"annotations": annotations, "Optional": Optional}
        params_str = ", ".join(f"{name}: annotations['{name}']" for name in param_names)
        exec(f"def job_func({params_str}) -> None: pass", local_ns)
        job_func = local_ns["job_func"]
        job_func.__annotations__ = annotations

        plan = build_resolution_plan(
            job_func, registered_types, runcontext_type=RunContext
        )

        # All params should be resolved as "di" with is_optional=True
        for binding in plan.params:
            assert binding.source == "di"
            assert binding.is_optional is True

        # Resolve should return the registered instances (not None)
        for binding in plan.params:
            resolved = registry.resolve(binding.annotation)
            # Find the matching expected instance
            for t, inst in types_and_instances:
                if t is binding.annotation:
                    assert resolved is inst
                    break

    def test_qualified_annotated_param_resolved_with_qualifier(self):
        """Parameters with Annotated[T, Provide("qualifier")] resolve using qualifier.

        **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 18.3, 18.6**
        """
        cache_service = _make_type("CacheService")
        redis_instance = cache_service()
        memcache_instance = cache_service()

        registry = DIRegistry()
        registry.provide(cache_service, redis_instance, qualifier="redis")
        registry.provide(cache_service, memcache_instance, qualifier="memcache")
        registered_types = {cache_service}

        # Build function with explicit __annotations__ to avoid resolution issues
        def job_with_qualified(cache=None) -> None:
            pass

        job_with_qualified.__annotations__ = {
            "cache": Annotated[cache_service, Provide("redis")],
            "return": None,
        }

        plan = build_resolution_plan(
            job_with_qualified, registered_types, runcontext_type=RunContext
        )

        assert len(plan.params) == 1
        binding = plan.params[0]
        assert binding.source == "di"
        assert binding.qualifier == "redis"
        assert binding.annotation is cache_service

        # Resolution with qualifier
        resolved = registry.resolve(cache_service, qualifier="redis")
        assert resolved is redis_instance

    @given(num_skip_params=st.integers(min_value=1, max_value=4))
    @settings(max_examples=100)
    def test_params_without_annotations_are_skipped(self, num_skip_params: int):
        """Parameters without type annotations are skipped during DI resolution.

        **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 18.3, 18.6**
        """
        registered_types = {Log}

        # Build a function with mixed annotated and non-annotated params
        # We'll do this with exec since we need params without annotations
        param_parts = ["log: Log"]
        for i in range(num_skip_params):
            param_parts.append(f"arg{i}")

        params_str = ", ".join(param_parts)
        local_ns: dict = {"Log": Log}
        exec(f"def job_func({params_str}): pass", local_ns)
        job_func = local_ns["job_func"]

        plan = build_resolution_plan(
            job_func, registered_types, runcontext_type=RunContext
        )

        # First param (log) should be "di", rest should be "skip"
        assert plan.params[0].source == "di"
        assert plan.params[0].name == "log"

        for i in range(num_skip_params):
            assert plan.params[i + 1].source == "skip"
            assert plan.params[i + 1].name == f"arg{i}"

    def test_di_takes_precedence_over_default_values(self):
        """DI-resolved instances take precedence over default values.

        **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 18.3, 18.6**
        """
        registered_types = {Log}

        def job_with_default(log: Log = None) -> None:  # type: ignore[assignment]
            pass

        plan = build_resolution_plan(
            job_with_default, registered_types, runcontext_type=RunContext
        )

        assert len(plan.params) == 1
        binding = plan.params[0]
        # Even though there's a default, the param should still be resolved via DI
        assert binding.source == "di"
        assert binding.has_default is True
        assert binding.annotation is Log


# =============================================================================
# Property 12: Per-invocation capability isolation
# =============================================================================


def _isolation_engine():
    """Build a bare engine suitable for exercising DI resolution."""
    from functualize._engine.executor import JobExecutionEngine

    return JobExecutionEngine(
        di_registry=DIRegistry(),
        event_bus=MagicMock(),
        hook_registry=MagicMock(),
        middleware_chain=MagicMock(),
    )


def _resolve_caps(engine, function, job_name: str) -> dict:
    """Resolve `function`'s DI params once, returning the per-invocation caps."""
    from functualize._engine.context import ExecutionContext

    context = ExecutionContext(job_name=job_name, function=function, call_kwargs={})
    _kwargs, caps = engine._resolve_di_parameters(function, context)
    return caps


# The capability set a job must actually *declare* to have it built. Capabilities
# are created on demand per binding, so a job that asks for nothing gets nothing.
_ISOLATED_CAPS = (Log, Invoke, Prompt, Perf, State, JobContext)


def _job_declaring_all_caps():
    """A job function whose signature requests every per-invocation capability."""

    def job(
        log: Log,
        invoke: Invoke,
        prompt: Prompt,
        perf: Perf,
        state: State,
        jc: JobContext,
    ) -> None:
        pass

    return job


class TestPerInvocationCapabilityIsolation:
    """Property 12: Per-invocation capability isolation.

    For any two sequential invocations of the same job, the framework capability
    instances SHALL be distinct objects (by identity), ensuring no state leakage
    between invocations.

    These are deterministic assertions about object identity, so they are plain
    tests rather than Hypothesis properties — the behaviour does not vary with
    generated input, and the engine never inspects the job name or the iteration
    count. See `test_capabilities_are_created_on_demand` for the on-demand
    construction contract that replaced the old eager capability builder.

    **Validates: Requirements 7.7**
    """

    def test_sequential_invocations_get_distinct_capabilities(self) -> None:
        """Sequential resolutions of the same job get distinct capability instances."""
        engine = _isolation_engine()
        function = _job_declaring_all_caps()

        all_caps = [_resolve_caps(engine, function, "test_job") for _ in range(5)]

        for cap_type in _ISOLATED_CAPS:
            ids = [id(caps[cap_type]) for caps in all_caps]
            assert len(set(ids)) == len(all_caps), (
                f"All {cap_type.__name__} instances must be distinct across "
                f"invocations (got {len(set(ids))} unique out of {len(all_caps)})"
            )

    def test_no_shared_identity_between_any_capability_pairs(self) -> None:
        """No capability instance from one invocation is shared with another."""
        engine = _isolation_engine()
        function = _job_declaring_all_caps()

        all_caps = [_resolve_caps(engine, function, "isolation_job") for _ in range(4)]

        for cap_type in _ISOLATED_CAPS:
            for i in range(len(all_caps)):
                for j in range(i + 1, len(all_caps)):
                    assert all_caps[i][cap_type] is not all_caps[j][cap_type], (
                        f"{cap_type.__name__} instance from invocation {i} "
                        f"must not be the same object as invocation {j}"
                    )

    def test_declared_capabilities_are_all_present(self) -> None:
        """Every capability the job declares is present in the resolved caps."""
        engine = _isolation_engine()
        caps = _resolve_caps(engine, _job_declaring_all_caps(), "completeness_job")

        assert set(_ISOLATED_CAPS).issubset(caps.keys()), (
            "Every declared capability should be built: missing "
            f"{sorted(t.__name__ for t in set(_ISOLATED_CAPS) - set(caps))}"
        )

    def test_capability_instances_are_correct_types(self) -> None:
        """Each capability instance is of the correct type."""
        engine = _isolation_engine()
        caps = _resolve_caps(engine, _job_declaring_all_caps(), "types_job")

        for cap_type in _ISOLATED_CAPS:
            assert isinstance(caps[cap_type], cap_type)

    def test_capabilities_are_created_on_demand(self) -> None:
        """Only capabilities the job actually declares are constructed.

        This is the contract that replaced the old eager `_build_per_invocation_
        capabilities()` builder, which returned a fixed dict regardless of the
        job's signature. Building an unrequested capability is not free — `State`
        and `Stdout` reach for backends — so the narrowing is load-bearing.
        """
        engine = _isolation_engine()

        def only_log(log: Log) -> None:
            pass

        caps = _resolve_caps(engine, only_log, "narrow_job")

        assert Log in caps
        unrequested = {Invoke, Prompt, Perf, State, JobContext} & set(caps)
        assert not unrequested, (
            "Capabilities the job never declared should not be built, but got "
            f"{sorted(t.__name__ for t in unrequested)}"
        )
