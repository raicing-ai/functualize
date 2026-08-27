"""The cached descriptor must agree with the live model.

The TUI resolves nothing about a field's *declaration*. It reads `secret`,
`required` and `default` from the cached `FieldDescriptor`, because
`build_command_panels` runs while the user types and importing a job module on
every keystroke would forfeit true-lazy boot (warm boot: zero imports). That is
deliberate — see ADR-008, Addendum A1.

It leaves one risk, and it is not the one the review first named. The risk is
not a second resolver drifting from the first: both readers bottom out in the
same `ResolutionChain`. The risk is the *cache* drifting from the *model*. If
it does, the TUI masks the wrong field and nothing notices, because every TUI
test would still be internally consistent with the cache it was given.

This module is the join. It asserts that what the cache carries is what the
live model says — for every declaration property a surface acts on.
"""

from __future__ import annotations

from enum import StrEnum

import pytest
from pydantic import BaseModel, Field

from functualize._config.chain import ResolutionChain
from functualize._config.job_config import JobConfigView
from functualize._config.resolved_field import resolve_job_fields
from functualize._config.sources import DefaultSource, EnvSource
from functualize._discovery.schema_extractor import extract_field_descriptors
from functualize._types.descriptors import _field_from_dict, _field_to_dict
from functualize.types import Secret  # noqa: TC001


class Mode(StrEnum):
    FAST = "fast"
    THOROUGH = "thorough"


class WideConfig(BaseModel):
    """Every declaration shape a surface has to render differently."""

    required_plain: str = Field(description="required, no default")
    required_secret: Secret[str] = Field(description="required credential")
    optional_secret: str = Field(
        default="", description="optional", json_schema_extra={"secret": True}
    )
    defaulted: str = Field(default="a-default")
    sort_key: str = Field(default="created_at")
    count: int = Field(default=10)
    flag: bool = Field(default=False)
    mode: Mode = Field(default=Mode.FAST)
    targets: list[str] = Field(default_factory=lambda: ["one"])


def _cached() -> dict[str, object]:
    """Descriptors as the TUI sees them: extracted, then through the cache."""
    return {
        fd.name: _field_from_dict(_field_to_dict(fd))
        for fd in extract_field_descriptors(WideConfig)
    }


def _resolved() -> dict[str, object]:
    """The same fields as the CLI seam derives them from the live model."""
    chain = ResolutionChain([EnvSource(), DefaultSource({})])
    view = JobConfigView(resolution_chain=chain, default_section_prefix="wide")
    return {f.name: f for f in resolve_job_fields(WideConfig, "wide", view)}


FIELD_NAMES = sorted(WideConfig.model_fields)


class TestTheCacheAndTheModelAgree:
    def test_every_field_is_present_in_both(self):
        assert sorted(_cached()) == FIELD_NAMES
        assert sorted(_resolved()) == FIELD_NAMES

    @pytest.mark.parametrize("name", FIELD_NAMES)
    def test_secretness_agrees(self, name):
        """The property the TUI masks on."""
        assert _cached()[name].secret is _resolved()[name].secret, (
            f"the cached descriptor and the live model disagree about whether "
            f"{name!r} is a secret — the TUI masks from the cache"
        )

    @pytest.mark.parametrize("name", FIELD_NAMES)
    def test_requiredness_agrees(self, name):
        """The property both surfaces render as `not set (required)`."""
        assert _cached()[name].required is _resolved()[name].required


class TestTheDeclarationsAreWhatTheyClaim:
    """Anchors, so a change to the extractor is a deliberate edit here."""

    def test_the_two_secret_markers_both_arrive(self):
        cached = _cached()
        assert cached["required_secret"].secret is True, "Secret[str] lost its marker"
        assert cached["optional_secret"].secret is True, "json_schema_extra lost"

    def test_a_secretish_name_is_not_a_secret(self):
        assert _cached()["sort_key"].secret is False

    def test_a_required_field_reads_as_required_on_both_sides(self):
        assert _cached()["required_plain"].required is True
        assert _resolved()["required_plain"].is_missing_required is True

    def test_a_secret_default_is_never_written_to_the_cache(self):
        """The cache is a file on disk; a credential must not reach it.

        `optional_secret` defaults to `""`, so this is asserted on the shape
        rather than the value: `_serialize_default` drops a secret's default
        outright, whatever it holds.
        """

        class WithSecretDefault(BaseModel):
            credential: str = Field(
                default="dev-key-in-the-default",
                json_schema_extra={"secret": True},
            )

        serialized = [
            _field_to_dict(fd) for fd in extract_field_descriptors(WithSecretDefault)
        ]
        assert serialized[0]["default"] is None
        assert "dev-key-in-the-default" not in repr(serialized)
