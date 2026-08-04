"""Centralized key dispatch — mediator for all key routing.

Routes key events based on the current (FocusMode, FocusZone) tuple
from FocusState. Implements CommandPalette protection, autocomplete
interception, target resolution, and mode-specific pass-through rules.
"""

from __future__ import annotations

from typing import Any

from functualize._cli.tui.focus import FocusMode, FocusState

__all__ = ["KEYMAPS", "KeyDispatcher"]

# ─── Keymaps ──────────────────────────────────────────────────────────────────

# NOTE: every FocusMode's dispatch path reads this table — it is
# the single source of truth for key routing (steering doc: no second
# key-routing mechanism is allowed alongside it).
# fan_in from every mode's dispatch path (KeyDispatcher.dispatch
# looks up KEYMAPS[mode] on every keypress); changing an entry here has
# app-wide behavioral effect with no compiler-level check.
KEYMAPS: dict[FocusMode, dict[str, str]] = {
    FocusMode.COMMAND: {
        "tab": "autocomplete_toggle",
        "ctrl+r": "panel_command_toggle",
        "ctrl+e": "panel_general_toggle",
        "ctrl+enter": "execute",
        "ctrl+q": "quit",
        "escape": "smartbar_clear",
        # NOTE: never bind ctrl+i/ctrl+h/ctrl+m here:
        # terminals deliver those byte sequences as tab/backspace/enter (see
        # tests/tui_audit/test_key_aliasing.py), so a KEYMAPS entry
        # under those names can never fire.
        "ctrl+g": "ring_first",
        "ctrl+j": "ring_next",
        "ctrl+k": "ring_prev",
        "ctrl+l": "ring_last",
        "ctrl+u": "display_prev",
        "ctrl+o": "display_next",
        "shift+tab": "zone_cycle",
        "ctrl+s": "save_shortcut",
    },
    FocusMode.NORMAL: {
        "j": "cursor_down",
        "k": "cursor_up",
        "h": "cursor_left",
        "l": "cursor_right",
        "down": "cursor_down",
        "up": "cursor_up",
        "left": "cursor_left",
        "right": "cursor_right",
        "i": "enter_insert",
        "I": "enter_persist",
        "r": "reset_override",
        "slash": "enter_filter",
        "enter": "drill_down",
        # Run the command straight from the pre-flight/config panel after
        # editing fields, without Esc'ing back to the SmartBar first. Routes to
        # app.action_execute (panels define no action_execute). NOTE: unlike
        # COMMAND mode there is no plain-`enter` fallback here — `enter` is
        # already claimed by drill_down — so this only fires on terminals that
        # deliver a distinct ctrl+enter (Kitty protocol); execute is always
        # still reachable via Esc → COMMAND.
        "ctrl+enter": "execute",
        "escape": "exit_panel",
        # Detail-view actions. They resolve to SourceChainDetailView when one
        # is pushed (PanelHost.push_view makes it the active panel) and are
        # inert otherwise, since no app-level action_toggle_removal /
        # action_save exists to fall back to. Adding them here rather than
        # giving the detail view its own bindings keeps this table the single
        # source of truth for key routing.
        "d": "toggle_removal",
        # New-file picker. Resolves to the Files panels (Config Files /
        # Settings Files, which define action_new_file) and is inert
        # elsewhere — no app-level action_new_file exists to fall back to.
        "n": "new_file",
        "ctrl+s": "save",
        "ctrl+j": "ring_next",
        "ctrl+k": "ring_prev",
        "ctrl+g": "ring_first",
        "ctrl+l": "ring_last",
        "ctrl+r": "panel_command_toggle",
        "ctrl+e": "panel_general_toggle",
        "ctrl+u": "display_prev",
        "ctrl+o": "display_next",
        "shift+tab": "zone_cycle",
    },
    FocusMode.INSERT: {
        "escape": "exit_insert",
        "enter": "confirm_edit",
        "tab": "select_choice",
        "up": "choice_up",
        "down": "choice_down",
    },
    FocusMode.FILTER: {
        "escape": "exit_filter",
        "enter": "apply_filter",
    },
}

_AUTOCOMPLETE_INTERCEPTS: dict[str, str] = {
    "tab": "autocomplete_accept",
    "enter": "autocomplete_accept",
    "down": "autocomplete_next",
    "up": "autocomplete_prev",
    "escape": "autocomplete_dismiss",
}


# ─── KeyDispatcher ────────────────────────────────────────────────────────────


class KeyDispatcher:
    """Centralized key dispatch: reads FocusState, looks up keymap, calls action.

    Instantiated once by the TUI App and invoked from ``on_key(event)``.
    """

    def __init__(self, focus_state: FocusState, app: Any) -> None:
        self._focus_state = focus_state
        self._app = app

    # ─── Public API ───────────────────────────────────────────────────

    # WARNING: central routing point for every key event in the app;
    # after R2/R3 its branching grew to include the
    # generalized overlay guard and the plain-enter execute fallback.
    # single point of failure for all keyboard input — a routing
    # bug here is invisible until a specific key/mode/overlay combination is
    # hit; no compiler-level check catches a misordered guard.
    def dispatch(self, event: Any) -> bool:
        """Dispatch a key event. Returns True if handled, False if pass-through.

        Algorithm:
        1. Guard: any non-base screen on screen_stack (ModalScreen,
           CommandPalette, or any future overlay) → return False (pass-through)
        2. COMMAND mode + autocomplete visible → intercept Tab/Enter/Down/Up/Escape
        3. Keymap lookup for current mode
        4. Target resolution: panel widget if it has the action, else app
        5. NORMAL mode: suppress unrecognized printable keys
        6. COMMAND/INSERT/FILTER: pass through unrecognized keys
        """
        # Req 12.1-12.4: overlay guard is the FIRST guard —
        # generalized from a CommandPalette-only check to cover any screen
        # pushed on top of the base screen (CommandPalette, ShortcutSaveModal,
        # or any future ModalScreen/Screen).
        if self._is_overlay_active():
            return False

        mode = self._focus_state.mode

        # Req 1.6: COMMAND mode with autocomplete visible → intercept
        if mode is FocusMode.COMMAND and self._is_autocomplete_visible():
            ac_action = _AUTOCOMPLETE_INTERCEPTS.get(event.key)
            if ac_action:
                event.prevent_default()
                event.stop()
                method = getattr(self._app, f"action_{ac_action}", None)
                if method:
                    method()
                return True

        # Req 1.1: Keymap lookup for current mode
        keymap = KEYMAPS.get(mode, {})
        action_name = keymap.get(event.key)

        if action_name:
            # Req 1.2: Match found → prevent default, stop, invoke action
            event.prevent_default()
            event.stop()
            target = self._resolve_target(action_name)
            method = getattr(target, f"action_{action_name}", None)
            if method:
                method()
            return True

        # plain-enter execute fallback, COMMAND mode only.
        # COMMAND's KEYMAPS deliberately does not define "enter" (INSERT and
        # FILTER already claim it for confirm_edit/apply_filter, and NORMAL
        # claims it for drill_down — see KEYMAPS above), so this only ever
        # runs for COMMAND. The autocomplete intercept above already
        # consumes "enter" first when the dropdown is visible, so by the
        # time we reach here the dropdown is guaranteed closed for "enter"
        # in COMMAND mode — the explicit _is_autocomplete_visible() check
        # is defense-in-depth against that invariant changing.
        if (
            mode is FocusMode.COMMAND
            and event.key == "enter"
            and not self._is_autocomplete_visible()
            and self._is_execute_ready()
        ):
            event.prevent_default()
            event.stop()
            method = getattr(self._app, "action_execute", None)
            if method:
                method()
            return True

        # Req 1.3: NORMAL mode suppresses unrecognized printable keys
        if mode is FocusMode.NORMAL and len(event.key) == 1 and event.key.isprintable():
            event.prevent_default()
            event.stop()
            return True

        # Req 1.4, 1.7: COMMAND/INSERT/FILTER pass through unrecognized keys
        return False

    # ─── Private helpers ──────────────────────────────────────────────

    def _is_overlay_active(self) -> bool:
        """Check if any non-base screen is on top of the screen_stack.

        Generalizes the original CommandPalette-only guard:
        Textual's ``screen_stack[0]`` is always the app's base screen: any
        entry pushed after it (a ``ModalScreen`` such as
        ``ShortcutSaveModal``, the built-in ``CommandPalette``, or any future
        overlay) means an overlay is active and all app-/panel-level key
        routing must pass through untouched. This is a strict superset of
        the previous CommandPalette-only check — CommandPalette is itself a
        pushed screen, so it is still covered.
        """
        try:
            return len(self._app.screen_stack) > 1
        except (TypeError, AttributeError):
            return False

    def _is_autocomplete_visible(self) -> bool:
        """Check if the autocomplete dropdown is currently visible.

        Delegates to the app's ``is_autocomplete_visible()`` method.
        if that app-level checker is unavailable, return
        ``False`` directly — do not fall back to importing
        ``functualize._cli.functualize_autocomplete`` (that module path
        does not exist; the previous fallback silently swallowed the
        resulting ``ImportError``).
        """
        checker = getattr(self._app, "is_autocomplete_visible", None)
        if checker is not None:
            return bool(checker())
        return False

    def _is_execute_ready(self) -> bool:
        """Check if SmartBar readiness allows the plain-enter execute
        fallback. Delegates to the app's ``is_execute_ready()``
        method; returns ``False`` if unavailable so the fallback never
        fires against an app that hasn't opted in."""
        checker = getattr(self._app, "is_execute_ready", None)
        if checker is None:
            return False
        return bool(checker())

    def _resolve_target(self, action_name: str) -> Any:
        """Resolve the target for an action.

        If the active panel widget defines ``action_{name}``, route there.
        Otherwise fall back to the app instance.
        """
        panel = getattr(self._app, "active_panel", None)
        if panel is not None and hasattr(panel, f"action_{action_name}"):
            return panel
        return self._app
