"""C3.1 — root CLI flags generated from the settings declaration.

The declaration is the statement: a setting that names a ``cli_flag`` gets
exactly one root option, with the declaration's own help text, on both
surfaces that have a root group. These tests hold that line from the outside —
what a flag looks like, which settings produce one, and that ``func`` and an
embedded app cannot disagree about the list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from functualize._cli.main import cli_app
from functualize.app.adapters.settings_flags import (
    declared_flag_settings,
    generated_setting_options,
    option_name_for,
    passed_setting_flags,
)
from functualize.plugin import FUNCTUALIZE_SETTINGS, AppSettingsSchema, Setting

if TYPE_CHECKING:
    from collections.abc import Iterator

    import click


def _schema(*settings: Setting) -> AppSettingsSchema:
    return AppSettingsSchema(settings=settings)


def _setting(name: str, *, cli_flag: str | None = None, type_: str = "str") -> Setting:
    return Setting(
        name=name,
        type=type_,
        description=f"{name} help",
        cli_flag=cli_flag,
    )


def _declared_flags() -> list[str]:
    return [
        str(setting.cli_flag)
        for setting in declared_flag_settings(FUNCTUALIZE_SETTINGS)
    ]


class TestFlagGeneration:
    def test_a_declared_flag_generates_one_option(self) -> None:
        options = generated_setting_options(
            _schema(_setting("demo.colour", cli_flag="--colour"))
        )

        assert [option.opts for option in options] == [["--colour"]]
        assert options[0].help == "demo.colour help"

    def test_a_setting_without_a_flag_is_not_generated(self) -> None:
        """The negative half of the AC — settings-only knobs stay off `--help`."""
        options = generated_setting_options(_schema(_setting("demo.quiet")))

        assert options == []

    def test_the_shipped_declaration_generates_eleven_flags(self) -> None:
        """The row's acceptance number, and no duplicates among them."""
        flags = _declared_flags()

        assert len(flags) == 11
        assert len(set(flags)) == 11
        assert flags == [
            option.opts[0] for option in generated_setting_options(FUNCTUALIZE_SETTINGS)
        ]

    def test_a_list_setting_generates_a_repeatable_option(self) -> None:
        """`--exclude a --exclude b` is the declared shape, not a later merge."""
        options = generated_setting_options(
            _schema(_setting("demo.patterns", cli_flag="--patterns", type_="list"))
        )

        assert options[0].multiple is True
        assert options[0].default is None

    def test_an_int_setting_converts_at_parse_time(self) -> None:
        options = generated_setting_options(
            _schema(_setting("demo.depth", cli_flag="--depth", type_="int"))
        )

        assert options[0].type.name == "integer"

    def test_the_parameter_name_follows_the_flag(self) -> None:
        """`--two-words` arrives as `two_words`, click's own convention."""
        assert (
            option_name_for(_setting("demo.two_words", cli_flag="--two-words"))
            == "two_words"
        )


class TestPassedFlags:
    def test_only_passed_flags_are_reported(self) -> None:
        """`None` and an empty tuple both mean "not given"."""
        schema = _schema(
            _setting("demo.colour", cli_flag="--colour"),
            _setting("demo.patterns", cli_flag="--patterns", type_="list"),
        )

        assert passed_setting_flags(schema, {"colour": None, "patterns": ()}) == {}

    def test_values_are_keyed_by_the_declared_name(self) -> None:
        """The resolver looks flags up by `Setting.name`, so this does too."""
        schema = _schema(_setting("discovery.scan_depth", cli_flag="--discovery-depth"))

        assert passed_setting_flags(schema, {"discovery_depth": 3}) == {
            "discovery.scan_depth": 3
        }

    def test_a_multi_value_flag_arrives_whole(self) -> None:
        schema = _schema(_setting("demo.patterns", cli_flag="--patterns", type_="list"))

        assert passed_setting_flags(schema, {"patterns": ("a", "b")}) == {
            "demo.patterns": ("a", "b")
        }


@pytest.fixture
def adapter_root_group(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[click.Group]:
    from functualize.app import FunctualizeApp, JobSources
    from functualize.app.adapters.cli import CliAdapter

    monkeypatch.chdir(tmp_path)
    app = FunctualizeApp(name="demo", job_sources=JobSources(directories=[]))
    adapter = CliAdapter()
    adapter(app)
    yield adapter._cli_group


class TestBothSurfacesShareTheList:
    def test_func_and_an_app_generate_the_same_flags(self, adapter_root_group) -> None:
        """AC22: one generated list, not two that happen to agree today."""
        declared = set(_declared_flags())

        from_func = [
            option.opts[0] for option in cli_app.params if option.opts[0] in declared
        ]
        from_app = [
            option.opts[0]
            for option in adapter_root_group.params
            if option.opts[0] in declared
        ]

        assert from_func == _declared_flags()
        assert from_app == from_func

    def test_the_app_root_group_declares_no_option_twice(
        self, adapter_root_group
    ) -> None:
        """A hand-written option beside its generated twin made click warn."""
        opts = [opt for param in adapter_root_group.params for opt in param.opts]

        assert len(opts) == len(set(opts)), opts
