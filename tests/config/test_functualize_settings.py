"""The built-in declaration carries the pinned vocabulary without runtime imports."""

from __future__ import annotations

import pytest

from functualize._types.functualize_settings import (
    DISCOVERY_FINGERPRINT_FIELDS,
    FUNCTUALIZE_SETTINGS,
    LIST_KEYS,
    PROJECT_CONFIG_CANDIDATES,
    SCRIPT_METADATA,
)
from functualize._types.settings import Setting
from tests.config.test_settings_pin import EXPECTED_CATALOG, EXPECTED_FLAGS


def test_declared_names_equal_the_pinned_union() -> None:
    names = [setting.name for setting in FUNCTUALIZE_SETTINGS.settings]
    assert len(names) == len(set(names))
    assert set(names) == {str(row[0]) for row in EXPECTED_CATALOG} | {
        "jobs_directories",
        "plugins_directories",
    }
    assert FUNCTUALIZE_SETTINGS.freeform_sections == {"aliases"}
    # Eleven settings are reachable from a root flag; every one of them is on
    # the pinned root surface. Which eleven, and in what order, is pinned by
    # `test_settings_pin.test_sixteen_root_options` — that test reads the click
    # options the declaration generated, so the two cannot drift.
    declared_flags = [
        setting.cli_flag
        for setting in FUNCTUALIZE_SETTINGS.settings
        if setting.cli_flag
    ]
    assert len(declared_flags) == 11
    assert set(declared_flags) <= {str(row[0]) for row in EXPECTED_FLAGS}
    assert LIST_KEYS == (
        "jobs_directories",
        "import_libs",
        "plugins_directories",
        "extra_directories",
        "exclude_patterns",
    )
    assert PROJECT_CONFIG_CANDIDATES == (
        "pyproject.toml",
        ".functualize.toml",
        ".functualize/.functualize.toml",
    )
    assert DISCOVERY_FINGERPRINT_FIELDS == (
        ("exclude_patterns", ()),
        ("extra_directories", ()),
        ("require_file_prefix", None),
        ("require_file_postfix", None),
        ("require_file_import", None),
        ("require_file_marker", None),
        ("require_job_decorators", None),
        ("require_job_prefix", None),
        ("require_job_postfix", None),
        ("pre_filter", None),
    )
    assert {"job"} == SCRIPT_METADATA


def test_declared_catalog_matches_pinned_types_defaults_and_help() -> None:
    for row in EXPECTED_CATALOG:
        setting = FUNCTUALIZE_SETTINGS.setting(str(row[0]))
        assert setting is not None
        assert (
            setting.type,
            setting.description,
            setting.default,
            setting.choices or (),
            setting.min_value,
            setting.max_value,
            setting.max_items,
        ) == row[1:8]


def test_extend_rejects_existing_and_new_duplicate_names() -> None:
    extension = Setting("sample.enabled", "bool", "Enable sample", default="false")
    extended = FUNCTUALIZE_SETTINGS.extend(extension)
    assert extended.setting(extension.name) == extension
    assert FUNCTUALIZE_SETTINGS.setting(extension.name) is None
    with pytest.raises(ValueError, match="already declared"):
        FUNCTUALIZE_SETTINGS.extend(extension, extension)
    with pytest.raises(ValueError, match="already declared"):
        FUNCTUALIZE_SETTINGS.extend(Setting("cli.output", "str", "clash"))


def test_places_prefer_canonical_discovery_and_accept_legacy_top_level() -> None:
    for name in ("discovery.extra_directories", "discovery.exclude_patterns"):
        setting = FUNCTUALIZE_SETTINGS.setting(name)
        assert setting is not None
        assert setting.places == ("", "discovery")
        assert setting.section == "discovery"
        assert setting.key in FUNCTUALIZE_SETTINGS.keys_in("")
        assert setting.key in FUNCTUALIZE_SETTINGS.keys_in("discovery")
        assert FUNCTUALIZE_SETTINGS.value_in({setting.key: ["legacy"]}, name) == [
            "legacy"
        ]
        assert FUNCTUALIZE_SETTINGS.value_in(
            {setting.key: ["legacy"], "discovery": {setting.key: ["canonical"]}},
            name,
        ) == ["canonical"]
    assert {
        "aliases",
        "cli",
        "discovery",
        "plugins",
        "shell",
        "tui",
        "vault",
    } <= FUNCTUALIZE_SETTINGS.sections()


def test_environment_names_use_canonical_declared_names() -> None:
    for setting in FUNCTUALIZE_SETTINGS.settings:
        assert FUNCTUALIZE_SETTINGS.env_var_for(setting) == (
            "FUNCTUALIZE_" + setting.name.upper().replace(".", "_")
        )
    assert (
        FUNCTUALIZE_SETTINGS.env_var_for(
            FUNCTUALIZE_SETTINGS.setting("discovery.extra_directories")
        )
        == "FUNCTUALIZE_DISCOVERY_EXTRA_DIRECTORIES"
    )


def test_setting_lookup_and_flag_map() -> None:
    assert FUNCTUALIZE_SETTINGS.setting("missing") is None
    assert FUNCTUALIZE_SETTINGS.value_in({"cli": {"output": "json"}}, "missing") is None
    assert (
        FUNCTUALIZE_SETTINGS.value_in({"cli": {"output": "json"}}, "cli.output")
        == "json"
    )
    assert FUNCTUALIZE_SETTINGS.flag("--require-file-import") == (
        FUNCTUALIZE_SETTINGS.setting("discovery.require_file_import")
    )
    assert FUNCTUALIZE_SETTINGS.flag("--does-not-exist") is None
