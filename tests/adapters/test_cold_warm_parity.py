"""The two config-field builders must render one declaration one way.

`_config_field_option` is the single rule for turning a config-model field into
a click parameter, and two builders reach it: `build_click_params` from the live
signature on a cold boot, and `build_click_params_from_fields` from cached
`FieldDescriptor`s on a warm one.

Only the warm caller passed `short_flag`. So `-s` worked on a warm boot and was
unknown on a cold one — the first run of a project behaved differently from
every run after it, which is the cold/warm divergence class that also produced
the group-options defects (`contributor/reference/pitfalls.md`).

The short flag originates in an `Option("-s")` marker in the field's
`Annotated` metadata, which both builders can read.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from functualize.app.adapters.click_params import (
    build_click_params,
    build_click_params_from_fields,
)
from functualize.job import Log, Option


class ShortFlagConfig(BaseModel):
    """A config model whose field declares a short flag."""

    region: Annotated[str, Option("-s")] = Field(
        default="us-east-1", description="Target region"
    )


def target(log: Log, config: ShortFlagConfig) -> None:
    """A job whose only config field carries a short flag."""


def _by_name(params: object) -> dict[str, object]:
    """Flatten whatever the builder returns into {param name: param}."""
    flat: list = []
    stack = [params]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(item)
        elif hasattr(item, "name"):
            flat.append(item)
    return {p.name: p for p in flat}


def _warm_descriptors() -> list:
    """The cached shape the warm builder consumes, with the marker resolved."""
    import dataclasses

    from functualize._discovery.group_options_extractor import (
        extract_field_descriptors,
    )

    resolved = []
    for descriptor in extract_field_descriptors(ShortFlagConfig):
        info = ShortFlagConfig.model_fields.get(descriptor.name)
        short = descriptor.short_flag
        for meta in getattr(info, "metadata", ()) or ():
            if type(meta).__name__ == "Option" and getattr(meta, "short", None):
                short = meta.short
        resolved.append(
            dataclasses.replace(descriptor, short_flag=short, from_config_model=True)
        )
    return resolved


def test_both_builders_render_the_same_opts_for_a_short_flagged_config_field() -> None:
    """A1's precondition: one declaration, one spelling, on both boot paths."""
    cold = _by_name(build_click_params(target, job_config_class=ShortFlagConfig))
    warm = _by_name(build_click_params_from_fields(_warm_descriptors()))

    assert "region" in cold, f"cold builder produced {sorted(cold)}"
    assert "region" in warm, f"warm builder produced {sorted(warm)}"

    assert tuple(cold["region"].opts) == tuple(warm["region"].opts), (  # type: ignore[attr-defined]
        f"cold={tuple(cold['region'].opts)} warm={tuple(warm['region'].opts)}"  # type: ignore[attr-defined]
    )
    assert tuple(cold["region"].secondary_opts) == tuple(  # type: ignore[attr-defined]
        warm["region"].secondary_opts  # type: ignore[attr-defined]
    )


def test_the_short_flag_is_actually_present() -> None:
    """The control.

    Without it, a fix that dropped `-s` from *both* builders would satisfy the
    agreement test perfectly while removing the capability.
    """
    cold = _by_name(build_click_params(target, job_config_class=ShortFlagConfig))

    assert "-s" in cold["region"].opts, (  # type: ignore[attr-defined]
        f"the declared short flag is missing: {tuple(cold['region'].opts)}"  # type: ignore[attr-defined]
    )
