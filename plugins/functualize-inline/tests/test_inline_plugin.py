"""Unit tests for functualize-inline plugin (a PromptCollector).

Tests:
1. Protocol compliance — InlinePlugin satisfies PromptCollector (not Surface)
2. Each PromptIntent's CLI fallback path (mocked input)
3. Cancel behavior (KeyboardInterrupt → source="cancelled")
4. Context message is printed when provided
5. Plain CLI path for CONFIRM_DESTRUCTIVE, CONFIRM_NEUTRAL, SELECT,
   SECRET_INPUT, ACKNOWLEDGE, TEXT_INPUT
6. Timeout behavior

Requirements: 28.3, 28.4
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from functualize_inline.plugin import InlinePlugin

from functualize._types.interactivity import (
    PromptChoice,
    PromptCollector,
    PromptIntent,
    PromptRequest,
    Surface,
)

# ─── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def plugin() -> InlinePlugin:
    """Create a fresh InlinePlugin instance."""
    return InlinePlugin()


def _make_request(
    intent: PromptIntent = PromptIntent.TEXT_INPUT,
    question: str = "Test question?",
    **kwargs,
) -> PromptRequest:
    """Helper to create PromptRequest with defaults."""
    return PromptRequest(question=question, intent=intent, **kwargs)


# ─── Protocol Compliance ──────────────────────────────────────────────


class TestProtocolCompliance:
    """Test that InlinePlugin satisfies PromptCollector (and not Surface)."""

    def test_satisfies_prompt_collector_protocol(self, plugin: InlinePlugin):
        """InlinePlugin passes isinstance check for PromptCollector."""
        assert isinstance(plugin, PromptCollector)

    def test_is_not_a_surface(self, plugin: InlinePlugin):
        """InlinePlugin asks for input; it does not render events."""
        assert not isinstance(plugin, Surface)

    def test_has_name_attribute(self, plugin: InlinePlugin):
        """InlinePlugin has the required name attribute."""
        assert hasattr(plugin, "name")
        assert plugin.name == "inline"

    def test_has_collect_method(self, plugin: InlinePlugin):
        """InlinePlugin has the required collect method."""
        assert hasattr(plugin, "collect")
        assert callable(plugin.collect)

    def test_callable_registers_with_app(self, plugin: InlinePlugin):
        """__call__ registers the plugin as a surface."""
        mock_app = MagicMock()
        plugin(mock_app)
        mock_app.register_surface.assert_called_once_with(plugin)


# ─── CLI Fallback: CONFIRM_DESTRUCTIVE ────────────────────────────────


class TestCliConfirmDestructive:
    """Test plain CLI fallback for CONFIRM_DESTRUCTIVE intent."""

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="yes")
    def test_confirm_destructive_yes(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Typing 'yes' returns value=True, source='user'."""
        request = _make_request(intent=PromptIntent.CONFIRM_DESTRUCTIVE)
        response = plugin.collect(request)
        assert response.value is True
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="YES")
    def test_confirm_destructive_yes_case_insensitive(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """'YES' (uppercase) is accepted as confirmation."""
        request = _make_request(intent=PromptIntent.CONFIRM_DESTRUCTIVE)
        response = plugin.collect(request)
        assert response.value is True
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="no")
    def test_confirm_destructive_no(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Typing anything other than 'yes' returns value=False."""
        request = _make_request(intent=PromptIntent.CONFIRM_DESTRUCTIVE)
        response = plugin.collect(request)
        assert response.value is False
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="")
    def test_confirm_destructive_empty(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Empty input returns value=False (not confirmed)."""
        request = _make_request(intent=PromptIntent.CONFIRM_DESTRUCTIVE)
        response = plugin.collect(request)
        assert response.value is False
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_confirm_destructive_cancel(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """KeyboardInterrupt returns source='cancelled'."""
        request = _make_request(intent=PromptIntent.CONFIRM_DESTRUCTIVE)
        response = plugin.collect(request)
        assert response.value is None
        assert response.source == "cancelled"


# ─── CLI Fallback: CONFIRM_NEUTRAL ────────────────────────────────────


class TestCliConfirmNeutral:
    """Test plain CLI fallback for CONFIRM_NEUTRAL intent."""

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="y")
    def test_confirm_neutral_yes(self, mock_input, mock_inline, plugin: InlinePlugin):
        """Typing 'y' returns value=True."""
        request = _make_request(intent=PromptIntent.CONFIRM_NEUTRAL)
        response = plugin.collect(request)
        assert response.value is True
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="n")
    def test_confirm_neutral_no(self, mock_input, mock_inline, plugin: InlinePlugin):
        """Typing 'n' returns value=False."""
        request = _make_request(intent=PromptIntent.CONFIRM_NEUTRAL)
        response = plugin.collect(request)
        assert response.value is False
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="")
    def test_confirm_neutral_empty_default_true(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Empty input with default=True returns True."""
        request = _make_request(intent=PromptIntent.CONFIRM_NEUTRAL, default=True)
        response = plugin.collect(request)
        assert response.value is True
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="")
    def test_confirm_neutral_empty_default_false(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Empty input with default=False returns False."""
        request = _make_request(intent=PromptIntent.CONFIRM_NEUTRAL, default=False)
        response = plugin.collect(request)
        assert response.value is False
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="")
    def test_confirm_neutral_empty_no_default(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Empty input with no default returns True (Y/n behavior)."""
        request = _make_request(intent=PromptIntent.CONFIRM_NEUTRAL)
        response = plugin.collect(request)
        assert response.value is True
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_confirm_neutral_cancel(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """KeyboardInterrupt returns source='cancelled'."""
        request = _make_request(intent=PromptIntent.CONFIRM_NEUTRAL)
        response = plugin.collect(request)
        assert response.value is None
        assert response.source == "cancelled"


# ─── CLI Fallback: SELECT ─────────────────────────────────────────────


class TestCliSelect:
    """Test plain CLI fallback for SELECT intent."""

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="1")
    def test_select_first_choice(self, mock_input, mock_inline, plugin: InlinePlugin):
        """Selecting '1' returns the first choice's value."""
        choices = [
            PromptChoice(value="alpha", label="Alpha"),
            PromptChoice(value="beta", label="Beta"),
        ]
        request = _make_request(intent=PromptIntent.SELECT, choices=choices)
        response = plugin.collect(request)
        assert response.value == "alpha"
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="2")
    def test_select_second_choice(self, mock_input, mock_inline, plugin: InlinePlugin):
        """Selecting '2' returns the second choice's value."""
        choices = [
            PromptChoice(value="alpha", label="Alpha"),
            PromptChoice(value="beta", label="Beta"),
        ]
        request = _make_request(intent=PromptIntent.SELECT, choices=choices)
        response = plugin.collect(request)
        assert response.value == "beta"
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="invalid")
    def test_select_invalid_returns_default(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Invalid input returns default value if available."""
        choices = [PromptChoice(value="alpha")]
        request = _make_request(
            intent=PromptIntent.SELECT, choices=choices, default="fallback"
        )
        response = plugin.collect(request)
        assert response.value == "fallback"
        assert response.source == "default"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="invalid")
    def test_select_invalid_no_default_returns_cancelled(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Invalid input without a default returns source='cancelled'."""
        choices = [PromptChoice(value="alpha")]
        request = _make_request(intent=PromptIntent.SELECT, choices=choices)
        response = plugin.collect(request)
        assert response.value is None
        assert response.source == "cancelled"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="1")
    def test_select_disabled_choice(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Selecting a disabled choice returns default value."""
        choices = [PromptChoice(value="alpha", disabled=True)]
        request = _make_request(
            intent=PromptIntent.SELECT, choices=choices, default="fallback"
        )
        response = plugin.collect(request)
        assert response.value == "fallback"
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_select_cancel(self, mock_input, mock_inline, plugin: InlinePlugin):
        """KeyboardInterrupt returns source='cancelled'."""
        choices = [PromptChoice(value="alpha")]
        request = _make_request(intent=PromptIntent.SELECT, choices=choices)
        response = plugin.collect(request)
        assert response.value is None
        assert response.source == "cancelled"


# ─── CLI Fallback: SECRET_INPUT ───────────────────────────────────────


class TestCliSecretInput:
    """Test plain CLI fallback for SECRET_INPUT intent."""

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("getpass.getpass", return_value="s3cr3t")
    def test_secret_input_returns_value(
        self, mock_getpass, mock_inline, plugin: InlinePlugin
    ):
        """Secret input returns the value entered via getpass."""
        request = _make_request(intent=PromptIntent.SECRET_INPUT)
        response = plugin.collect(request)
        assert response.value == "s3cr3t"
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("getpass.getpass", side_effect=KeyboardInterrupt)
    def test_secret_input_cancel(self, mock_getpass, mock_inline, plugin: InlinePlugin):
        """KeyboardInterrupt during getpass returns source='cancelled'."""
        request = _make_request(intent=PromptIntent.SECRET_INPUT)
        response = plugin.collect(request)
        assert response.value is None
        assert response.source == "cancelled"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("getpass.getpass", side_effect=EOFError)
    def test_secret_input_eof(self, mock_getpass, mock_inline, plugin: InlinePlugin):
        """EOFError during getpass returns source='cancelled'."""
        request = _make_request(intent=PromptIntent.SECRET_INPUT)
        response = plugin.collect(request)
        assert response.value is None
        assert response.source == "cancelled"


# ─── CLI Fallback: ACKNOWLEDGE ────────────────────────────────────────


class TestCliAcknowledge:
    """Test plain CLI fallback for ACKNOWLEDGE intent."""

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="")
    def test_acknowledge_returns_true(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Pressing Enter returns value=True, source='user'."""
        request = _make_request(intent=PromptIntent.ACKNOWLEDGE)
        response = plugin.collect(request)
        assert response.value is True
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_acknowledge_cancel(self, mock_input, mock_inline, plugin: InlinePlugin):
        """KeyboardInterrupt returns source='cancelled'."""
        request = _make_request(intent=PromptIntent.ACKNOWLEDGE)
        response = plugin.collect(request)
        assert response.value is None
        assert response.source == "cancelled"


# ─── CLI Fallback: TEXT_INPUT ─────────────────────────────────────────


class TestCliTextInput:
    """Test plain CLI fallback for TEXT_INPUT intent."""

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="hello world")
    def test_text_input_returns_value(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Text input returns the entered value."""
        request = _make_request(intent=PromptIntent.TEXT_INPUT)
        response = plugin.collect(request)
        assert response.value == "hello world"
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="")
    def test_text_input_empty_with_default(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Empty input with default returns default value, source='default'."""
        request = _make_request(intent=PromptIntent.TEXT_INPUT, default="fallback")
        response = plugin.collect(request)
        assert response.value == "fallback"
        assert response.source == "default"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="")
    def test_text_input_empty_no_default(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Empty input without default returns empty string."""
        request = _make_request(intent=PromptIntent.TEXT_INPUT)
        response = plugin.collect(request)
        assert response.value == ""
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_text_input_cancel(self, mock_input, mock_inline, plugin: InlinePlugin):
        """KeyboardInterrupt returns source='cancelled'."""
        request = _make_request(intent=PromptIntent.TEXT_INPUT)
        response = plugin.collect(request)
        assert response.value is None
        assert response.source == "cancelled"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", side_effect=EOFError)
    def test_text_input_eof(self, mock_input, mock_inline, plugin: InlinePlugin):
        """EOFError returns source='cancelled'."""
        request = _make_request(intent=PromptIntent.TEXT_INPUT)
        response = plugin.collect(request)
        assert response.value is None
        assert response.source == "cancelled"


# ─── Context Message Display ──────────────────────────────────────────


class TestContextMessage:
    """Test that context_message is printed when provided."""

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="yes")
    @patch("builtins.print")
    def test_context_message_printed_confirm_destructive(
        self, mock_print, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Context message is printed for CONFIRM_DESTRUCTIVE."""
        request = _make_request(
            intent=PromptIntent.CONFIRM_DESTRUCTIVE,
            context_message="This will delete everything!",
        )
        plugin.collect(request)
        mock_print.assert_called_with("  This will delete everything!")

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="y")
    @patch("builtins.print")
    def test_context_message_printed_confirm_neutral(
        self, mock_print, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Context message is printed for CONFIRM_NEUTRAL."""
        request = _make_request(
            intent=PromptIntent.CONFIRM_NEUTRAL,
            context_message="Please review carefully.",
        )
        plugin.collect(request)
        mock_print.assert_any_call("  Please review carefully.")

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="1")
    @patch("builtins.print")
    def test_context_message_printed_select(
        self, mock_print, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Context message is printed for SELECT."""
        choices = [PromptChoice(value="alpha")]
        request = _make_request(
            intent=PromptIntent.SELECT,
            choices=choices,
            context_message="Choose wisely.",
        )
        plugin.collect(request)
        mock_print.assert_any_call("  Choose wisely.")

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="hello")
    @patch("builtins.print")
    def test_context_message_printed_text_input(
        self, mock_print, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Context message is printed for TEXT_INPUT."""
        request = _make_request(
            intent=PromptIntent.TEXT_INPUT,
            context_message="Enter your name.",
        )
        plugin.collect(request)
        mock_print.assert_called_with("  Enter your name.")

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_context_message_printed_acknowledge(
        self, mock_print, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Context message is printed for ACKNOWLEDGE."""
        request = _make_request(
            intent=PromptIntent.ACKNOWLEDGE,
            context_message="Operation completed.",
        )
        plugin.collect(request)
        mock_print.assert_called_with("  Operation completed.")

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="hello")
    @patch("builtins.print")
    def test_no_context_message_when_none(
        self, mock_print, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """No print call for context_message when it is None."""
        request = _make_request(intent=PromptIntent.TEXT_INPUT, context_message=None)
        plugin.collect(request)
        # print should not have been called (no context_message, no choices to display)
        mock_print.assert_not_called()


# ─── Cancel and Timeout Behavior ──────────────────────────────────────


class TestCancelAndTimeout:
    """Test cancel (KeyboardInterrupt) and timeout behavior."""

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_all_intents_return_cancelled(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """KeyboardInterrupt for any intent returns source='cancelled'."""
        intents_to_test = [
            PromptIntent.CONFIRM_DESTRUCTIVE,
            PromptIntent.CONFIRM_NEUTRAL,
            PromptIntent.ACKNOWLEDGE,
            PromptIntent.TEXT_INPUT,
        ]
        for intent in intents_to_test:
            request = _make_request(intent=intent)
            response = plugin.collect(request)
            assert response.source == "cancelled", f"Failed for intent {intent}"
            assert response.value is None, f"Failed for intent {intent}"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", side_effect=EOFError)
    def test_eof_error_returns_cancelled(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """EOFError for any intent returns source='cancelled'."""
        intents_to_test = [
            PromptIntent.CONFIRM_DESTRUCTIVE,
            PromptIntent.CONFIRM_NEUTRAL,
            PromptIntent.ACKNOWLEDGE,
            PromptIntent.TEXT_INPUT,
        ]
        for intent in intents_to_test:
            request = _make_request(intent=intent)
            response = plugin.collect(request)
            assert response.source == "cancelled", f"Failed for intent {intent}"
            assert response.value is None, f"Failed for intent {intent}"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_select_cancel_via_keyboard_interrupt(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """SELECT intent with KeyboardInterrupt returns cancelled."""
        choices = [PromptChoice(value="a"), PromptChoice(value="b")]
        request = _make_request(intent=PromptIntent.SELECT, choices=choices)
        response = plugin.collect(request)
        assert response.source == "cancelled"
        assert response.value is None


# ─── MULTI_SELECT CLI Fallback ────────────────────────────────────────


class TestCliMultiSelect:
    """Test plain CLI fallback for MULTI_SELECT intent."""

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="1,2")
    def test_multi_select_multiple_choices(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Comma-separated selection returns list of values."""
        choices = [
            PromptChoice(value="alpha"),
            PromptChoice(value="beta"),
            PromptChoice(value="gamma"),
        ]
        request = _make_request(intent=PromptIntent.MULTI_SELECT, choices=choices)
        response = plugin.collect(request)
        assert response.value == ["alpha", "beta"]
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="1")
    def test_multi_select_single_choice(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Single number returns list with one value."""
        choices = [PromptChoice(value="alpha"), PromptChoice(value="beta")]
        request = _make_request(intent=PromptIntent.MULTI_SELECT, choices=choices)
        response = plugin.collect(request)
        assert response.value == ["alpha"]
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="1,2")
    def test_multi_select_skips_disabled(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Disabled choices are skipped in selection."""
        choices = [
            PromptChoice(value="alpha", disabled=True),
            PromptChoice(value="beta"),
        ]
        request = _make_request(intent=PromptIntent.MULTI_SELECT, choices=choices)
        response = plugin.collect(request)
        assert response.value == ["beta"]
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_multi_select_cancel(self, mock_input, mock_inline, plugin: InlinePlugin):
        """KeyboardInterrupt returns source='cancelled'."""
        choices = [PromptChoice(value="alpha")]
        request = _make_request(intent=PromptIntent.MULTI_SELECT, choices=choices)
        response = plugin.collect(request)
        assert response.source == "cancelled"
        assert response.value is None


# ─── Inline Path Fallback on Error ────────────────────────────────────


class TestInlinePathFallback:
    """Test that inline path errors fall back to CLI."""

    @patch("functualize_inline.plugin._is_inline_available", return_value=True)
    @patch("builtins.input", return_value="fallback value")
    def test_inline_failure_falls_back_to_cli(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """When Textual inline app raises, the plugin falls back to plain CLI."""
        request = _make_request(intent=PromptIntent.TEXT_INPUT)

        # Patch the InlinePromptApp to raise when instantiated/run
        with patch(
            "functualize_inline.apps.InlinePromptApp",
            side_effect=Exception("Textual crashed"),
        ):
            response = plugin.collect(request)
            assert response.value == "fallback value"
            assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="cli value")
    def test_non_tty_uses_cli_fallback(
        self, mock_input, mock_inline, plugin: InlinePlugin
    ):
        """Non-TTY environment uses CLI fallback path."""
        request = _make_request(intent=PromptIntent.TEXT_INPUT)
        response = plugin.collect(request)
        assert response.value == "cli value"
        assert response.source == "user"


# ─── CONFIRM_PROCEED (alias for CONFIRM_NEUTRAL) ─────────────────────


class TestCliConfirmProceed:
    """Test that CONFIRM_PROCEED uses the same path as CONFIRM_NEUTRAL."""

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="y")
    def test_confirm_proceed_yes(self, mock_input, mock_inline, plugin: InlinePlugin):
        """CONFIRM_PROCEED uses the same Y/n path as CONFIRM_NEUTRAL."""
        request = _make_request(intent=PromptIntent.CONFIRM_PROCEED)
        response = plugin.collect(request)
        assert response.value is True
        assert response.source == "user"

    @patch("functualize_inline.plugin._is_inline_available", return_value=False)
    @patch("builtins.input", return_value="n")
    def test_confirm_proceed_no(self, mock_input, mock_inline, plugin: InlinePlugin):
        """CONFIRM_PROCEED 'n' returns False."""
        request = _make_request(intent=PromptIntent.CONFIRM_PROCEED)
        response = plugin.collect(request)
        assert response.value is False
        assert response.source == "user"
