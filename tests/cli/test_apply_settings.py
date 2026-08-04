"""Tests that resolved TUI settings actually reach their live consumers.

Regression cover for a setting that was reported as wired but never was:
``_apply_settings`` called ``DisplaySlot.set_display_auto_switch``, while the
method is ``set_auto_switch_setting``. A blanket ``suppress(Exception)`` ate
the resulting AttributeError, so the setting silently did nothing while every
existing test — which only checked that resolution produced the right *value*
— kept passing.

The lesson these tests encode: assert the value landed on the consumer, not
merely that it resolved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize.app.core import FunctualizeApp, JobSources


@pytest.fixture()
def tui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeInlineTUI:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)
    app = FunctualizeApp(name="settingsapp", job_sources=JobSources(directories=[]))
    return FunctualizeInlineTUI(app)


class TestApplySettings:
    def test_display_auto_switch_reaches_the_display_slot(
        self, tui: FunctualizeInlineTUI
    ) -> None:
        tui._apply_settings({"tui.display_auto_switch": "off"})

        assert tui._display_slot._display_auto_switch == "off"

    def test_theme_reaches_the_theme_manager(self, tui: FunctualizeInlineTUI) -> None:
        # An unregistered theme falls back to "transparent", so assert on a
        # theme the manager actually knows.
        tui._theme_manager.activate_theme("transparent")

        tui._apply_settings({"tui.theme": "transparent"})

        assert tui._theme_manager.active_theme_id == "transparent"

    def test_a_broken_consumer_call_is_not_swallowed(
        self, tui: FunctualizeInlineTUI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure mode that hid the bug: silent success.

        If applying a setting raises, that must surface rather than leave the
        setting quietly unapplied.
        """

        def boom(_value: str) -> None:
            raise RuntimeError("consumer exploded")

        monkeypatch.setattr(tui._display_slot, "set_auto_switch_setting", boom)

        with pytest.raises(RuntimeError, match="consumer exploded"):
            tui._apply_settings({"tui.display_auto_switch": "auto"})

    def test_unknown_settings_are_ignored(self, tui: FunctualizeInlineTUI) -> None:
        """Settings without a live consumer must not raise."""
        tui._apply_settings(
            {"tui.execution_mode": "sync", "tui.history_retention": "10"}
        )
