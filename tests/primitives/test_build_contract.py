"""Every row of the declaration table gets its verdict from ``build_contract``.

Two steps, as discovery will run them (spec B-2):

1. ``build_contract`` decides from the declaration alone; no registry exists
   anywhere in this module. Its verdict is the row's ``declared_verdict``.
2. ``admit`` applies the one availability rule against the matrix project's
   exact ``(type, qualifier)`` providers (``PROVIDERS``). Its verdict is the
   row's ``expected_verdict``.

Each row is compiled with and without ``from __future__ import annotations``
and must yield equal contracts (B-6). The one exception is E142: without PEP 563
``FromJob[...]`` raises ``TypeError`` while the module imports, so the refusal
happens before any classifier can see it; with PEP 563 the classifier refuses
it.
"""

from __future__ import annotations

import json
import sys
import types
from typing import TYPE_CHECKING, Any

import pytest
from tests._support.parameter_matrix import PROVIDERS, ROWS, module_source

from functualize._primitives.parameter_contract import (
    REQUIRED,
    admit,
    build_contracts,
    build_field_contract,
)
from functualize._types.parameter_contract import ParameterContract, Verdict

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

MODES = pytest.mark.parametrize("future", [False, True], ids=["eager", "pep563"])
BY_ID = {row["id"]: row for row in ROWS}
VALUE_VERDICTS = {
    Verdict.ACCEPTED_FLAG,
    Verdict.ACCEPTED_POSITIONAL,
    Verdict.CONFIG_FIELD,
    Verdict.INVOCATION_ONLY,
}


def _provided_by(
    pairs: frozenset[tuple[str, str | None]],
) -> Callable[[str, str | None], bool]:
    return lambda provider_type, qualifier: (provider_type, qualifier) in pairs


@pytest.fixture(autouse=True, scope="module")
def _provlib() -> Iterator[None]:
    """The matrix's provider plugin module, for ``from provlib import ProvWidget``."""
    module = types.ModuleType("provlib")
    widget = type("ProvWidget", (), {"__module__": "provlib"})
    module.ProvWidget = widget  # type: ignore[attr-defined]
    previous = sys.modules.get("provlib")
    sys.modules["provlib"] = module
    yield
    if previous is None:
        sys.modules.pop("provlib", None)
    else:
        sys.modules["provlib"] = previous


def _load(row: dict[str, Any], future: bool) -> dict[str, Any]:
    name = f"_pc_row_{row['id'].lower()}"
    module = types.ModuleType(name)
    sys.modules[name] = module  # pydantic and get_type_hints resolve through it
    source = module_source(row, future_annotations=future)
    # dont_inherit: this file's own `from __future__ import annotations` must
    # not leak into the "eager" mode, or both modes would be PEP 563.
    code = compile(source, f"<{name}>", "exec", dont_inherit=True)
    exec(code, module.__dict__)
    return module.__dict__


def _contracts(row: dict[str, Any], future: bool) -> dict[str, ParameterContract]:
    """The contracts of the row's declaration, keyed by parameter or field name."""
    namespace = _load(row, future)
    rid, declaration = row["id"].lower(), row["declaration"]
    if declaration.startswith("GROUP:") or row["axis"] == "config":
        group = declaration.startswith("GROUP:")
        model = namespace[f"G_{rid}" if group else f"Cfg_{rid}"]
        return {
            field: build_field_contract(field, info, group=group)
            for field, info in model.model_fields.items()
        }
    if declaration.startswith("CLASS:"):
        function = getattr(namespace[f"K_{rid}"], row["path"][-1])
    else:
        function = namespace[row["path"][-1]]
    return {contract.name: contract for contract in build_contracts(function)}


def _probe(row: dict[str, Any], future: bool) -> ParameterContract:
    return _contracts(row, future)[row["probe"]]


def _skip_eager_e142(row: dict[str, Any], future: bool) -> None:
    if row["id"] == "E142" and not future:
        with pytest.raises(TypeError, match=r"FromJob\[\.\.\.\] is not a type"):
            _load(row, future)
        pytest.skip("E142 is refused at import without PEP 563 (asserted above)")


@MODES
@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["id"])
def test_declaration_alone_gives_the_declared_verdict(
    row: dict[str, Any], future: bool
) -> None:
    _skip_eager_e142(row, future)
    contract = _probe(row, future)
    assert contract.verdict.name == row["declared_verdict"], contract.reject_reason


@MODES
@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["id"])
def test_admit_against_the_matrix_providers_gives_the_expected_verdict(
    row: dict[str, Any], future: bool
) -> None:
    _skip_eager_e142(row, future)
    admitted = admit(_probe(row, future), _provided_by(PROVIDERS))
    assert admitted.verdict.name == row["expected_verdict"], admitted.reject_reason


@MODES
def test_a_str_provider_turns_h165_injected_and_moves_nothing_else(
    future: bool,
) -> None:
    """F-21 / UC-6: availability is per ``(type, qualifier)``, never per kind."""
    extended = _provided_by(PROVIDERS | {("builtins.str", "s2")})
    baseline = _provided_by(PROVIDERS)
    moved = {}
    for row in ROWS:
        if row["id"] == "E142" and not future:
            continue
        for name, contract in _contracts(row, future).items():
            before = admit(contract, baseline).verdict
            after = admit(contract, extended).verdict
            if before is not after:
                moved[(row["id"], name)] = (before, after)
    assert moved == {
        ("H165", "p"): (Verdict.REJECTED_DISCOVERY, Verdict.INJECTED),
    }


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["id"])
def test_pep563_makes_no_difference(row: dict[str, Any]) -> None:
    if row["id"] == "E142":
        pytest.skip("eager E142 never reaches the classifier (see the module doc)")
    assert _contracts(row, False) == _contracts(row, True)


@MODES
@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["id"])
def test_contract_invariants(row: dict[str, Any], future: bool) -> None:
    """schema.md invariants 2-4, and B-15: shape, schema and spelling agree."""
    _skip_eager_e142(row, future)
    for contract in _contracts(row, future).values():
        valued = contract.verdict in VALUE_VERDICTS
        assert (contract.shape is not None) is valued
        assert (contract.json_schema is not None) is valued
        spellable = valued and contract.verdict is not Verdict.INVOCATION_ONLY
        assert (contract.cli is not None) is spellable
        rejected = contract.verdict is Verdict.REJECTED_DISCOVERY
        assert bool(contract.reject_reason) is rejected
        assert (contract.injection is not None) is (
            contract.verdict is Verdict.INJECTED
        )
        json.dumps(contract.default_json)  # JSON-native: survives cache.json
        assert (contract.default_json == REQUIRED) is contract.required


def test_capability_and_from_job_contracts_ignore_availability() -> None:
    """B-2: only a provider-backed dependency asks ``has_provider``."""
    asked: list[tuple[str, str | None]] = []

    def nothing_registered(provider_type: str, qualifier: str | None) -> bool:
        asked.append((provider_type, qualifier))
        return False

    for rid in ("E108", "E119", "E140", "E141"):
        contract = _probe(BY_ID[rid], True)
        assert admit(contract, nothing_registered) is contract
    assert asked == []


def test_a_qualified_provider_does_not_satisfy_an_unqualified_parameter() -> None:
    """Exact pairs: ``ProvWidget`` under ``"w"`` only leaves ``p: ProvWidget`` bare."""
    only_qualified = _provided_by(frozenset({("provlib.ProvWidget", "w")}))
    unqualified = admit(_probe(BY_ID["H163"], True), only_qualified)
    qualified = admit(_probe(BY_ID["H162"], True), only_qualified)
    assert unqualified.verdict is Verdict.REJECTED_DISCOVERY
    assert "provlib.ProvWidget without a qualifier" in (unqualified.reject_reason or "")
    assert qualified.verdict is Verdict.INJECTED


def test_missing_provider_reason_names_type_qualifier_and_remedy() -> None:
    contract = admit(_probe(BY_ID["H166"], True), _provided_by(PROVIDERS))
    assert contract.reject_reason == (
        "No provider is registered for provlib.ProvWidget with qualifier 'nope'. "
        "Register one from a plugin, or declare a type the caller supplies"
    )


def test_timedelta_is_an_iso_8601_duration() -> None:
    contract = _probe(BY_ID["A038"], True)  # p: timedelta = timedelta(seconds=1)
    assert contract.json_schema == {"type": "string", "format": "duration"}
    assert contract.default_json == "PT1S"


@pytest.mark.parametrize(
    ("rid", "schema"),
    [
        ("A007", {"type": "integer"}),  # Optional[int]: B-20, never "string"
        ("A031", {"type": "string", "format": "date-time"}),
        ("B053", {"type": "array", "items": {"type": "string"}}),
        ("C080", {"type": "array", "items": {"type": "string"}}),
        ("C082", {"type": "object", "additionalProperties": {"type": "string"}}),
        ("A046", {"type": "string", "enum": ["red", "blue"]}),
    ],
)
def test_json_schema_comes_from_the_declared_shape(
    rid: str, schema: dict[str, Any]
) -> None:
    assert _probe(BY_ID[rid], True).json_schema == schema


def test_enum_default_is_published_as_its_value_on_every_path() -> None:
    """F-34: a cold ``Color.RED`` and a warm ``"red"`` must not differ."""
    assert _probe(BY_ID["A046"], True).default_json == "red"


def test_a_secret_default_is_never_encoded() -> None:
    assert _probe(BY_ID["F148"], True).default_json is None
    assert _probe(BY_ID["A050"], True).default_json is None
