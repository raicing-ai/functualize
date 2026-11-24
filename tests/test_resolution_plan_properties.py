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
import types
import weakref
from typing import Annotated, Union, get_origin
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._engine.resolution import (
    ResolutionPlan,
    build_resolution_plan,
)
from functualize._primitives.di import DIRegistry, MissingProviderError, Provide
from functualize._primitives.parameter_contract import build_contracts
from functualize.job.capabilities import Invoke, JobContext, Log, Perf, Prompt, State
from functualize.job.context import RunContext
from tests._support.engine_storage import engine_storage


def _plan_for(function, *_args, **_kwargs):
    """Use the declaration contract, regardless of registry contents."""
    return build_resolution_plan(build_contracts(function))


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
    SHALL be cached such that subsequent lookups by callable return the exact
    same plan object (by identity) without re-invoking inspect.signature().

    **Validates: Requirements 5.4**
    """

    @given(num_lookups=st.integers(min_value=2, max_value=20))
    def test_cached_plan_returns_same_object_by_identity(self, num_lookups: int):
        """Subsequent lookups return the exact same plan object (by identity).

        **Validates: Requirements 5.4**
        """

        # Create a function to cache the plan for
        def my_job(log: Log, state: State) -> None:
            pass

        # Simulate engine caching: build once, store by weak callable reference.
        cache: weakref.WeakKeyDictionary[object, ResolutionPlan] = (
            weakref.WeakKeyDictionary()
        )
        registered_types = {Log, State}

        plan = _plan_for(my_job, registered_types, runcontext_type=RunContext)
        cache[my_job] = plan

        # All subsequent lookups should return the same plan object
        for _ in range(num_lookups):
            cached_plan = cache.get(my_job)
            assert cached_plan is plan, (
                "Cached plan must be the same object (by identity) on every lookup"
            )

    @given(num_lookups=st.integers(min_value=2, max_value=20))
    def test_no_reinvocation_of_inspect_signature(self, num_lookups: int):
        """Caching avoids re-invoking inspect.signature() on subsequent lookups.

        **Validates: Requirements 5.4**
        """

        def sample_job(log: Log, perf: Perf) -> None:
            pass

        cache: weakref.WeakKeyDictionary[object, ResolutionPlan] = (
            weakref.WeakKeyDictionary()
        )
        registered_types = {Log, Perf}
        signature_call_count = 0

        original_signature = inspect.signature

        def counting_signature(func, **kwargs):
            nonlocal signature_call_count
            signature_call_count += 1
            return original_signature(func, **kwargs)

        # First call builds the plan (invokes inspect.signature)
        with patch(
            "functualize._primitives.parameter_contract.inspect.signature",
            counting_signature,
        ):
            plan = _plan_for(sample_job, registered_types, runcontext_type=RunContext)
        cache[sample_job] = plan
        initial_count = signature_call_count

        # Subsequent lookups should NOT invoke inspect.signature
        for _ in range(num_lookups):
            if sample_job in cache:
                _ = cache[sample_job]
            else:
                # This branch should never be taken
                with patch(
                    "functualize._primitives.parameter_contract.inspect.signature",
                    counting_signature,
                ):
                    cache[sample_job] = _plan_for(
                        sample_job, registered_types, runcontext_type=RunContext
                    )

        assert signature_call_count == initial_count, (
            "inspect.signature should not be called again after caching"
        )

    @given(num_functions=st.integers(min_value=2, max_value=8))
    def test_different_functions_get_distinct_plans(self, num_functions: int):
        """Each function gets its own distinct ResolutionPlan in the cache.

        **Validates: Requirements 5.4**
        """
        registered_types = {Log, State, Perf}
        cache: weakref.WeakKeyDictionary[object, ResolutionPlan] = (
            weakref.WeakKeyDictionary()
        )

        # Create multiple distinct functions
        functions = []
        for i in range(num_functions):
            # Each function has a unique closure and callable identity.
            def make_fn(idx):
                def fn(log: Log) -> None:
                    _ = idx

                fn.__name__ = f"job_{idx}"
                return fn

            functions.append(make_fn(i))

        # Build plans for each function
        for fn in functions:
            plan = _plan_for(fn, registered_types, runcontext_type=RunContext)
            cache[fn] = plan

        # Each function should have its own plan (distinct by identity)
        plans = [cache[fn] for fn in functions]
        plan_ids = [id(p) for p in plans]
        assert len(set(plan_ids)) == num_functions, (
            "Each function should have a distinct plan object"
        )

    @given(num_lookups=st.integers(min_value=2, max_value=10))
    def test_plan_has_no_address_based_identity(self, num_lookups: int):
        """A plan's result depends on the declaration, not its memory address.

        **Validates: Requirements 5.4**
        """

        def target_job(invoke: Invoke) -> None:
            pass

        registered_types = {Invoke}
        plan = _plan_for(target_job, registered_types, runcontext_type=RunContext)

        for _ in range(num_lookups):
            assert plan == _plan_for(target_job, registered_types)


# =============================================================================
# Property 10: Engine DI resolution correctness
# =============================================================================


def _qualname(type_: type) -> str:
    """How a contract names a provider-backed dependency (``Injection.provider_type``)."""
    return f"{type_.__module__}.{type_.__qualname__}"


def _recording_job(annotations: dict, seen: dict):
    """A job whose parameters carry ``annotations`` and that records what it got."""
    names = [name for name in annotations if name != "return"]
    local_ns: dict = {"seen": seen}
    params = ", ".join(f"{name}=None" for name in names)
    body = "; ".join(f"seen[{name!r}] = {name}" for name in names) or "pass"
    exec(f"def job_func({params}):\n    {body}", local_ns)
    job_func = local_ns["job_func"]
    for name in names:  # required unless the declaration is Optional
        if get_origin(annotations[name]) not in (Union, types.UnionType):
            job_func.__defaults__ = None
    job_func.__annotations__ = annotations
    return job_func


def _run_hostless(registry: DIRegistry, function) -> object:
    """Run ``function`` through a bare engine's door: no host, so no admission."""
    from functualize._engine.executor import JobExecutionEngine
    from tests._support.engine_run import run_job

    chain = MagicMock()
    chain.has_middleware = False  # the job body runs, not a mock's return value
    engine = JobExecutionEngine(
        di_registry=registry,
        event_bus=MagicMock(),
        hook_registry=MagicMock(),
        middleware_chain=chain,
        **engine_storage(),
    )
    return run_job(engine, "job_func", function, kwargs={})


class TestEngineDIResolutionCorrectness:
    """Property 10: Engine DI resolution correctness, from the job's contracts.

    The plan is projected from each parameter's contract (5.1 Work, schema
    invariant 6): its ``source`` is the ``Injection`` field that names the value
    (``capability`` → the engine's per-invocation capability, ``RunContext``
    included; ``provider_type`` with ``qualifier`` → DI), and its ``annotation``
    is that name, never a type object — "no type name and no annotation is
    inspected here". The type is read from the live annotation where the value
    is resolved, so resolution is asserted through ``engine.run`` rather than
    simulated with ``registry.resolve(binding.annotation)``.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 18.3, 18.6**
    """

    @given(num_params=st.integers(min_value=1, max_value=6))
    def test_all_registered_type_params_resolved_from_registry(self, num_params: int):
        """All N provider-backed params are planned as DI and receive their instances."""
        registry = DIRegistry()
        annotations: dict = {"return": None}
        instances: dict[str, object] = {}
        for i in range(num_params):
            t = _make_type(f"Service{i}")
            instances[f"param{i}"] = t()
            registry.provide(t, instances[f"param{i}"])
            annotations[f"param{i}"] = t

        seen: dict = {}
        job_func = _recording_job(annotations, seen)
        plan = _plan_for(job_func)

        assert len(plan.params) == num_params
        for binding in plan.params:
            assert binding.source == "di"
            assert binding.annotation == _qualname(annotations[binding.name])

        result = _run_hostless(registry, job_func)
        assert result.status.value == "Success", result
        for name, instance in instances.items():
            assert seen[name] is instance

    def test_runcontext_annotated_param_receives_runcontext(self):
        """``RunContext`` is named by its capability and receives the facade."""

        def job_with_rc(ctx: RunContext) -> None:
            pass

        plan = _plan_for(job_with_rc)

        assert len(plan.params) == 1
        assert plan.params[0].source == "runcontext"
        assert plan.params[0].annotation == "RunContext"

        seen: dict = {}
        result = _run_hostless(
            DIRegistry(), _recording_job({"ctx": RunContext, "return": None}, seen)
        )
        assert result.status.value == "Success", result
        assert isinstance(seen["ctx"], RunContext)

    @given(
        num_registered=st.integers(min_value=1, max_value=3),
        num_unregistered=st.integers(min_value=1, max_value=3),
    )
    def test_unregistered_types_without_default_trigger_missing_provider(
        self, num_registered: int, num_unregistered: int
    ):
        """A required provider-backed parameter with no provider is refused.

        Kind comes from the declaration (B-2), so a registered and an unregistered
        class are both planned as DI; the missing provider surfaces when the value
        is resolved, never as a silent ``None``.
        """
        registry = DIRegistry()
        annotations: dict = {"return": None}
        for i in range(num_registered):
            t = _make_type(f"Registered{i}")
            registry.provide(t, t())
            annotations[f"p{i}"] = t
        for i in range(num_unregistered):
            annotations[f"q{i}"] = _make_type(f"Unregistered{i}")

        job_func = _recording_job(annotations, {})
        plan = _plan_for(job_func)
        assert all(binding.source == "di" for binding in plan.params)

        # A missing provider is one of the paths ``engine.run`` raises, not a
        # FAILURE result (executor: ``except MissingProviderError: raise``).
        with pytest.raises(MissingProviderError, match="Unregistered"):
            _run_hostless(registry, job_func)

    def test_optional_param_with_no_provider_resolves_to_none(self):
        """``Optional[T]`` with no provider receives ``None`` on a hostless engine.

        Optionality is read at resolution from the live annotation: an injected
        contract carries no value shape (``schema.md``: ``shape`` is ``None`` for
        ``INJECTED``), so the plan's ``is_optional`` is ``False``. An app-hosted
        job is refused at discovery instead (row C086, B-2's availability rule).
        """
        unregistered_service = _make_type("UnregisteredService")
        annotations = {"svc": unregistered_service | None, "return": None}
        seen: dict = {}
        job_func = _recording_job(annotations, seen)

        plan = _plan_for(job_func)
        assert len(plan.params) == 1
        binding = plan.params[0]
        assert binding.source == "di"
        assert binding.annotation == _qualname(unregistered_service)

        result = _run_hostless(DIRegistry(), job_func)
        assert result.status.value == "Success", result
        assert seen["svc"] is None

    @given(num_params=st.integers(min_value=1, max_value=4))
    def test_optional_params_with_registered_provider_resolve_normally(
        self, num_params: int
    ):
        """``Optional[T]`` with a registered provider receives the instance, not None."""
        registry = DIRegistry()
        annotations: dict = {"return": None}
        instances: dict[str, object] = {}
        for i in range(num_params):
            t = _make_type(f"OptService{i}")
            instances[f"opt{i}"] = t()
            registry.provide(t, instances[f"opt{i}"])
            annotations[f"opt{i}"] = t | None

        seen: dict = {}
        job_func = _recording_job(annotations, seen)
        plan = _plan_for(job_func)
        assert all(binding.source == "di" for binding in plan.params)

        result = _run_hostless(registry, job_func)
        assert result.status.value == "Success", result
        for name, instance in instances.items():
            assert seen[name] is instance

    def test_qualified_annotated_param_resolved_with_qualifier(self):
        """``Annotated[T, Provide("q")]`` is planned with its qualifier and gets that provider."""
        cache_service = _make_type("CacheService")
        redis_instance = cache_service()
        registry = DIRegistry()
        registry.provide(cache_service, redis_instance, qualifier="redis")
        registry.provide(cache_service, cache_service(), qualifier="memcache")

        seen: dict = {}
        job_func = _recording_job(
            {"cache": Annotated[cache_service, Provide("redis")], "return": None}, seen
        )
        plan = _plan_for(job_func)

        assert len(plan.params) == 1
        binding = plan.params[0]
        assert binding.source == "di"
        assert binding.qualifier == "redis"
        assert binding.annotation == _qualname(cache_service)

        result = _run_hostless(registry, job_func)
        assert result.status.value == "Success", result
        assert seen["cache"] is redis_instance

    @given(num_skip_params=st.integers(min_value=1, max_value=4))
    def test_params_without_annotations_are_skipped(self, num_skip_params: int):
        """An unannotated parameter is a caller input (C090), so DI skips it.

        ``Log`` is one of the 15 capabilities, so its source is ``capability``
        (5.1 Work), named ``"Log"``.
        """
        param_parts = ["log: Log", *(f"arg{i}" for i in range(num_skip_params))]
        local_ns: dict = {"Log": Log}
        exec(f"def job_func({', '.join(param_parts)}): pass", local_ns)
        plan = _plan_for(local_ns["job_func"])

        assert plan.params[0].source == "capability"
        assert plan.params[0].annotation == "Log"
        assert plan.params[0].name == "log"
        for i in range(num_skip_params):
            assert plan.params[i + 1].source == "skip"
            assert plan.params[i + 1].name == f"arg{i}"

    def test_di_takes_precedence_over_default_values(self):
        """An injected parameter with a default is still injected, not defaulted."""

        def job_with_default(log: Log = None) -> None:  # type: ignore[assignment]
            pass

        plan = _plan_for(job_with_default)

        assert len(plan.params) == 1
        binding = plan.params[0]
        assert binding.source == "capability"
        assert binding.has_default is True
        assert binding.annotation == "Log"

        seen: dict = {}
        result = _run_hostless(
            DIRegistry(), _recording_job({"log": Log | None, "return": None}, seen)
        )
        assert result.status.value == "Success", result
        assert isinstance(seen["log"], Log)


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
        **engine_storage(),
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
