"""The Click boundary renders the decisions made at discovery."""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Annotated

import click
from click.testing import CliRunner
from pydantic import BaseModel, Field

from functualize._primitives.parameter_contract import (
    build_contracts,
    build_field_contract,
)
from functualize._types.descriptors import FieldDescriptor
from functualize.app.adapters.click_params import (
    build_click_params,
    build_click_params_from_fields,
    render_click_params,
)
from functualize.job.markers import Option


class Color(Enum):
    RED = "red"
    BLUE = "blue"


def _by_name(params: list[click.Parameter]) -> dict[str, click.Parameter]:
    return {param.name: param for param in params if param.name is not None}


def test_required_marked_option_has_no_null_default() -> None:
    def run(p: Annotated[str, Option("-p")]) -> None:
        pass

    param = _by_name(render_click_params(build_contracts(run)))["p"]
    assert isinstance(param, click.Option)
    assert param.required
    assert param.default is not None
    command = click.Command("run", params=[param], callback=lambda **_: None)
    result = CliRunner().invoke(command, [])
    assert result.exit_code == 2
    assert "Missing option '--p'" in result.output


def test_iso_duration_and_typed_default() -> None:
    def run(p: dt.timedelta = dt.timedelta(minutes=5)) -> None:
        pass

    seen: list[dt.timedelta] = []
    params, _, _ = build_click_params(run, None)
    command = click.Command("run", params=params, callback=lambda p: seen.append(p))
    runner = CliRunner()
    assert runner.invoke(command, ["--p", "PT1H"]).exit_code == 0
    assert runner.invoke(command, []).exit_code == 0
    assert seen == [dt.timedelta(hours=1), dt.timedelta(minutes=5)]
    assert all(isinstance(value, dt.timedelta) for value in seen)
    invalid = runner.invoke(command, ["--p", "1:00:00"])
    assert invalid.exit_code == 2
    assert "ISO-8601 duration" in invalid.output


def test_list_and_variadic_tuple_are_repeatable_options() -> None:
    def run(items: list[str] = [], pairs: tuple[str, ...] = ()) -> None:  # noqa: B006
        pass

    params = _by_name(render_click_params(build_contracts(run)))
    assert isinstance(params["items"], click.Option)
    assert isinstance(params["pairs"], click.Option)
    assert params["items"].multiple and params["pairs"].multiple
    seen: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    command = click.Command(
        "run",
        params=list(params.values()),
        callback=lambda items, pairs: seen.append((items, pairs)),
    )
    result = CliRunner().invoke(
        command, ["--items", "a", "--items", "b", "--pairs", "x", "--pairs", "y"]
    )
    assert result.exit_code == 0, result.output
    assert seen == [(("a", "b"), ("x", "y"))]


def test_cached_fields_and_live_contracts_share_rendered_spellings() -> None:
    def run(verbose: bool = False, items: list[str] = []) -> None:  # noqa: B006
        pass

    contracts = build_contracts(run)
    fields = [
        FieldDescriptor(
            name=contract.name,
            type_annotation=contract.display,
            default=contract.default_json,
            description=contract.description,
            required=contract.required,
            contract=contract,
        )
        for contract in contracts
    ]
    cold = _by_name(render_click_params(contracts))
    warm = _by_name(build_click_params_from_fields(fields))
    assert cold.keys() == warm.keys()
    for name in cold:
        assert type(cold[name]) is type(warm[name])
        assert cold[name].opts == warm[name].opts
        assert cold[name].secondary_opts == warm[name].secondary_opts
        assert cold[name].multiple == warm[name].multiple


def test_live_enum_bridge_keeps_member_until_the_binding_door() -> None:
    def run(color: Color) -> None:
        pass

    # A contract can offer the spelling, while only a live function supplies
    # the class that makes the existing command callback receive the member.
    params, _, _ = build_click_params(run, None)
    seen: list[object] = []
    command = click.Command(
        "run", params=params, callback=lambda color: seen.append(color)
    )
    result = CliRunner().invoke(command, ["red"])
    assert result.exit_code == 0, result.output
    second = CliRunner().invoke(command, ["blue"])
    assert second.exit_code == 0, second.output
    assert seen == [Color.RED, Color.BLUE]


def test_group_config_field_remains_an_option_without_a_click_default() -> None:
    class Options(BaseModel):
        target: str = Field(default="staging", description="deployment target")

    info = Options.model_fields["target"]
    contract = build_field_contract("target", info, group=True)
    field = FieldDescriptor(
        name="target",
        type_annotation="str",
        default="staging",
        description=contract.description,
        required=False,
        from_config_model=True,
        contract=contract,
    )
    param = _by_name(build_click_params_from_fields([field]))["target"]
    assert isinstance(param, click.Option)
    assert param.default is None
    assert "--target" in param.opts
