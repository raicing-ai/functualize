"""PROPOSED — the two click-parameter builders must agree.

**Not wired into the suite.** Drop into `tests/adapters/` to adopt.

`tests/adapters/test_click_params_parity.py` freezes `build_click_params`
against typer's historical output. Nothing compares the two builders that are
both live *today*:

* `_config_option_params` — cold path, from the live pydantic model;
* `build_click_params_from_fields` — warm path, from the cached
  `FieldDescriptor`s.

They disagree on `default` for every field with a non-`None` default, and on
the *parameter class* for a required field. See
`pipeline-readiness/idiomatic-audit/repro/repro_01_warm_config_default.py`.

This is the unit-level counterpart of the discipline
`contributor/reference/pitfalls.md` #6 demands and that
`app/adapters/surface_gate.py` already applies to one attribute: if two paths
must not drift, assert that they do not.

Expected today: both tests FAIL.
"""

from __future__ import annotations

from enum import StrEnum

import pytest
from pydantic import BaseModel, Field

from functualize._discovery.schema_extractor import extract_field_descriptors
from functualize.app.adapters.click_params import (
    _config_option_params,
    build_click_params_from_fields,
)


class Mode(StrEnum):
    FAST = "fast"
    THOROUGH = "thorough"


class WideConfig(BaseModel):
    """One field per shape the two builders route differently."""

    required_str: str
    defaulted_str: str = Field(default="DEFAULT")
    defaulted_int: int = 3
    flag_false: bool = False
    flag_true: bool = True
    optional_none: str | None = None
    factory_list: list[str] = Field(default_factory=list)
    enum_field: Mode = Mode.FAST


def _by_name(params: list) -> dict[str, object]:
    return {p.name: p for p in params}


def _cold() -> dict[str, object]:
    return _by_name(_config_option_params(WideConfig))


def _warm() -> dict[str, object]:
    return _by_name(
        build_click_params_from_fields(extract_field_descriptors(WideConfig))
    )


FIELDS = sorted(WideConfig.model_fields)


@pytest.mark.parametrize("field", FIELDS)
def test_the_two_builders_agree_on_the_default(field: str) -> None:
    """A default supplied by the CLI layer outranks the config file.

    The cold builder passes `default=None` precisely so the resolution ladder
    stays reachable; the warm builder must not smuggle the model's default in
    as though the user had typed it.
    """
    cold, warm = _cold().get(field), _warm().get(field)
    assert cold is not None and warm is not None, f"{field} missing from a builder"
    assert getattr(warm, "default", None) == getattr(cold, "default", None), (
        f"{field}: cold default={getattr(cold, 'default', None)!r} "
        f"warm default={getattr(warm, 'default', None)!r} — the warm value "
        f"reaches call_kwargs and outranks every config source"
    )


@pytest.mark.parametrize("field", FIELDS)
def test_the_two_builders_agree_on_the_parameter_shape(field: str) -> None:
    """A field must not be an Option on one boot and a positional on the next."""
    cold, warm = _cold().get(field), _warm().get(field)
    assert cold is not None and warm is not None, f"{field} missing from a builder"
    assert type(warm).__name__ == type(cold).__name__, (
        f"{field}: cold is {type(cold).__name__}, warm is {type(warm).__name__}"
    )
    assert warm.required == cold.required, (
        f"{field}: cold required={cold.required}, warm required={warm.required}"
    )
