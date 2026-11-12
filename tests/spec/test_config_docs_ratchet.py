"""Keep the published framework settings reference tied to the declaration."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from functualize._cli.data.config_vocabulary import find_unknown_keys
from functualize.plugin import FUNCTUALIZE_SETTINGS

DOCS = Path(__file__).parents[2] / "docs"
CONFIG = (DOCS / "cli" / "config.md").read_text()


def test_reference_lists_every_declared_setting_once() -> None:
    section = CONFIG.split("## Settings Reference", 1)[1].split("## ", 1)[0]
    names = re.findall(r"^\| `([a-z][a-z0-9_.]*)` \|", section, re.MULTILINE)
    declared = [setting.name for setting in FUNCTUALIZE_SETTINGS.settings]
    assert len(names) == len(set(names))
    assert set(names) == set(declared)


def test_environment_table_names_the_declared_variables() -> None:
    rows = re.findall(
        r"^\| `([^`]+)` \| `(FUNCTUALIZE_[A-Z_]+)` \|$",
        CONFIG,
        re.MULTILINE,
    )
    assert len(rows) >= 9
    for locations, env_name in rows:
        for location in locations.split(" or "):
            name = location.replace("[", "").replace("]", "")
            setting = FUNCTUALIZE_SETTINGS.setting(name)
            if setting is None:
                setting = next(
                    (
                        item
                        for item in FUNCTUALIZE_SETTINGS.settings
                        if item.key == name and "" in item.accepted_places
                    ),
                    None,
                )
            assert setting is not None, name
            assert FUNCTUALIZE_SETTINGS.env_var_for(setting) == env_name


def test_published_settings_toml_blocks_have_only_declared_keys() -> None:
    sections = (
        ("### Schema", ()),
        ("### pyproject.toml", ("tool", "functualize")),
        ("### .functualize.toml (Alternative)", ()),
    )
    for heading, prefix in sections:
        content = CONFIG.split(heading, 1)[1]
        toml = content.split("```toml\n", 1)[1].split("```", 1)[0]
        data = tomllib.loads(toml)
        for part in prefix:
            data = data[part]
        assert not find_unknown_keys(
            data, file=Path("documented-settings.toml"), schema=FUNCTUALIZE_SETTINGS
        )


def test_documented_diagnostics_and_renames_are_current() -> None:
    shell = (DOCS / "guides" / "shell.md").read_text()
    guide = (DOCS / "guides" / "configuration.md").read_text()
    assert "containing only `root = true` is `○ found`" in CONFIG
    assert "`config.unknown_keys`" in CONFIG
    assert "Unrecognized section in config | Silently ignored" not in CONFIG
    assert "Unrecognized key in recognized section | Warning to stderr" not in CONFIG
    assert "FUNCTUALIZE_SHELL_SUDO_PASSWORD" in shell
    assert "FUNCTUALIZE_SUDO_PASSWORD" not in shell
    assert "config.unknown_keys" in guide
