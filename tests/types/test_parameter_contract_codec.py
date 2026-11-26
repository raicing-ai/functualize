"""The cached field record carries the same contract as a cold descriptor.

The records here are cache-shaped: the type travels in the contract, and the
codec stores no type string (9.1), so none is constructed.
"""

from __future__ import annotations

import json

import pytest

from functualize._types.descriptors import (
    FieldDescriptor,
    JobDescriptor,
    _field_from_dict,
    _field_to_dict,
)
from functualize._types.parameter_contract import (
    CliSpelling,
    Container,
    Injection,
    ParameterContract,
    Scalar,
    ValueShape,
    Verdict,
)


@pytest.mark.parametrize("verdict", list(Verdict))
def test_contract_survives_json_cache_round_trip(verdict: Verdict) -> None:
    shape = ValueShape(
        Scalar.ENUM,
        container=Container.FIXED_TUPLE,
        optional=True,
        enum_values=("red", "blue"),
        elements=(ValueShape(Scalar.STR), ValueShape(Scalar.INT)),
    )
    contract = ParameterContract(
        name="colour",
        verdict=verdict,
        shape=shape,
        required=False,
        default_json={"values": ["red", 2]},
        cli=CliSpelling(
            long="--colour",
            short="-c",
            negative="--no-colour",
            positional=False,
            repeatable=True,
            hidden=True,
            envvar="COLOUR",
        ),
        json_schema={"type": "array", "items": [{"type": "string"}]},
        injection=Injection(capability="Log", qualifier="main", from_job="source"),
        reject_reason="Not supported. Use a value type.",
        display="tuple[str, int]",
        description="The colour",
    )
    field = FieldDescriptor(
        name="colour",
        default=None,
        description="The colour",
        required=False,
        contract=contract,
    )

    encoded = json.loads(json.dumps(_field_to_dict(field)))
    assert encoded["contract"]["default_json"] == {"values": ["red", 2]}
    assert _field_from_dict(encoded) == field


def test_missing_contract_key_decodes_as_none() -> None:
    field = FieldDescriptor(name="name", default=None, description="", required=True)
    encoded = _field_to_dict(field)
    del encoded["contract"]
    assert _field_from_dict(encoded) == field


def test_injected_contract_without_shape_or_cli_round_trips() -> None:
    contract = ParameterContract("log", Verdict.INJECTED, None, False, None, None, None)
    field = FieldDescriptor(
        name="log",
        default=None,
        description="",
        required=False,
        contract=contract,
    )
    assert _field_from_dict(json.loads(json.dumps(_field_to_dict(field)))) == field


def test_job_descriptor_cache_path_preserves_contract() -> None:
    contract = ParameterContract(
        "name",
        Verdict.ACCEPTED_FLAG,
        ValueShape(Scalar.STR),
        False,
        "default",
        CliSpelling("--name"),
        {"type": "string"},
    )
    field = FieldDescriptor(
        name="name",
        default="default",
        description="",
        required=False,
        contract=contract,
    )
    descriptor = JobDescriptor(name="run", group=None, parameters=[field])

    warm = JobDescriptor.from_dict(json.loads(json.dumps(descriptor.to_dict())))

    assert warm.parameters == [field]
    assert warm.config_fields == [field]
