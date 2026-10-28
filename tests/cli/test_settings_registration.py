"""Declared settings replace process-wide catalog registration."""

from __future__ import annotations

import subprocess
import sys

import pytest

from functualize._cli.data import func_settings as fs
from functualize._cli.data.func_settings import FuncSettingsStore
from functualize.plugin import FUNCTUALIZE_SETTINGS, Setting


def test_the_legacy_catalog_is_a_fixed_projection() -> None:
    assert not any(name.startswith("tui.") for name in fs.SETTINGS_ORDER)
    assert {s.name for s in fs.FUNC_SETTINGS if s.section == "shell"} == {
        "shell.program",
        "shell.sudo_password",
    }
    assert tuple(s.name for s in fs.FUNC_SETTINGS) == fs.SETTINGS_ORDER


def test_shell_rows_live_in_the_declaration() -> None:
    names = [s.name for s in FUNCTUALIZE_SETTINGS.settings if s.surface == "tui"]
    assert len(names) == 7
    assert names[0] == "tui.theme"


def test_explicit_schema_extends_one_store_without_changing_another(tmp_path) -> None:
    schema = FUNCTUALIZE_SETTINGS.extend(
        Setting("demo.alpha", "str", "demo.alpha help", default="hello")
    )
    custom = FuncSettingsStore(
        schema, cwd=tmp_path, env={}, global_dir=tmp_path / "global"
    )
    ordinary = FuncSettingsStore(cwd=tmp_path, env={}, global_dir=tmp_path / "global")
    assert custom.effective_values()["demo.alpha"] == "hello"
    assert "demo.alpha" not in ordinary.effective_values()
    assert FUNCTUALIZE_SETTINGS.setting("demo.alpha") is None


def test_duplicate_declared_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="cli.output"):
        FUNCTUALIZE_SETTINGS.extend(
            Setting("cli.output", "str", "colliding declaration")
        )


def test_importing_the_shell_has_no_catalog_side_effect() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from functualize._cli.data import func_settings as fs;"
            "before = tuple(fs.SETTINGS_ORDER);"
            "import functualize._cli.tui;"
            "assert tuple(fs.SETTINGS_ORDER) == before;"
            "print('ok')",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_removed_setting_is_absent_from_both_catalogs() -> None:
    assert "tui.completion_debounce_ms" not in fs.SETTINGS_ORDER
    assert FUNCTUALIZE_SETTINGS.setting("tui.completion_debounce_ms") is None
