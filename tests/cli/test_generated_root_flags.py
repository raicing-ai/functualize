"""C3.1 — root CLI flags generated from `Setting.cli_flag`.

Two halves, and the second is the one the task text understates. Declaring the
flag is easy; making it *override file and env* means the settings store needs
a CLI precedence rung, which it did not have — its layers were files + env.
"""

from __future__ import annotations

import pytest

from functualize._cli.data.func_settings import (
    PRECEDENCE_CLI,
    PRECEDENCE_ENV,
    FuncSetting,
    FuncSettingsStore,
    clear_registered_settings,
    register_settings,
    registered_settings,
)
from functualize._cli.data.settings_schema import SettingSchema


def _setting(
    name: str,
    *,
    default: str = "base",
    cli_flag: str | None = None,
    phase: str | None = None,
) -> FuncSetting:
    section, _, key = name.rpartition(".")
    return FuncSetting(
        name=name,
        section=section,
        key=key,
        schema=SettingSchema(name=key, type="str", description=f"{name} help"),
        default=default,
        cli_flag=cli_flag,
        phase=phase,
    )


@pytest.fixture
def clean_registry():
    saved = registered_settings()
    clear_registered_settings()
    yield
    clear_registered_settings()
    register_settings(*saved)


class TestFlagGeneration:
    def test_a_setting_declaring_a_flag_generates_one(self, clean_registry) -> None:
        from functualize.app.adapters.cli import _setting_flag_specs

        register_settings(_setting("demo.colour", cli_flag="--colour"))
        flags = {flag for flag, _dest, _name, _help in _setting_flag_specs()}
        assert "--colour" in flags

    def test_a_setting_without_one_does_not(self, clean_registry) -> None:
        """The negative half of the AC — file/env-only settings stay hidden."""
        from functualize.app.adapters.cli import _setting_flag_specs

        register_settings(_setting("demo.quiet"))
        names = {name for _flag, _dest, name, _help in _setting_flag_specs()}
        assert "demo.quiet" not in names

    def test_no_shipped_setting_declares_a_flag_yet(self) -> None:
        """Baseline guard, mirroring C2.1's.

        Generation is live and opt-in; if a shipped setting ever declares a
        flag, that is a deliberate act and this test is where it gets noticed.
        """
        from functualize.app.adapters.cli import _setting_flag_specs

        assert _setting_flag_specs() == []

    def test_flag_becomes_a_click_option(self, clean_registry) -> None:
        from functualize.app.adapters.cli import _generated_setting_options

        register_settings(_setting("demo.colour", cli_flag="--colour"))
        options = _generated_setting_options()
        assert [o.opts for o in options] == [["--colour"]]
        assert options[0].default is None, "un-passed must be distinguishable"

    def test_dest_is_derived_from_the_flag(self, clean_registry) -> None:
        """`--log-level` arrives as `log_level`, click's own convention."""
        from functualize.app.adapters.cli import _setting_flag_specs

        register_settings(_setting("demo.two_words", cli_flag="--two-words"))
        specs = {name: dest for _flag, dest, name, _help in _setting_flag_specs()}
        assert specs["demo.two_words"] == "two_words"

    def test_help_text_comes_from_the_setting(self, clean_registry) -> None:
        from functualize.app.adapters.cli import _setting_flag_specs

        register_settings(_setting("demo.colour", cli_flag="--colour"))
        helps = {name: h for _f, _d, name, h in _setting_flag_specs()}
        assert "demo.colour help" in helps["demo.colour"]


class TestPrecedence:
    """The half that needed a new rung in the store."""

    def test_cli_outranks_env(self) -> None:
        assert PRECEDENCE_CLI > PRECEDENCE_ENV

    def test_a_cli_override_wins_over_env(self, clean_registry) -> None:
        register_settings(_setting("demo.colour", cli_flag="--colour"))
        store = FuncSettingsStore(
            layers=[], env={"FUNCTUALIZE_DEMO_COLOUR": "from-env"}
        )
        assert store.effective_values()["demo.colour"] == "from-env"

        store.set_cli_override("demo.colour", "from-cli", flag="--colour")
        assert store.effective_values()["demo.colour"] == "from-cli"

    def test_a_cli_override_wins_over_default(self, clean_registry) -> None:
        register_settings(_setting("demo.colour", default="base", cli_flag="--colour"))
        store = FuncSettingsStore(layers=[], env={})
        assert store.effective_values()["demo.colour"] == "base"

        store.set_cli_override("demo.colour", "from-cli")
        assert store.effective_values()["demo.colour"] == "from-cli"

    def test_the_source_label_names_the_flag(self, clean_registry) -> None:
        """So the TUI's source chain says `--colour`, not "command line"."""
        register_settings(_setting("demo.colour", cli_flag="--colour"))
        store = FuncSettingsStore(layers=[], env={})
        store.set_cli_override("demo.colour", "from-cli", flag="--colour")
        assert store.source_labels()["demo.colour"] == "--colour"

    def test_an_unpassed_flag_adds_no_rung(self, clean_registry) -> None:
        """ "Not given" and "given as empty" must stay distinguishable.

        A store that never had an override recorded must resolve exactly as it
        did before C3.1 existed — this is what keeps func's own behaviour
        unchanged while no setting declares a flag.
        """
        register_settings(_setting("demo.colour", default="base", cli_flag="--colour"))
        store = FuncSettingsStore(layers=[], env={})

        key = next(k for k in store.resolve() if k.name == "demo.colour")
        assert not [e for e in key.chain if e.source_id.startswith("cli:")]
        assert store.effective_values()["demo.colour"] == "base"

    def test_overrides_are_per_store(self, clean_registry) -> None:
        register_settings(_setting("demo.colour", cli_flag="--colour"))
        a = FuncSettingsStore(layers=[], env={})
        b = FuncSettingsStore(layers=[], env={})
        a.set_cli_override("demo.colour", "only-a")

        assert a.effective_values()["demo.colour"] == "only-a"
        assert b.effective_values()["demo.colour"] == "base"


class TestApplyOverrides:
    def test_passed_flags_are_recorded(self, clean_registry, monkeypatch) -> None:
        from functualize.app.adapters import cli as cli_mod

        register_settings(_setting("demo.colour", cli_flag="--colour"))
        recorded: dict[str, str] = {}

        class _Store:
            @classmethod
            def discover(cls) -> _Store:
                return cls()

            def set_cli_override(
                self, name: str, value: str, *, flag: str = ""
            ) -> None:
                recorded[name] = value

        monkeypatch.setattr(
            "functualize._cli.data.func_settings.FuncSettingsStore", _Store
        )
        cli_mod._apply_setting_overrides({"colour": "red"})
        assert recorded == {"demo.colour": "red"}

    def test_unpassed_flags_do_not_build_a_store(self, clean_registry) -> None:
        """No flags given must be a complete no-op, not a store construction."""
        from functualize.app.adapters import cli as cli_mod

        register_settings(_setting("demo.colour", cli_flag="--colour"))
        # Would raise if it tried to discover a store.
        cli_mod._apply_setting_overrides({"colour": None})
