"""A secret field is masked in the SmartBar while it is being edited.

INSERT mode repurposes the SmartBar rather than opening a separate editor, so
"mask as typed" is `Input.password` on the bar itself, turned on for the
duration of the edit and off again on restore.

Two things have to hold together, and only one of them is obvious:

- the bar masks, and
- autocomplete is suppressed while it does — a dropdown renders candidate text
  unmasked, so completing a secret would print it one row below the bullets that
  are hiding it.

COMMAND mode is deliberately never masked: a whole command line cannot be
half-masked without breaking editing of the rest of it.
"""

from __future__ import annotations

import contextlib

import pytest
from textual.app import App, ComposeResult

from functualize._cli.tui.bar import BarReadiness, SmartBar


class _BarHarness(App[None]):
    """Smallest app that can host a real SmartBar.

    A real bar, not a mock: `password` is a Textual reactive, and the whole
    point of this module is that setting it actually changes what the widget
    renders. A stand-in with a plain attribute would pass whatever we wrote.
    """

    def compose(self) -> ComposeResult:
        yield SmartBar(id="bar")


@contextlib.asynccontextmanager
async def _live_bar():
    """Yield a mounted SmartBar with its pre-edit state already saved."""
    app = _BarHarness()
    async with app.run_test():
        bar = app.query_one("#bar", SmartBar)
        bar.value = "deploy --region us-east-1"
        bar.save_state()
        yield bar


@pytest.fixture()
async def bar():
    async with _live_bar() as b:
        yield b


@pytest.mark.asyncio
class TestMaskWhileEditing:
    async def test_secret_edit_masks_the_bar(self, bar: SmartBar):
        bar.enter_edit_mode("credential", "hunter2", "Editing credential", secret=True)
        assert bar.password is True
        assert bar.readiness is BarReadiness.EDITING

    async def test_plain_edit_does_not_mask(self, bar: SmartBar):
        bar.enter_edit_mode("sort_key", "created_at", "Editing sort_key")
        assert bar.password is False

    async def test_restore_unmasks(self, bar: SmartBar):
        """A bar left masked would silently hide every later command typed."""
        bar.enter_edit_mode("credential", "hunter2", "Editing credential", secret=True)
        bar.restore_state()
        assert bar.password is False
        assert bar._suppress_autocomplete is False

    async def test_secret_edit_suppresses_autocomplete(self, bar: SmartBar):
        bar.enter_edit_mode("credential", "hunter2", "Editing credential", secret=True)
        assert bar._suppress_autocomplete is True


@pytest.mark.asyncio
class TestAutocompleteSuppression:
    @staticmethod
    def _completer(target):
        """A SmartBarAutoComplete bound to `target`, without Textual mounting."""
        from functualize._cli.tui.smart_bar_autocomplete import SmartBarAutoComplete

        completer = SmartBarAutoComplete.__new__(SmartBarAutoComplete)
        completer.target = target
        return completer

    async def test_no_candidates_while_masked(self, bar: SmartBar):
        bar.enter_edit_mode("credential", "hunter2", "Editing credential", secret=True)
        completer = self._completer(bar)
        state = type("S", (), {"text": "hun", "cursor_position": 3})()
        assert completer.get_candidates(state) == []

    async def test_candidates_resume_after_restore(self, bar: SmartBar):
        """Suppression must not outlive the secret edit that caused it.

        The bare `__new__` completer used here has no `input_modes`, so reaching
        that attribute is the observable proof that the guard did *not* fire and
        the call fell through to the real resolution path. Asserting on returned
        candidates would need the whole TUI stood up to say the same thing.
        """
        bar.enter_edit_mode("credential", "hunter2", "Editing credential", secret=True)
        bar.restore_state()
        completer = self._completer(bar)
        state = type("S", (), {"text": "hun", "cursor_position": 3})()
        with pytest.raises(AttributeError, match="input_modes"):
            completer.get_candidates(state)
