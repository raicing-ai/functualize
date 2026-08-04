"""unreachable-key unit guard.

Asserts no entry in ``key_handler.py``'s ``KEYMAPS`` (any ``FocusMode``)
uses a terminal-aliased key that can never be delivered by a real terminal.

Scope: this guard targets ``key_handler.py``'s ``KEYMAPS`` only. The
separate, unreferenced ``KEYMAPS`` copy in ``tui/models/focus_state.py`` is
explicitly out of scope per spec.md Exclusion 7 and is not imported or
asserted against here.
"""

from __future__ import annotations

from functualize._cli.tui.key_handler import KEYMAPS

_UNREACHABLE_KEYS = frozenset({"ctrl+i", "ctrl+h", "ctrl+m"})


def test_no_unreachable_keys_in_any_focus_mode() -> None:
    offenders = {
        mode: sorted(_UNREACHABLE_KEYS & keymap.keys())
        for mode, keymap in KEYMAPS.items()
        if _UNREACHABLE_KEYS & keymap.keys()
    }
    assert not offenders, f"unreachable keys found in KEYMAPS: {offenders}"
