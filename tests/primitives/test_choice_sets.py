"""Choice sets keep their declared value type (spec B-3, schema invariant 7).

A choice set is the values of an ``Enum`` or the arguments of a ``Literal``.
All ``str`` or all ``int`` is supported: the schema publishes the typed values,
and the binder accepts each advertised value **and** its ``str()`` token (what a
text surface spells), delivering the declared value. Every other set is
refused at discovery with the remedy.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from functualize._primitives.argument_binding import ArgumentBinder
from functualize._primitives.parameter_contract import build_contracts
from functualize._types.parameter_contract import ParameterContract, Verdict

SOURCE = """
import enum
from typing import Literal


class Level(enum.Enum):
    LOW = 1
    HIGH = 2


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


class Mixed(enum.Enum):
    ONE = 1
    TWO = "two"


def s_str(p: Literal["low", "high"]) -> None: ...
def s_int(p: Literal[1, 2]) -> None: ...
def e_str(p: Color) -> None: ...
def e_int(p: Level) -> None: ...
def l_s_str(p: list[Literal["low", "high"]]) -> None: ...
def l_s_int(p: list[Literal[1, 2]]) -> None: ...
def l_e_str(p: list[Color]) -> None: ...
def l_e_int(p: list[Level]) -> None: ...
def r_mixed(p: Literal["a", 1]) -> None: ...
def r_bool(p: Literal[True]) -> None: ...
def r_float(p: Literal[1.5]) -> None: ...
def r_enum(p: Mixed) -> None: ...
def r_list(p: list[Literal["a", 1]]) -> None: ...
"""

MODES = pytest.mark.parametrize("future", [False, True], ids=["eager", "pep563"])

#: job → (JSON type, advertised values, declared value for each advertised one)
SUPPORTED: dict[str, tuple[str, list[Any]]] = {
    "s_str": ("string", ["low", "high"]),
    "s_int": ("integer", [1, 2]),
    "e_str": ("string", ["red", "blue"]),
    "e_int": ("integer", [1, 2]),
}
REMEDY = "Use an Enum whose values are all str or all int"


def _module(future: bool) -> dict[str, Any]:
    name = f"_choice_sets_{int(future)}"
    module = types.ModuleType(name)
    sys.modules[name] = module
    prefix = "from __future__ import annotations\n" if future else ""
    code = compile(prefix + SOURCE, f"<{name}>", "exec", dont_inherit=True)
    exec(code, module.__dict__)
    return module.__dict__


def _contract(namespace: dict[str, Any], job: str) -> ParameterContract:
    (contract,) = build_contracts(namespace[job])
    return contract


def _declared(namespace: dict[str, Any], job: str, value: Any) -> Any:
    """What the job must receive for an advertised value: the member or the value."""
    if job.endswith("e_str"):
        return namespace["Color"](value)
    if job.endswith("e_int"):
        return namespace["Level"](value)
    return value


@MODES
@pytest.mark.parametrize("job", sorted(SUPPORTED))
def test_the_schema_publishes_typed_values(job: str, future: bool) -> None:
    namespace = _module(future)
    kind, values = SUPPORTED[job]
    scalar = _contract(namespace, job)
    assert scalar.verdict is Verdict.ACCEPTED_POSITIONAL
    assert scalar.json_schema == {"type": kind, "enum": values}
    listed = _contract(namespace, f"l_{job}")
    assert listed.json_schema == {
        "type": "array",
        "items": {"type": kind, "enum": values},
    }
    assert scalar.shape is not None
    assert [type(v).__name__ for v in scalar.shape.enum_values] == [
        "str" if kind == "string" else "int"
    ] * 2


@MODES
@pytest.mark.parametrize("job", sorted(SUPPORTED))
def test_each_advertised_value_and_its_text_token_bind(job: str, future: bool) -> None:
    namespace = _module(future)
    _, values = SUPPORTED[job]
    binder = ArgumentBinder()
    for listed in (False, True):
        name = f"l_{job}" if listed else job
        function, contract = namespace[name], _contract(namespace, name)
        for value in values:
            expected = _declared(namespace, job, value)
            for raw in (value, str(value)):
                supplied = [raw, raw] if listed else raw
                bound = binder.bind(
                    function, [contract], {"p": supplied}, surface="http"
                )
                result = bound["p"]
                if listed:
                    assert result == [expected, expected], (name, raw)
                    assert all(type(item) is type(expected) for item in result)
                else:
                    assert result == expected and type(result) is type(expected), (
                        name,
                        raw,
                    )


@MODES
@pytest.mark.parametrize("job", ["r_mixed", "r_bool", "r_float", "r_enum", "r_list"])
def test_other_sets_are_refused_at_discovery_with_the_remedy(
    job: str, future: bool
) -> None:
    contract = _contract(_module(future), job)
    assert contract.verdict is Verdict.REJECTED_DISCOVERY
    assert contract.json_schema is None and contract.shape is None
    assert contract.reject_reason is not None
    assert "is a choice set whose values are not all str or all int" in (
        contract.reject_reason
    )
    assert contract.reject_reason.endswith(REMEDY)


def test_the_refusal_names_the_declaration() -> None:
    namespace = _module(True)
    assert _contract(namespace, "r_mixed").reject_reason.startswith(  # type: ignore[union-attr]
        "'Literal['a', 1]' is a choice set"
    )
    assert _contract(namespace, "r_enum").reject_reason.startswith(  # type: ignore[union-attr]
        "'Mixed' is a choice set"
    )


def test_a_token_outside_the_set_is_still_refused() -> None:
    from functualize._primitives.argument_binding import BindRefusal

    namespace = _module(True)
    with pytest.raises(BindRefusal):
        ArgumentBinder().bind(
            namespace["s_int"],
            [_contract(namespace, "s_int")],
            {"p": "3"},
            surface="http",
        )
