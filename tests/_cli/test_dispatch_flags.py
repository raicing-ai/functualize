"""Declared setting flags survive preboot parsing with their Setting identity."""

from __future__ import annotations

from typing import TYPE_CHECKING

import functualize.plugin
from functualize._cli import dispatch
from functualize._cli.data import func_settings
from functualize.plugin import AppSettingsSchema, Setting

if TYPE_CHECKING:
    import pytest


def test_declared_flags_are_typed_and_do_not_eat_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = Setting("custom.name", "str", "Name", cli_flag="--custom-name")
    depth = Setting("custom.depth", "int", "Depth", cli_flag="--custom-depth")
    paths = Setting("custom.paths", "list", "Paths", cli_flag="--custom-path")
    monkeypatch.setattr(
        functualize.plugin,
        "FUNCTUALIZE_SETTINGS",
        AppSettingsSchema(settings=(name, depth, paths)),
    )

    argv = [
        "func",
        "--custom-name",
        "alice",
        "--custom-depth=2",
        "--custom-path",
        "one",
        "--custom-path=two",
        "build",
    ]
    parsed, legacy_flags = dispatch._extract_global_options(argv)

    assert dict(parsed.setting_overrides) == {
        name: "alice",
        depth: 2,
        paths: ["one", "two"],
    }
    assert legacy_flags == {}
    assert parsed.first_positional_index == 6
    assert dispatch.detect_mode(argv, job_names={"build"}) == (
        dispatch.Mode.JOB,
        ["build"],
    )


def test_accepted_values_name_is_an_alias_during_migration() -> None:
    from functualize._types.flag_grammar import (
        GLOBAL_OPTION_ACCEPTED_VALUES,
        OPTIONAL_VALUE_VALID_SET,
    )

    assert GLOBAL_OPTION_ACCEPTED_VALUES is OPTIONAL_VALUE_VALID_SET


def test_early_scan_reads_phase_from_the_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    early = Setting(
        "custom.name", "str", "Name", cli_flag="--custom-name", phase="early"
    )
    monkeypatch.setattr(
        functualize.plugin, "FUNCTUALIZE_SETTINGS", AppSettingsSchema(settings=(early,))
    )
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        func_settings,
        "set_preboot_override",
        lambda name, value, *, flag: calls.append((name, value, flag)),
    )

    assert dispatch.scan_early_setting_flags(["--custom-name=alice"]) == 1
    assert calls == [("custom.name", "alice", "--custom-name")]


def test_funcs_own_declared_flags_are_parsed_pre_boot() -> None:
    """No stand-in schema: the pre-boot parse reads `FUNCTUALIZE_SETTINGS`."""
    from functualize.plugin import FUNCTUALIZE_SETTINGS

    depth = FUNCTUALIZE_SETTINGS.setting("discovery.scan_depth")
    assert depth is not None
    parsed, legacy_flags = dispatch._extract_global_options(
        ["func", "--discovery-depth", "3", "build"]
    )
    assert dict(parsed.setting_overrides) == {depth: 3}
    assert legacy_flags == {"scan_depth": 3}
    assert parsed.first_positional_index == 2
