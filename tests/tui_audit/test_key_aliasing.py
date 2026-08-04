"""Proof: terminal key aliasing makes some KEYMAPS entries unreachable.

Terminals encode Ctrl+I and Tab as the same byte (0x09), and Ctrl+H and
Backspace as 0x08. Textual's XTermParser normalizes these to ``tab`` /
``backspace`` — a real terminal NEVER delivers ``event.key == "ctrl+i"``.

Consequence for src/functualize/_cli/tui/key_handler.py:
- KEYMAPS[COMMAND]["ctrl+i"] = "display_next"  → dead (arrives as "tab",
  which COMMAND maps to "autocomplete_toggle" instead)
- KEYMAPS[NORMAL]["ctrl+i"]  = "display_next"  → dead ("tab" is unmapped
  in NORMAL, so the key is silently ignored)
- KEYMAPS[*]["ctrl+h"]       = "ring_first"    → dead (arrives as
  "backspace")

The alias IS exposed on the event (``Key.name_aliases`` contains
``ctrl_i``), so a dispatcher that wants to honor ctrl+i must match
against aliases, not ``event.key`` alone — or simply bind "tab" /
"backspace" deliberately.
"""

from __future__ import annotations

from textual._xterm_parser import XTermParser
from textual.events import Key

from functualize._cli.tui.focus import FocusMode
from functualize._cli.tui.key_handler import KEYMAPS


def _parse_single(byte_seq: str) -> Key:
    """Feed one byte sequence to a fresh parser and return the Key event."""
    parser = XTermParser()
    events = [e for e in parser.feed(byte_seq) if isinstance(e, Key)]
    assert len(events) == 1, f"expected one Key event, got {events!r}"
    return events[0]


class TestTerminalAliasing:
    """What the terminal actually delivers for the aliased control keys."""

    def test_ctrl_i_arrives_as_tab(self) -> None:
        event = _parse_single("\x09")
        assert event.key == "tab"
        assert "ctrl_i" in event.name_aliases

    def test_ctrl_h_arrives_as_backspace(self) -> None:
        event = _parse_single("\x08")
        assert event.key == "backspace"

    def test_ctrl_m_arrives_as_enter(self) -> None:
        event = _parse_single("\x0d")
        assert event.key == "enter"


class TestKeymapDeadEntries:
    """Dead-KEYMAPS-entry inversion tests.

    These tests originally proved the ``ctrl+i``/``ctrl+h`` dead-key bug
    (they asserted the buggy entries were present and unreachable). R2 removed the dead entries and rebound the affected
    actions to terminal-safe keys (``ctrl+o`` for ``display_next``,
    ``ctrl+g`` for ``ring_first``). By design, the same test names and
    fixtures are kept, with assertions flipped to the corrected behavior,
    so this class continues to document the defect's history while
    standing as a permanent regression guard against its reintroduction.
    """

    def test_command_mode_ctrl_i_is_unreachable(self) -> None:
        """COMMAND no longer maps ctrl+i at all; display_next now lives on
        ctrl+o, which the terminal delivers unaliased."""
        command_map = KEYMAPS[FocusMode.COMMAND]
        assert "ctrl+i" not in command_map, "dead ctrl+i entry reintroduced"
        delivered = _parse_single("\x09").key
        assert delivered == "tab"
        assert command_map["ctrl+o"] == "display_next"

    def test_normal_mode_ctrl_i_is_unreachable(self) -> None:
        normal_map = KEYMAPS[FocusMode.NORMAL]
        assert "ctrl+i" not in normal_map, "dead ctrl+i entry reintroduced"
        delivered = _parse_single("\x09").key
        # 'tab' is still not mapped in NORMAL — unrelated to display_next,
        # which now lives on ctrl+o.
        assert delivered not in normal_map
        assert normal_map["ctrl+o"] == "display_next"

    def test_ctrl_h_is_unreachable_in_both_modes(self) -> None:
        delivered = _parse_single("\x08").key  # backspace
        for mode in (FocusMode.COMMAND, FocusMode.NORMAL):
            keymap = KEYMAPS[mode]
            assert "ctrl+h" not in keymap, "dead ctrl+h entry reintroduced"
            assert delivered not in keymap
            # ring_first was rebound to ctrl+g, not removed.
            assert keymap["ctrl+g"] == "ring_first"


class TestKeymapFixedBindings:
    """The fixed bindings arrive unaliased and are
    reachable from a real terminal."""

    def test_ctrl_o_arrives_unaliased_and_maps_to_display_next(self) -> None:
        event = _parse_single("\x0f")
        assert event.key == "ctrl+o"
        assert KEYMAPS[FocusMode.COMMAND]["ctrl+o"] == "display_next"
        assert KEYMAPS[FocusMode.NORMAL]["ctrl+o"] == "display_next"

    def test_ctrl_g_arrives_unaliased_and_maps_to_ring_first(self) -> None:
        event = _parse_single("\x07")
        assert event.key == "ctrl+g"
        assert KEYMAPS[FocusMode.COMMAND]["ctrl+g"] == "ring_first"
        assert KEYMAPS[FocusMode.NORMAL]["ctrl+g"] == "ring_first"

    def test_ctrl_u_display_prev_unaffected_by_the_fix(self) -> None:
        """Regression guard: ctrl+u (display_prev) was already safe and
        must remain untouched by the ctrl+i/ctrl+h rebind work."""
        event = _parse_single("\x15")
        assert event.key == "ctrl+u"
        assert KEYMAPS[FocusMode.COMMAND]["ctrl+u"] == "display_prev"
        assert KEYMAPS[FocusMode.NORMAL]["ctrl+u"] == "display_prev"
