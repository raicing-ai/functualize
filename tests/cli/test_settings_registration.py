"""C2.4 — the settings registration API.

The point of the task: `tui.*` are the *shell's* settings, not `func`'s, so a
project app that never launches a shell should not resolve them. That only
works if the catalog is live — every derived structure used to be computed
from a module-level tuple at import time, which a registration API silently
invalidates.
"""

from __future__ import annotations

import pytest

from functualize._cli.data import func_settings as fs
from functualize._cli.data.func_settings import (
    FuncSetting,
    clear_registered_settings,
    register_settings,
    registered_settings,
    tui_settings,
)
from functualize._cli.data.settings_schema import SettingSchema


def _setting(name: str, default: str = "x") -> FuncSetting:
    section, _, key = name.rpartition(".")
    return FuncSetting(
        name=name,
        section=section,
        key=key,
        schema=SettingSchema(name=key, type="str", description=f"{name} help"),
        default=default,
    )


@pytest.fixture
def clean_registry():
    """The catalog is process-global; restore whatever was registered."""
    saved = registered_settings()
    clear_registered_settings()
    yield
    clear_registered_settings()
    register_settings(*saved)


class TestBaseCatalogHasNoShellSettings:
    def test_no_tui_entries_without_a_registration(self, clean_registry) -> None:
        """The acceptance property: no shell registered, no `tui.*`."""
        assert [s for s in fs.FUNC_SETTINGS if s.section == "tui"] == []
        assert not any(n.startswith("tui.") for n in fs.SETTINGS_ORDER)
        assert not any(n.startswith("tui.") for n in fs.DEFAULT_VALUES)

    def test_shell_settings_appear_once_registered(self, clean_registry) -> None:
        register_settings(*tui_settings())
        names = [s.name for s in fs.FUNC_SETTINGS if s.section == "tui"]
        # 7 since `tui.sensitive_keywords` was removed (2026-08-27): it was a
        # registered, schema'd, user-settable promise of masking with no consumer
        # reading it. Secret detection is model-driven (`is_secret_field`), so a
        # keyword list has nothing left to mean.
        assert len(names) == 7
        assert "tui.theme" in names

    def test_shell_settings_render_first(self, clean_registry) -> None:
        """Display order: the shell's knobs lead, as they did when hardcoded."""
        register_settings(*tui_settings())
        assert fs.SETTINGS_ORDER[0] == "tui.theme"

    def test_shell_carries_over_shell_star_unchanged(self, clean_registry) -> None:
        """`shell.*` stays in the base catalog — 2 entries, not invented ones."""
        names = {s.name for s in fs.FUNC_SETTINGS if s.section == "shell"}
        assert names == {"shell.program", "shell.sudo_password"}
        assert not any(s.section in ("runner", "watch") for s in fs.FUNC_SETTINGS), (
            "runner.*/watch.* belong to deferred S5-S7 and must not be invented"
        )


class TestDerivedStructuresAreLive:
    """The hazard the task text omitted: import-time derivation.

    Each of these was computed once from a module-level tuple. A registration
    API makes that silently stale — the setting renders in the panel and
    resolves to nothing.
    """

    def test_settings_order_tracks_registration(self, clean_registry) -> None:
        before = len(fs.SETTINGS_ORDER)
        register_settings(_setting("demo.alpha"))
        assert len(fs.SETTINGS_ORDER) == before + 1
        assert "demo.alpha" in fs.SETTINGS_ORDER

    def test_default_values_tracks_registration(self, clean_registry) -> None:
        register_settings(_setting("demo.alpha", default="hello"))
        assert fs.DEFAULT_VALUES["demo.alpha"] == "hello"

    def test_schema_tracks_registration(self, clean_registry) -> None:
        register_settings(_setting("demo.alpha"))
        assert "demo.alpha" in {s.name for s in fs.FUNC_SCHEMA.settings}

    def test_lookup_tracks_registration(self, clean_registry) -> None:
        assert fs.func_setting("demo.alpha") is None
        register_settings(_setting("demo.alpha"))
        assert fs.func_setting("demo.alpha") is not None

    def test_a_from_import_is_not_a_snapshot(self, clean_registry) -> None:
        """The idiom the whole codebase uses, including `settings_panel.py`.

        `from func_settings import FUNC_SETTINGS` binds the object once. A
        recomputed module attribute (PEP 562 `__getattr__`) would hand out a
        stale tuple here; a live view does not.
        """
        from functualize._cli.data.func_settings import FUNC_SETTINGS, SETTINGS_ORDER

        before = len(FUNC_SETTINGS)
        register_settings(_setting("demo.alpha"))

        assert len(FUNC_SETTINGS) == before + 1
        assert "demo.alpha" in SETTINGS_ORDER

    def test_a_store_built_after_registration_resolves_the_new_setting(
        self, clean_registry, tmp_path
    ) -> None:
        """The signature-default trap: `catalog=FUNC_SETTINGS` binds once."""
        register_settings(_setting("demo.alpha", default="hello"))

        from functualize._cli.data.func_settings import FuncSettingsStore

        store = FuncSettingsStore(layers=[], env={})
        assert store.effective_values().get("demo.alpha") == "hello"


class TestRegistrationRules:
    def test_registering_twice_replaces_rather_than_duplicates(
        self, clean_registry
    ) -> None:
        """A relaunched shell must not double every row in the panel."""
        register_settings(_setting("demo.alpha", default="one"))
        register_settings(_setting("demo.alpha", default="two"))

        assert [s.name for s in fs.FUNC_SETTINGS].count("demo.alpha") == 1
        assert fs.DEFAULT_VALUES["demo.alpha"] == "two"

    def test_shadowing_a_base_setting_is_rejected(self, clean_registry) -> None:
        """The base catalog is not something a component may redefine."""
        with pytest.raises(ValueError, match="base catalog"):
            register_settings(_setting("cli.output"))

    def test_registration_order_is_preserved(self, clean_registry) -> None:
        register_settings(_setting("demo.b"), _setting("demo.a"))
        order = [n for n in fs.SETTINGS_ORDER if n.startswith("demo.")]
        assert order == ["demo.b", "demo.a"]


class TestImportingTheShellRegisters:
    def test_importing_the_tui_package_contributes_tui_settings(self) -> None:
        """Importing `_cli.tui` *is* the shell being present.

        Run in a subprocess: the import is a one-time side effect, so in a
        process where `_cli.tui` is already in `sys.modules` (or where another
        test's fixture has since cleared the registry) importing again proves
        nothing. A fresh interpreter is the only honest way to assert it.
        """
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from functualize._cli.data import func_settings as fs;"
                "assert not any(n.startswith('tui.') for n in fs.SETTINGS_ORDER);"
                "import functualize._cli.tui;"
                "assert 'tui.theme' in fs.SETTINGS_ORDER;"
                "print('ok')",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout


class TestDeadSettingIsGone:
    """D-01 byproduct: `completion_debounce_ms` was declared and read by nothing."""

    def test_it_is_not_in_the_catalog(self) -> None:
        assert "tui.completion_debounce_ms" not in fs.SETTINGS_ORDER

    def test_it_is_not_a_recognized_config_key(self) -> None:
        from functualize._cli.config import _RECOGNIZED_KEYS

        assert "completion_debounce_ms" not in _RECOGNIZED_KEYS["tui"]

    def test_it_has_no_schema(self) -> None:
        from functualize._cli.data.settings_schema import SETTING_SCHEMAS

        assert "completion_debounce_ms" not in SETTING_SCHEMAS
