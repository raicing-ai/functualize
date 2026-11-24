"""The execution door binds declared caller values before running a job."""

from __future__ import annotations

import gc
import sys
import weakref
from collections.abc import Generator
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Annotated
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from pydantic import BaseModel
from tests._support.engine_storage import engine_storage
from tests._support.parameter_matrix import ROWS, module_source

from functualize._app.state import AppState
from functualize._engine.context import ExecutionContext
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.resolution import build_resolution_plan
from functualize._primitives.argument_binding import ArgumentBinder, BindRefusal
from functualize._primitives.di import DIRegistry
from functualize._primitives.parameter_contract import build_contracts
from functualize._types.enums import RunStatus
from functualize._types.parameter_contract import Verdict
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp
from functualize.types import RunRequest
from functualize.workflow import FromStep


class Service:
    """Unmarked injected class with a module-level resolvable annotation."""


class Color(Enum):
    RED = "red"
    GREEN = "green"


class Config(BaseModel):
    city: str = "Tokyo"


PAINT_SEEN: list[Color] = []


def paint(color: Color) -> None:
    PAINT_SEEN.append(color)


def step_job(planned: Annotated[str, FromStep("plan")]) -> str:
    return planned


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture(scope="module", autouse=True)
def _matrix_provider_module() -> Generator[None]:
    module = ModuleType("provlib")
    module.ProvWidget = type("ProvWidget", (), {"__module__": "provlib"})
    previous = sys.modules.get("provlib")
    sys.modules["provlib"] = module
    yield
    if previous is None:
        sys.modules.pop("provlib", None)
    else:
        sys.modules["provlib"] = previous


def _run(app: FunctualizeApp, name: str, **kwargs: object):
    return app.execution_engine.run(
        RunRequest(job_name=name, surface="app.execute", kwargs=kwargs)
    )


def test_dynamic_job_is_admitted_and_converts_supplied_values() -> None:
    app = FunctualizeApp(name="door-test")

    def job(count: int = 1) -> int:
        return count

    app.register_dynamic_job("job", job)
    contracts = app.admitted_contracts("job")
    assert contracts is not None
    assert set(contracts) == {"count"}
    result = _run(app, "job", count="5")
    assert result.status is RunStatus.SUCCESS
    assert result.return_value == 5
    assert type(result.return_value) is int


def test_discovered_cold_and_warm_jobs_are_admitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "count.py").write_text("def count(value: int = 1) -> int: return value\n")
    monkeypatch.chdir(tmp_path)
    for _ in range(2):
        app = FunctualizeApp(
            name="door-test", job_sources=JobSources(directories=["jobs"])
        )
        contracts = app.admitted_contracts("count")
        assert contracts is not None
        assert set(contracts) == {"value"}
        assert _run(app, "count", value="5").return_value == 5


def test_missing_provider_is_reported_once_and_refused_at_the_door() -> None:
    app = FunctualizeApp(name="door-test")

    def job(service: Service) -> None:
        pass

    app.register_dynamic_job("job", job)
    reports = [
        failure
        for failure in app._unsatisfiable_jobs
        if failure.error_type == "UnsupportedParameter" and "service" in failure.message
    ]
    assert len(reports) == 1
    assert "Register one" in reports[0].message
    assert _run(app, "job").status is RunStatus.INVALID
    assert _run(app, "job").status is RunStatus.INVALID
    assert (
        len([failure for failure in app._unsatisfiable_jobs if failure in reports]) == 1
    )


def test_config_field_is_resolved_outside_the_binder() -> None:
    app = FunctualizeApp(name="door-test")

    def job(config: Config) -> str:
        return config.city

    app.register_dynamic_job("job", job, config_class=Config)
    result = _run(app, "job", city="Kyoto")
    assert result.status is RunStatus.SUCCESS
    assert result.return_value == "Kyoto"


def test_descriptor_only_lazy_command_delivers_an_enum_member() -> None:
    from functualize.app.adapters.lazy_command import make_lazy_command

    PAINT_SEEN.clear()
    app = FunctualizeApp(name="door-test")
    app.register_dynamic_job("paint", paint)
    descriptor = app.job_registry.get_descriptor("paint")
    command = make_lazy_command(descriptor, app, surface="app.cli")
    outcome = CliRunner().invoke(command, ["red"])
    assert outcome.exit_code == 0, outcome.output
    assert PAINT_SEEN == [Color.RED]


@pytest.mark.parametrize("name", ["plain", "workflow"])
def test_unknown_keyword_is_invalid_before_body(name: str) -> None:
    app = FunctualizeApp(name="door-test")
    called: list[bool] = []

    def job(version: str = "1") -> str:
        called.append(True)
        return version

    if name == "workflow":
        from functualize.workflow import END, Edge, Step, workflow

        app.register_dynamic_job("work", lambda: called.append(True))
        job = workflow(steps=[Step("work")], edges=[Edge("work", END)])(job)
    app.register_dynamic_job(name, job)
    result = _run(app, name, zzz=1)
    assert result.status is RunStatus.INVALID
    assert "zzz" in str(result.exception)
    assert called == []


def test_var_keyword_does_not_swallow_undeclared_input() -> None:
    app = FunctualizeApp(name="door-test")

    def job(version: str = "1", **kwargs: object) -> str:
        return version

    app.register_dynamic_job("job", job)
    result = _run(app, "job", zzz=1)
    assert result.status is RunStatus.INVALID
    assert "Unknown argument 'zzz'" in str(result.exception)


def test_unannotated_parameter_is_text_even_for_an_in_process_call() -> None:
    app = FunctualizeApp(name="door-test")

    def job(value="default") -> str:
        return value

    app.register_dynamic_job("job", job)
    refused = _run(app, "job", value=1)
    assert refused.status is RunStatus.INVALID
    assert "value" in str(refused.exception)
    accepted = _run(app, "job", value="1")
    assert accepted.status is RunStatus.SUCCESS
    assert accepted.return_value == "1"
    assert type(accepted.return_value) is str


def test_absent_repeatable_option_uses_its_declared_default() -> None:
    import click

    from functualize.app.adapters.click_params import render_click_params

    def job(items: list[str] | None = None, other: list[str] = []) -> None:  # noqa: B006
        pass

    contracts = build_contracts(job)
    received: list[dict[str, object]] = []
    command = click.Command(
        "job",
        params=render_click_params(contracts),
        callback=lambda **kw: received.append(kw),
    )
    runner = CliRunner()
    assert runner.invoke(command, []).exit_code == 0
    assert received == [{}]
    bound = ArgumentBinder().bind(job, contracts, received[0], surface="app.cli")
    assert bound == {"items": None, "other": []}
    assert runner.invoke(command, ["--items", "a", "--other", "b"]).exit_code == 0
    assert received[1] == {"items": ("a",), "other": ("b",)}


def test_caller_cannot_supply_a_from_step_value() -> None:
    app = FunctualizeApp(name="door-test")
    app.register_dynamic_job("step-job", step_job)
    assert app.admitted_contracts("step-job") == {}
    result = _run(app, "step-job", planned="caller")
    assert result.status is RunStatus.INVALID
    assert "Unknown argument 'planned'" in str(result.exception)


def test_a_value_for_an_injected_parameter_is_refused() -> None:
    def job(service: Service) -> None:
        pass

    contracts = build_contracts(job)
    with pytest.raises(BindRefusal, match="framework"):
        ArgumentBinder().bind(
            job, contracts, {"service": Service()}, surface="app.execute"
        )


@pytest.mark.parametrize("pep563", [False, True])
def test_field_constraint_is_invalid_before_body(pep563: bool) -> None:
    app = FunctualizeApp(name="door-test")
    module = ModuleType("door_field_constraint")
    source = "from __future__ import annotations\n" if pep563 else ""
    source += (
        "from typing import Annotated\n"
        "from pydantic import Field\n"
        "CALLED = []\n"
        "def job(count: Annotated[int, Field(ge=1)] = 1) -> int:\n"
        "    CALLED.append(True)\n"
        "    return count\n"
    )
    exec(source, module.__dict__)
    app.register_dynamic_job("job", module.job)
    result = _run(app, "job", count=0)
    assert result.status is RunStatus.INVALID
    assert module.CALLED == []


def test_binding_is_idempotent_for_caller_values() -> None:
    def job(count: int = 1, label: str = "a") -> tuple[int, str]:
        return count, label

    contracts = build_contracts(job)
    binder = ArgumentBinder()
    first = binder.bind(job, contracts, {"count": "5"}, surface="app.execute")
    second = binder.bind(job, contracts, first, surface="app.execute")
    assert first == second == {"count": 5, "label": "a"}


def test_plan_sources_are_the_contracts_injection_sources() -> None:
    def job(service: Service, count: int = 1) -> None:
        pass

    contracts = build_contracts(job)
    plan = build_resolution_plan(contracts)
    by_name = {binding.name: binding for binding in plan.params}
    for contract in contracts:
        binding = by_name[contract.name]
        if contract.verdict is Verdict.INJECTED:
            assert binding.source == "di"
            assert binding.annotation == contract.injection.provider_type
        else:
            assert binding.source == "skip"


@pytest.mark.parametrize("future", [False, True], ids=["live", "pep563"])
@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["id"])
def test_matrix_resolution_source_follows_each_injection(
    row: dict, future: bool
) -> None:
    if row["id"] == "E142" and not future:
        pytest.skip("FromJob[...] raises at import in the live declaration")
    module = ModuleType(f"door_matrix_{row['id'].lower()}_{int(future)}")
    sys.modules[module.__name__] = module
    try:
        source = module_source(row, future_annotations=future)
        exec(
            compile(source, module.__name__, "exec", dont_inherit=True), module.__dict__
        )
        rid = row["id"].lower()
        if row["declaration"].startswith("CLASS:"):
            function = getattr(module.__dict__[f"K_{rid}"], row["path"][-1])
        else:
            function = module.__dict__[row["path"][-1]]
        contracts = build_contracts(function)
        plan = build_resolution_plan(contracts)
        assert [binding.name for binding in plan.params] == [
            contract.name for contract in contracts
        ]
        for contract, binding in zip(contracts, plan.params, strict=True):
            injection = contract.injection
            if contract.verdict is not Verdict.INJECTED or injection is None:
                expected = "skip"
            elif injection.from_job is not None:
                expected = "from_job"
            elif injection.capability == "RunContext":
                expected = "runcontext"
            elif injection.capability is not None:
                expected = "capability"
            elif injection.provider_type is not None:
                expected = "di"
            else:
                expected = "skip"
            assert binding.source == expected, row["id"]
    finally:
        sys.modules.pop(module.__name__, None)


def test_a_str_provider_does_not_turn_middleware_text_into_di() -> None:
    from functualize._engine.middleware import _resolve_middleware_kwargs

    def middleware(value: str) -> Generator[None]:
        yield

    registry = DIRegistry()
    registry.provide(str, "provider")
    context = ExecutionContext(
        job_name="job", function=lambda: None, call_kwargs={}, capabilities={}
    )
    cache = weakref.WeakKeyDictionary()
    assert (
        _resolve_middleware_kwargs(
            middleware,
            context=context,
            di_registry=registry,
            resolution_plan_cache=cache,
        )
        is None
    )
    assert cache[middleware].params[0].source == "skip"


def test_unresolvable_bare_capability_name_still_injects() -> None:
    module = ModuleType("door_bare_capability")
    exec(
        "from __future__ import annotations\n"
        "def job(log: Log) -> str:\n"
        "    return type(log).__name__\n",
        module.__dict__,
    )
    contracts = build_contracts(module.job)
    assert contracts[0].verdict is Verdict.INJECTED
    assert contracts[0].injection.capability == "Log"

    app = FunctualizeApp(name="door-test")
    app.register_dynamic_job("job", module.job)
    result = _run(app, "job")
    assert result.status is RunStatus.SUCCESS
    assert result.return_value == "Log"


@pytest.mark.parametrize("annotation", ["Optional[Log]", "Annotated[Log, object()]"])
def test_unresolvable_wrapped_capability_stays_refused(annotation: str) -> None:
    module = ModuleType("door_wrapped_capability")
    exec(
        "from __future__ import annotations\n"
        "from typing import Annotated, Optional\n"
        f"def job(log: {annotation}) -> None: pass\n",
        module.__dict__,
    )
    assert build_contracts(module.job)[0].verdict is Verdict.REJECTED_DISCOVERY


def _hostless_engine() -> JobExecutionEngine:
    return JobExecutionEngine(
        di_registry=DIRegistry(),
        event_bus=MagicMock(),
        hook_registry=MagicMock(),
        middleware_chain=MagicMock(),
        **engine_storage(),
    )


def test_an_address_collision_never_reuses_another_functions_contracts() -> None:
    engine = _hostless_engine()

    def first(alpha: int = 1) -> None:
        pass

    # Force the old id-keyed implementation to see one address for both
    # callables. The weak-keyed implementation never consults that address.
    with patch("functualize._engine.executor.id", return_value=42, create=True):
        first_contracts = engine._contracts_for_job("first", first)
        first_plan = engine._get_resolution_plan(first, first_contracts)
    assert [contract.name for contract in first_contracts] == ["alpha"]
    first_ref = weakref.ref(first)
    del first
    gc.collect()
    assert first_ref() is None
    assert not engine._hostless_contract_cache
    assert not engine._resolution_plan_cache

    def second(beta: int = 2) -> None:
        pass

    with patch("functualize._engine.executor.id", return_value=42, create=True):
        second_contracts = engine._contracts_for_job("second", second)
        second_plan = engine._get_resolution_plan(second, second_contracts)
    assert [contract.name for contract in second_contracts] == ["beta"]
    assert second_plan is not first_plan
    assert [binding.name for binding in second_plan.params] == ["beta"]


@pytest.mark.parametrize("hashable", [False, True])
def test_uncacheable_callables_still_build_a_contract_and_plan(hashable: bool) -> None:
    engine = _hostless_engine()

    class Unweakrefable:
        __slots__ = ()

        def __call__(self, value: int = 1) -> int:
            return value

    class Unhashable:
        __hash__ = None  # type: ignore[assignment]

        def __call__(self, value: int = 1) -> int:
            return value

    job = Unweakrefable() if hashable else Unhashable()
    first = engine._contracts_for_job("job", job)
    second = engine._contracts_for_job("job", job)
    assert first == second
    assert engine._get_resolution_plan(job, first) == engine._get_resolution_plan(
        job, second
    )
    assert not engine._hostless_contract_cache
    assert not engine._resolution_plan_cache
