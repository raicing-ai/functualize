"""Custom AutoComplete subclass for functualize SmartBar.

Overrides textual-autocomplete v4's default behaviors to:
1. Show dropdown when candidates exist (even with empty search string)
2. Skip re-filtering since SmartBarAutoComplete already filters
3. Handle context-aware completion insertion
4. Use FunctualizeDropdownItem for separate display vs insertion values
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._cli.tui.smart_bar_autocomplete import SmartBarAutoComplete

try:
    from textual_autocomplete import AutoComplete, DropdownItem
    from textual_autocomplete._autocomplete import TargetState  # noqa: TC002

    class FunctualizeDropdownItem(DropdownItem):
        """DropdownItem subclass that separates display text from insertion value.

        In textual-autocomplete v4, DropdownItem.value returns main.plain which
        is used for both display AND insertion. We need the display to show
        rich information (name + source + description) but insert only the
        clean command/flag name.
        """

        def __init__(
            self,
            main: str | Any,
            insertion_value: str,
            prefix: str | Any | None = None,
            id: str | None = None,
            disabled: bool = False,
        ) -> None:
            """Create a dropdown item with separate display and insertion values.

            Args:
                main: The display text/Content (shown in the dropdown).
                insertion_value: The text that gets inserted on completion.
                prefix: Optional prefix displayed to the left.
            """
            super().__init__(main=main, prefix=prefix, id=id, disabled=disabled)
            self._insertion_value = insertion_value

        @property
        def value(self) -> str:
            """Return the insertion value (not the display text)."""
            return self._insertion_value

    class FunctualizeAutoComplete(AutoComplete):
        """AutoComplete subclass tailored for functualize's SmartBar.

        Key differences from the base AutoComplete:
        - Shows dropdown when candidates exist, even with an empty search string
        - Skips the library's built-in fuzzy re-filtering (SmartBarAutoComplete
          already pre-filters candidates contextually)
        - Delegates get_search_string and get_candidates to the SmartBarAutoComplete
          instance for context-aware behavior
        - Applies context-aware completion insertion (replaces only the partial
          being completed, not the full input text)
        """

        def __init__(
            self,
            target: Any,
            completer: SmartBarAutoComplete,
            *,
            prevent_default_enter: bool = True,
            prevent_default_tab: bool = True,
            name: str | None = None,
            id: str | None = None,
            classes: str | None = None,
            disabled: bool = False,
        ) -> None:
            """Initialize with a reference to the SmartBarAutoComplete logic.

            Args:
                target: The Input widget to attach to.
                completer: The SmartBarAutoComplete instance that provides
                    context-aware candidates and search strings.
                prevent_default_enter: Prevent Enter from submitting the Input.
                prevent_default_tab: Prevent Tab from moving focus.
            """
            super().__init__(
                target,
                candidates=None,  # We override get_candidates
                prevent_default_enter=prevent_default_enter,
                prevent_default_tab=prevent_default_tab,
                name=name,
                id=id,
                classes=classes,
                disabled=disabled,
            )
            self._completer = completer
            self._insert_choices: list[str] | None = None
            self._suppressed: bool = False

        def enter_insert_mode(self, choices: list[str] | None) -> None:
            """Switch candidate source to field-specific choices for INSERT mode.

            Args:
                choices: List of valid values for the field (enum members, etc.).
                         Pass empty list to suppress normal completions with no dropdown.
                         Pass None to keep normal completions (not recommended in INSERT).
            """
            self._insert_choices = choices if choices is not None else []
            # Hide current dropdown and refresh
            self.action_hide()

        def exit_insert_mode(self) -> None:
            """Restore candidate source back to normal command/flag completions."""
            self._insert_choices = None
            # Hide the dropdown immediately
            self.action_hide()

        def suppress(self) -> None:
            """Fully suppress the autocomplete — hide dropdown and ignore all events.

            Used when the SmartBar is repurposed for non-command input (e.g. FILTER mode)
            so the autocomplete doesn't intercept keys or show candidates.
            """
            self._suppressed = True
            self.action_hide()

        def unsuppress(self) -> None:
            """Re-enable autocomplete after suppression."""
            self._suppressed = False

        def refresh_dropdown(self) -> None:
            """Rebuild options against the current target state and show/hide as needed.

            Public wrapper around the base library's private
            ``_handle_target_update()`` — callers outside this module (e.g.
            app.py) should use this instead of reaching into that private
            method directly.
            """
            self._handle_target_update()

        def accept_highlighted(self) -> None:
            """Apply the currently highlighted dropdown option, if any.

            Public wrapper around the base library's private ``_complete()``
            — callers outside this module should use this instead of
            calling ``_complete()`` directly. No-op if the dropdown is
            hidden or has no options.
            """
            if not self.display or self.option_list.option_count == 0:
                return
            highlighted = self.option_list.highlighted or 0
            self._complete(option_index=highlighted)

        def _listen_to_messages(self, event: Any) -> None:
            """Override to short-circuit when suppressed."""
            if self._suppressed:
                return
            super()._listen_to_messages(event)

        def get_search_string(self, target_state: TargetState) -> str:
            """Delegate to SmartBarAutoComplete for context-aware search string.

            In INSERT mode, the entire input text is the search string.
            In COMMAND mode, returns the partial text for CLI context.
            """
            if self._insert_choices is not None:
                return target_state.text
            return self._completer.get_search_string(target_state)

        def get_candidates(self, target_state: TargetState) -> list[DropdownItem]:
            """Delegate to SmartBarAutoComplete for context-aware candidates.

            SmartBarAutoComplete already filters and scores candidates based
            on cursor context (command mode, flag mode, value mode, etc.).
            When in INSERT mode (field editing), returns field-specific choices.
            """
            # If insert mode choices are active, use those instead
            if self._insert_choices is not None:
                search = target_state.text.lower()
                return [
                    DropdownItem(main=c)
                    for c in self._insert_choices
                    if search in c.lower()
                ]
            return self._completer.get_candidates(target_state)  # type: ignore[return-value]

        def get_matches(
            self,
            target_state: TargetState,
            candidates: list[DropdownItem],
            search_string: str,
        ) -> list[DropdownItem]:
            """Return candidates as-is without additional fuzzy filtering.

            SmartBarAutoComplete already performed contextual filtering and
            scoring. We skip fuzzy re-filtering and highlighting since:
            - Candidates are already pre-filtered and sorted by relevance
            - The display text format (name + badge + description) doesn't
              map cleanly to fuzzy match offsets
            """
            return candidates

        def should_show_dropdown(self, search_string: str) -> bool:
            """Show dropdown when candidates exist and user has interacted.

            Rules:
            - In INSERT mode: always show if there are matching choices
            - In COMMAND mode: don't show on empty input (initial state)
            - Show when candidates exist for the current context
            """
            option_list = self.option_list
            option_count = option_list.option_count

            if option_count == 0:
                return False

            # In INSERT mode, always show choices unless input is an exact match
            if self._insert_choices is not None:
                # Hide if input exactly matches a choice (nothing more to suggest)
                return search_string not in self._insert_choices

            # Don't show dropdown on completely empty input (initial state)
            target_state = self._get_target_state()
            if not target_state.text.strip():
                return False

            # If there's exactly one candidate matching the search string exactly,
            # don't show the dropdown (nothing to complete).
            if option_count == 1 and search_string:
                from rich.text import Text

                first_option = option_list.get_option_at_index(0).prompt
                text_from_option = (
                    first_option.plain
                    if isinstance(first_option, Text)
                    else first_option
                )
                if text_from_option == search_string:
                    return False

            return True

        def apply_completion(self, value: str, state: TargetState) -> None:
            """Context-aware insertion: replace only the partial being completed.

            In INSERT mode: replaces the entire input with the selected choice.
            In COMMAND mode: replaces only the portion of the input that
            corresponds to the current partial (as determined by cursor context).
            """
            # INSERT mode: simple full replacement
            if self._insert_choices is not None:
                target = self.target
                target.value = value
                target.cursor_position = len(value)
                return

            from functualize._cli.completions.cursor_context import parse_cursor_context
            from functualize._cli.completions.quote_handling import quote_for_insertion

            target = self.target
            text = state.text
            cursor_pos = state.cursor_position

            # Parse the cursor context to find where the partial starts
            try:
                ctx = parse_cursor_context(
                    text,
                    cursor_pos,
                    self._completer._cached_job_names,
                    positional_params=self._completer._cached_positional_params,
                )
            except Exception as exc:
                self.log.warning(
                    f"apply_completion: parse_cursor_context failed "
                    f"({type(exc).__name__}): {exc}"
                )
                # Fallback to base behavior if parsing fails
                target.value = ""
                target.insert_text_at_cursor(value)
                return

            partial = ctx.partial
            quoted_value = quote_for_insertion(value)

            # Calculate the start position of the partial in the text
            # The partial is at cursor_pos - len(partial) to cursor_pos
            partial_start = cursor_pos - len(partial)

            # Build the new text: everything before partial + completion + trailing space + everything after cursor
            new_text = text[:partial_start] + quoted_value + " " + text[cursor_pos:]

            # Set the new text and position cursor after the trailing space.
            # NOTE: Textual's Input.value setter posts Input.Changed, but the
            # parent class's _complete() wraps this in self.prevent(Input.Changed),
            # so the message is suppressed here. Re-posting happens in
            # post_completion() which runs after the prevent context exits.
            target.value = new_text
            new_cursor = partial_start + len(quoted_value) + 1
            target.cursor_position = new_cursor

            # Rebuild options after completion
            new_target_state = self._get_target_state()
            self._rebuild_options(
                new_target_state, self.get_search_string(new_target_state)
            )

        def post_completion(self) -> None:
            """After completion, re-post Input.Changed so the app re-evaluates readiness.

            The parent class's _complete() wraps apply_completion() in
            `self.prevent(Input.Changed)`, which suppresses the Changed message
            that Textual's Input.value setter would normally post. We explicitly
            re-post it here (outside the prevent context) so on_input_changed fires.
            """
            from textual.widgets import Input

            super().post_completion()
            target = self.target
            target.post_message(Input.Changed(target, target.value))

except ImportError:
    # textual-autocomplete not installed — degrade to an invisible no-op
    # widget. It must be a real Widget: app.compose() yields it, and a
    # plain object there crashes every mount with a MountError.
    from textual.widget import Widget as _Widget

    class _EmptyOptionList:
        """Stands in for the dropdown's option list (always empty)."""

        option_count = 0

    class FunctualizeAutoComplete(_Widget):  # type: ignore[no-redef]
        """Placeholder when textual-autocomplete is not available.

        Mounts as a hidden widget and no-ops the autocomplete surface the
        TUI drives (suppress/insert-mode/refresh), so the app runs without
        completion instead of failing to start.
        """

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__()
            self.display = False
            self.option_list = _EmptyOptionList()

        def enter_insert_mode(self, choices: list[str] | None) -> None:
            """No-op placeholder — see the real implementation above."""

        def exit_insert_mode(self) -> None:
            """No-op placeholder — see the real implementation above."""

        def suppress(self) -> None:
            """No-op placeholder — see the real implementation above."""

        def unsuppress(self) -> None:
            """No-op placeholder — see the real implementation above."""

        def refresh_dropdown(self) -> None:
            """No-op placeholder — see the real implementation above."""

        def accept_highlighted(self) -> None:
            """No-op placeholder — see the real implementation above."""

        def action_hide(self) -> None:
            """No-op placeholder — see the real implementation above."""
