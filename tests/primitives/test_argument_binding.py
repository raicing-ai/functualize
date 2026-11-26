"""``ArgumentBinder.bind``: the one door from raw surface values to job arguments.

Driven by the declaration table: every row a caller supplies is bound with a
value, then without one, in both annotation modes. The refusals (B-26) are
asserted one by one. The binder never sees a DI registry: contracts arrive
already admitted.
"""

from __future__ import annotations

import enum
import inspect
import pathlib
import sys
import types
import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
from tests._support.parameter_matrix import PROVIDERS, ROWS, module_source

from functualize._primitives.argument_binding import ArgumentBinder, BindRefusal
from functualize._primitives.parameter_contract import admit, build_contracts
from functualize._types.parameter_contract import ParameterContract, Verdict

MODES = pytest.mark.parametrize("future", [False, True], ids=["eager", "pep563"])
CALLER = ("ACCEPTED_FLAG", "ACCEPTED_POSITIONAL", "INVOCATION_ONLY")
SIGNATURE_ROWS = [
    row
    for row in ROWS
    if row["axis"] != "config"
    and not row["declaration"].startswith("GROUP:")
    and row["id"] != "E142"  # refused at import without PEP 563; no binding
]
CALLER_ROWS = [row for row in SIGNATURE_ROWS if row["expected_verdict"] in CALLER]
BY_ID = {row["id"]: row for row in ROWS}

#: One raw value per element type, as a surface delivers it: text, or JSON.
SAMPLES: dict[str, Any] = {
    "str": "x",
    "int": "7",
    "float": "1.5",
    "bool": "true",
    "Path": "/tmp/x",
    "UUID": "12345678-1234-5678-1234-567812345678",
    "date": "2026-01-02",
    "datetime": "2026-01-02T03:04:05",
    "time": "01:02:03",
    "timedelta": "PT1H",
    "Decimal": "1.25",
    "Color": "red",
}
EXPECTED_TYPES: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "Path": pathlib.PurePath,
    "UUID": uuid.UUID,
    "date": date,
    "datetime": datetime,
    "time": time,
    "timedelta": timedelta,
    "Decimal": Decimal,
    "Color": enum.Enum,
}
#: INVOCATION_ONLY rows: tuple[str, int], dict[str, str] (twice), set[str].
INVOCATION_VALUES = {
    "C081": (["a", "1"], tuple, ("a", 1)),
    "C082": ({"k": "v"}, dict, {"k": "v"}),
    "C083": ({"k": "v"}, dict, {"k": "v"}),
    "C084": (["a", "b"], set, {"a", "b"}),
}


@pytest.fixture(autouse=True, scope="module")
def _provlib() -> Iterator[None]:
    module = types.ModuleType("provlib")
    module.ProvWidget = type("ProvWidget", (), {"__module__": "provlib"})  # type: ignore[attr-defined]
    previous = sys.modules.get("provlib")
    sys.modules["provlib"] = module
    yield
    if previous is None:
        sys.modules.pop("provlib", None)
    else:
        sys.modules["provlib"] = previous


def _job(row: dict[str, Any], future: bool) -> Any:
    name = f"_bind_{row['id'].lower()}_{int(future)}"
    module = types.ModuleType(name)
    sys.modules[name] = module
    source = module_source(row, future_annotations=future)
    exec(compile(source, f"<{name}>", "exec", dont_inherit=True), module.__dict__)
    if row["declaration"].startswith("CLASS:"):
        return getattr(module.__dict__[f"K_{row['id'].lower()}"], row["path"][-1])
    return module.__dict__[row["path"][-1]]


def _admitted(function: Any) -> list[ParameterContract]:
    provided = _provided(PROVIDERS)
    return [admit(contract, provided) for contract in build_contracts(function)]


def _provided(pairs: frozenset[tuple[str, str | None]]) -> Any:
    return lambda provider_type, qualifier: (provider_type, qualifier) in pairs


def _element_name(row: dict[str, Any]) -> str:
    delivered = row["delivered_type"] or "str"  # unannotated rows are text
    for name in sorted(SAMPLES, key=len, reverse=True):
        if name in delivered:
            return name
    raise AssertionError(f"no sample for {delivered!r}")


def _raw_value(row: dict[str, Any]) -> Any:
    sample = SAMPLES[_element_name(row)]
    delivered = row["delivered_type"] or ""
    if delivered.startswith(("list[", "tuple[")):
        return [sample, sample]
    return sample


def _others_supplied(contracts: list[ParameterContract], probe: str) -> dict[str, Any]:
    """Values for the job's other required caller parameters (G157's ``q``)."""
    return {
        c.name: ["x"]
        for c in contracts
        if c.name != probe and c.required and c.verdict.name in CALLER
    }


@MODES
@pytest.mark.parametrize("row", CALLER_ROWS, ids=lambda row: row["id"])
def test_a_supplied_value_arrives_as_the_declared_type(
    row: dict[str, Any], future: bool
) -> None:
    function = _job(row, future)
    contracts = _admitted(function)
    raw = _others_supplied(contracts, row["probe"])
    if row["id"] in INVOCATION_VALUES:
        value, container, expected = INVOCATION_VALUES[row["id"]]
        raw[row["probe"]] = value
        bound = ArgumentBinder().bind(function, contracts, raw, surface="http")
        assert type(bound[row["probe"]]) is container
        assert bound[row["probe"]] == expected
        return
    raw[row["probe"]] = _raw_value(row)
    bound = ArgumentBinder().bind(function, contracts, raw, surface="mcp.tool")
    value = bound[row["probe"]]
    element = EXPECTED_TYPES[_element_name(row)]
    delivered = row["delivered_type"] or ""
    if delivered.startswith("list["):
        assert type(value) is list and all(isinstance(v, element) for v in value)
    elif delivered.startswith("tuple["):
        assert type(value) is tuple and all(isinstance(v, element) for v in value)
    else:
        assert isinstance(value, element), (value, element)


@MODES
@pytest.mark.parametrize("row", CALLER_ROWS, ids=lambda row: row["id"])
def test_absence_gives_the_declared_default_or_a_refusal(
    row: dict[str, Any], future: bool
) -> None:
    """B-25, B-12, B-14: defaults survive absence; a required one is refused."""
    function = _job(row, future)
    contracts = _admitted(function)
    contract = next(c for c in contracts if c.name == row["probe"])
    raw = _others_supplied(contracts, row["probe"])
    binder = ArgumentBinder()
    if contract.required:
        with pytest.raises(BindRefusal) as refused:
            binder.bind(function, contracts, raw, surface="http")
        assert refused.value.argument == row["probe"]
        return
    bound = binder.bind(function, contracts, raw, surface="http")
    default = inspect.signature(function).parameters[row["probe"]].default
    if default is inspect.Parameter.empty:  # `p: bool`: an off-by-default flag
        default = False
    assert bound[row["probe"]] == default
    assert type(bound[row["probe"]]) is type(default)


@MODES
def test_the_same_input_binds_identically_on_every_surface(future: bool) -> None:
    """B-24: one door, so one answer whatever the surface."""
    function = _job(BY_ID["B058"], future)  # p: list[UUID]
    contracts = _admitted(function)
    raw = {"p": [SAMPLES["UUID"], SAMPLES["UUID"]]}
    results = [
        ArgumentBinder().bind(function, contracts, raw, surface=surface)
        for surface in ("func.job", "tui.inline", "mcp.tool", "http", "lambda")
    ]
    assert all(result == results[0] for result in results)


def test_an_unknown_key_is_refused_naming_it() -> None:
    function = _job(BY_ID["A002"], True)
    with pytest.raises(BindRefusal) as refused:
        ArgumentBinder().bind(function, _admitted(function), {"zzz": 1}, surface="http")
    assert refused.value.argument == "zzz"
    assert refused.value.reason == "Unknown argument 'zzz'. This job accepts: p"


@pytest.mark.parametrize("rid", ["E110", "E140", "H163"])
def test_a_value_for_an_injected_parameter_is_refused(rid: str) -> None:
    """B-26, B-29, B-30: capability, FromJob and provider alike."""
    function = _job(BY_ID[rid], True)
    contracts = _admitted(function)
    assert contracts[0].verdict is Verdict.INJECTED
    with pytest.raises(BindRefusal) as refused:
        ArgumentBinder().bind(function, contracts, {"p": "x"}, surface="mcp.tool")
    assert refused.value.argument == "p"
    assert "supplied by the framework" in refused.value.reason


def test_injected_parameters_are_left_for_di() -> None:
    function = _job(BY_ID["E110"], True)
    assert (
        ArgumentBinder().bind(function, _admitted(function), {}, surface="http") == {}
    )


@pytest.mark.parametrize("rid", ["C089", "C085", "H166"])
def test_a_call_to_a_job_with_a_refused_parameter_is_refused(rid: str) -> None:
    """DC-1 = B: listed, and refused when called, with discovery's reason."""
    function = _job(BY_ID[rid], True)
    with pytest.raises(BindRefusal) as refused:
        ArgumentBinder().bind(function, _admitted(function), {}, surface="http")
    assert refused.value.argument == "p"
    assert "refused at discovery" in refused.value.reason


@pytest.mark.parametrize(
    ("rid", "value"),
    [("A005", "seven"), ("A021", "not-a-uuid"), ("A038", "soon"), ("A045", "green")],
)
def test_a_value_that_does_not_convert_is_refused(rid: str, value: str) -> None:
    function = _job(BY_ID[rid], True)
    with pytest.raises(BindRefusal) as refused:
        ArgumentBinder().bind(
            function, _admitted(function), {"p": value}, surface="http"
        )
    assert refused.value.argument == "p"
    assert repr(value) in refused.value.reason


def test_field_constraints_hold_at_the_door() -> None:
    """``Annotated[int, Field(ge=1)] = 1``: what ``ArgValidator`` did, subsumed."""
    function = _job(BY_ID["D107"], True)
    contracts = _admitted(function)
    binder = ArgumentBinder()
    with pytest.raises(BindRefusal):
        binder.bind(function, contracts, {"p": 0}, surface="http")
    assert binder.bind(function, contracts, {"p": "3"}, surface="http") == {"p": 3}
    assert binder.bind(function, contracts, {}, surface="http") == {"p": 1}


def test_a_required_invocation_only_parameter_names_the_surfaces_on_a_command_line() -> (
    None
):
    """B-15: `func apply` without `patch` is a usage error naming MCP, HTTP, Lambda."""
    function = _job(BY_ID["C082"], True)  # p: dict[str, str]
    contracts = _admitted(function)
    for surface in ("func.job", "tui.inline"):
        with pytest.raises(BindRefusal) as refused:
            ArgumentBinder().bind(function, contracts, {}, surface=surface)
        assert refused.value.reason == (
            "Parameter 'p' can only be supplied over MCP, HTTP or Lambda"
        )
    with pytest.raises(BindRefusal) as refused:
        ArgumentBinder().bind(function, contracts, {}, surface="http")
    assert refused.value.reason == "Missing required argument 'p'"


def test_a_config_field_is_not_a_call_argument() -> None:
    row = BY_ID["F143"]
    name = "_bind_cfg_f143"
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(module_source(row), name, "exec", dont_inherit=True), module.__dict__)
    from functualize._primitives.parameter_contract import build_field_contract

    model = module.__dict__["Cfg_f143"]
    field = build_field_contract("f", model.model_fields["f"])
    function = module.__dict__["f143"]
    with pytest.raises(BindRefusal) as refused:
        ArgumentBinder().bind(function, [field], {"f": "x"}, surface="http")
    assert "config field" in refused.value.reason


def test_adapters_are_built_once_per_binder_and_never_shared() -> None:
    function = _job(BY_ID["A006"], True)
    contracts = _admitted(function)
    first, second = ArgumentBinder(), ArgumentBinder()
    first.bind(function, contracts, {"p": "1"}, surface="http")
    adapter = first._adapters[(function, "p")]
    first.bind(function, contracts, {"p": "2"}, surface="http")
    assert first._adapters[(function, "p")] is adapter
    assert second._adapters == {}
