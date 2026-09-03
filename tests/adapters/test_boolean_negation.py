"""Every boolean renders one way, and the collision rule is deterministic.

A boolean that is `true` in a config file could not be turned off from the
command line — the config ladder promises CLI > env > file and for booleans it
was three-quarters true. There were four boolean shapes rendering three
different ways, with no rule a reader could infer.

The shape assertions walk the builder's **own output**. A hand-written table of
expected flags is the thing that stops tracking the builder — the failure mode
recorded in ADR-009 (a stub that kept passing over a shape the panel no longer
produced).
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from functualize._types.naming import negative_flag_for
from functualize.app.adapters.click_params import build_click_params
from functualize.job import Log, Option


class AllShapes(BaseModel):
    """Config-model booleans, with and without a short flag."""

    cfg_bool: bool = Field(default=False, description="plain config bool")
    cfg_bool_short: Annotated[bool, Option("-s")] = Field(
        default=False, description="config bool with a short flag"
    )


def every_shape(
    log: Log,
    config: AllShapes,
    plain_bool: bool = True,
    plain_bool_short: Annotated[bool, Option("-p")] = True,
) -> None:
    """A job carrying all four boolean shapes the spec names."""


def _params(fn, config_class) -> dict:
    out = build_click_params(fn, job_config_class=config_class)
    flat: list = []
    stack = [out]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(item)
        elif hasattr(item, "name"):
            flat.append(item)
    return {p.name: p for p in flat}


class TestEveryBooleanShapeGetsANegativeForm:
    """A3 — one declaration, one CLI shape."""

    @pytest.mark.parametrize(
        "field_name",
        ["cfg_bool", "cfg_bool_short", "plain_bool", "plain_bool_short"],
    )
    def test_the_shape_emits_a_negative(self, field_name: str) -> None:
        params = _params(every_shape, AllShapes)
        param = params[field_name]

        expected = f"--no-{field_name.replace('_', '-')}"
        assert expected in param.secondary_opts, (
            f"{field_name} rendered opts={tuple(param.opts)} "
            f"secondary={tuple(param.secondary_opts)}"
        )

    def test_a_short_flag_does_not_cost_the_negative_form(self) -> None:
        """B3 — the shape that was the odd one out.

        A short flag used to replace the pair rather than sit beside it, so
        declaring `-s` silently removed the ability to turn the field off.
        """
        params = _params(every_shape, AllShapes)

        for name, short in (("cfg_bool_short", "-s"), ("plain_bool_short", "-p")):
            assert short in params[name].opts, f"{name} lost its short flag"
            assert params[name].secondary_opts, f"{name} lost its negative form"

    def test_absence_still_means_absence(self) -> None:
        """A7 — the ladder is untouched.

        A config field's option carries `default=None` so the resolution chain
        can supply the value. A pair declared with the wrong default would
        report `False` for a flag nobody typed, at the highest precedence
        there is.
        """
        params = _params(every_shape, AllShapes)

        assert params["cfg_bool"].default is None
        assert params["cfg_bool_short"].default is None


class TestTheCollisionRuleIsDeterministic:
    """A5 — `no_cache` wins, whichever order the two are declared in.

    Click raises nothing for this and binds by declaration order, so the same
    two fields produce opposite results depending on which was written first.
    Determinism is the guarantee; detection is deliberately not.
    """

    def test_the_rule_itself(self) -> None:
        assert negative_flag_for("cache", {"cache"}) == "--no-cache"
        assert negative_flag_for("cache", {"cache", "no_cache"}) is None
        assert negative_flag_for("no_cache", {"cache", "no_cache"}) == "--no-no-cache"

    @pytest.mark.parametrize("order", ["cache-first", "no_cache-first"])
    def test_declaration_order_does_not_change_the_answer(self, order: str) -> None:
        if order == "cache-first":

            class Cfg(BaseModel):
                cache: bool = Field(default=False)
                no_cache: bool = Field(default=False)
        else:

            class Cfg(BaseModel):  # type: ignore[no-redef]
                no_cache: bool = Field(default=False)
                cache: bool = Field(default=False)

        def target(log: Log, config: Cfg) -> None: ...

        params = _params(target, Cfg)

        assert params["cache"].secondary_opts == [], (
            "`cache` must yield --no-cache to the field literally named no_cache"
        )
        assert "--no-cache" in params["no_cache"].opts, (
            "the literal field must own --no-cache"
        )
