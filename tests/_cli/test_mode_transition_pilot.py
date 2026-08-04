"""mode-transition Pilot matrix.

Covers every valid ``(from_mode, to_mode)`` transition defined in
``FocusState._VALID_TRANSITIONS`` (``src/functualize/_cli/tui/focus.py``),
each triggered via a REAL key press through a Pilot-driven real app
instance (never a direct ``.transition()``/``.force()`` call) — exercising
the same production wiring a user's keypress goes through:
``Pilot.press -> App.on_key -> KeyDispatcher.dispatch -> action_* ->
FocusState.transition``.

The six non-no-op transitions (``COMMAND -> COMMAND`` is an explicit no-op
entry in the FSM's valid-transition set, not a user-triggerable mode
change, and is out of scope here):

- COMMAND -> NORMAL   (Ctrl+E opens the general panel ring)
- NORMAL  -> COMMAND  (Escape exits the panel back to the SmartBar)
- NORMAL  -> INSERT   ('i' on a field-bearing panel row)
- INSERT  -> NORMAL   (Escape cancels the edit)
- NORMAL  -> FILTER   ('/' on a Filterable panel)
- FILTER  -> NORMAL   (Escape clears the filter)

Panel setup notes (see ``contributor/guides/steering_textual_tui.md``
§4.2): dynamic jobs (as registered by the shared ``tui_app`` fixture)
yield no field descriptors, so the *command* panel ring (Ctrl+R) never
has fields to show. The *general* panel ring (Ctrl+E) is used instead —
it is always available regardless of job field defs and hosts two
real, already-populated panels: the Job Browser (index 0, implements
``Filterable`` — used for the FILTER transitions) and Settings (index 1,
implements ``get_cursor_field()`` — used for the INSERT transitions).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from functualize._cli.tui.focus import FocusMode, FocusZone
from tests._cli._tui_fixtures import tui_app

if TYPE_CHECKING:
    from functualize._cli.tui.app import FunctualizeInlineTUI

__all__ = ["tui_app"]


def _mode(app: FunctualizeInlineTUI) -> FocusMode:
    """Read the current FocusState mode through a function call.

    Routing the read through a call (rather than repeating the bare
    ``app._focus_state.mode`` attribute-access expression) keeps mypy from
    narrowing that expression's static type to the *first* literal it sees
    asserted against and then flagging later, differently-valued assertions
    on the same real (mutated-by-keypress) attribute as "non-overlapping" —
    a false positive, since the mode genuinely changes between assertions
    as a result of the intervening ``pilot.press(...)`` calls.
    """
    return app._focus_state.mode


def _zone(app: FunctualizeInlineTUI) -> FocusZone:
    """Read the current FocusState zone — see ``_mode`` for rationale."""
    return app._focus_state.zone


async def test_command_to_normal_via_ctrl_e(tui_app: FunctualizeInlineTUI) -> None:
    """COMMAND -> NORMAL: Ctrl+E opens the general panel ring."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert _mode(tui_app) is FocusMode.COMMAND

        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()

        assert _mode(tui_app) is FocusMode.NORMAL
        assert _zone(tui_app) is FocusZone.PANEL


async def test_normal_to_command_via_escape(tui_app: FunctualizeInlineTUI) -> None:
    """NORMAL -> COMMAND: Escape exits the panel back to the SmartBar."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert _mode(tui_app) is FocusMode.NORMAL

        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert _mode(tui_app) is FocusMode.COMMAND
        assert _zone(tui_app) is FocusZone.SMARTBAR


async def test_normal_to_insert_via_i_on_settings_panel(
    tui_app: FunctualizeInlineTUI,
) -> None:
    """NORMAL -> INSERT: 'i' on the Settings panel's cursor field."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("ctrl+e")  # open general ring -> NORMAL, Job Browser (idx 0)
        await pilot.pause()
        assert _mode(tui_app) is FocusMode.NORMAL

        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("ctrl+j")  # ring_next -> Settings panel (idx 1)
        await pilot.pause()

        panel = tui_app.active_panel
        assert panel is not None
        get_cursor_field = getattr(panel, "get_cursor_field", None)
        assert get_cursor_field is not None, (
            "active panel (expected SettingsPanel) must expose "
            "get_cursor_field() (PanelActions)"
        )
        assert get_cursor_field() is not None, (
            "Settings panel must have a populated cursor field for the "
            "NORMAL -> INSERT transition to be reachable"
        )

        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        assert _mode(tui_app) is FocusMode.INSERT


async def test_insert_to_normal_via_escape(tui_app: FunctualizeInlineTUI) -> None:
    """INSERT -> NORMAL: Escape cancels the edit without applying changes."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("ctrl+j")
        await pilot.pause()
        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        assert _mode(tui_app) is FocusMode.INSERT

        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert _mode(tui_app) is FocusMode.NORMAL
        assert _zone(tui_app) is FocusZone.PANEL


async def test_normal_to_filter_via_slash_on_job_browser(
    tui_app: FunctualizeInlineTUI,
) -> None:
    """NORMAL -> FILTER: '/' on the (Filterable) Job Browser panel."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("ctrl+e")  # open general ring -> NORMAL, Job Browser (idx 0)
        await pilot.pause()
        assert _mode(tui_app) is FocusMode.NORMAL

        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()

        assert _mode(tui_app) is FocusMode.FILTER


async def test_filter_to_normal_via_escape(tui_app: FunctualizeInlineTUI) -> None:
    """FILTER -> NORMAL: Escape clears the filter and returns to NORMAL."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        assert _mode(tui_app) is FocusMode.FILTER

        tui_app.set_focus(None)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert _mode(tui_app) is FocusMode.NORMAL
        assert _zone(tui_app) is FocusZone.PANEL
