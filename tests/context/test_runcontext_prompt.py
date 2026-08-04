"""Unit tests for RunContext prompt methods.

Tests rc.prompt(), rc.prompt_confirm(), rc.prompt_choice(), rc.prompt_text()
including no-InputProvider handling, source_job auto-fill, and convenience method behavior.

Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.7, 4.8, 4.9
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from functualize._config.job_config import JobConfigView
from functualize._types.interactivity import (
    InputNotAvailable,
    PromptChoice,
    PromptIntent,
    PromptRequest,
    PromptResponse,
    PromptSeverity,
)
from functualize.job.context import RunContext

# --- Helpers ---


class FakeInputProvider:
    """A fake InputProvider that records calls and returns configured responses."""

    name: str = "fake-provider"

    def __init__(self, response: PromptResponse | None = None):
        self._response = response or PromptResponse(value="user_input", source="user")
        self.last_request: PromptRequest | None = None

    def collect(self, request: PromptRequest) -> PromptResponse:
        self.last_request = request
        return self._response


def _make_rc(
    name: str = "test-job",
    input_provider: FakeInputProvider | None = None,
) -> RunContext:
    """Create a RunContext with optional InputProvider wired up."""
    config = MagicMock(spec=JobConfigView)
    config.set_prefix = MagicMock()
    logger = MagicMock()

    # Build a mock app with _surfaces
    app = MagicMock()
    plugins: list = []
    if input_provider is not None:
        plugins.append(input_provider)
    app._surfaces = plugins

    # Build a mock execution engine referencing the app
    engine = MagicMock()
    engine._app = app

    rc = RunContext(
        name=name,
        config=config,
        logger=logger,
        _execution_engine=engine,
    )
    return rc


# --- Tests for rc.prompt() ---


class TestPrompt:
    """Tests for RunContext.prompt() method."""

    def test_auto_fills_source_job(self):
        """source_job is auto-filled from rc.name regardless of request value."""
        provider = FakeInputProvider()
        rc = _make_rc(name="my-job", input_provider=provider)

        request = PromptRequest(question="Hello?", source_job="other-job")
        rc.prompt(request)

        # Provider should receive the request with source_job overridden
        assert provider.last_request is not None
        assert provider.last_request.source_job == "my-job"

    def test_delegates_to_input_provider(self):
        """prompt() delegates to the active InputProvider."""
        expected = PromptResponse(value="confirmed", source="user")
        provider = FakeInputProvider(response=expected)
        rc = _make_rc(input_provider=provider)

        request = PromptRequest(question="Continue?")
        result = rc.prompt(request)

        assert result == expected

    def test_no_provider_required_no_default_raises(self):
        """No InputProvider + required=True + no default → InputNotAvailable."""
        rc = _make_rc(input_provider=None)

        request = PromptRequest(question="Input needed?", required=True, default=None)
        with pytest.raises(InputNotAvailable):
            rc.prompt(request)

    def test_no_provider_has_default_returns_default(self):
        """No InputProvider + has default → PromptResponse(value=default, source='default')."""
        rc = _make_rc(input_provider=None)

        request = PromptRequest(question="Input?", required=True, default="fallback")
        result = rc.prompt(request)

        assert result.value == "fallback"
        assert result.source == "default"

    def test_no_provider_not_required_returns_default(self):
        """No InputProvider + required=False → PromptResponse(value=default, source='default')."""
        rc = _make_rc(input_provider=None)

        request = PromptRequest(question="Optional?", required=False, default=None)
        result = rc.prompt(request)

        assert result.value is None
        assert result.source == "default"

    def test_no_engine_required_raises(self):
        """No execution engine + required=True + no default → InputNotAvailable."""
        config = MagicMock(spec=JobConfigView)
        config.set_prefix = MagicMock()
        logger = MagicMock()

        rc = RunContext(
            name="orphan-job",
            config=config,
            logger=logger,
            _execution_engine=None,
        )

        request = PromptRequest(question="Input?", required=True, default=None)
        with pytest.raises(InputNotAvailable):
            rc.prompt(request)

    def test_no_engine_has_default_returns_default(self):
        """No execution engine + has default → returns default response."""
        config = MagicMock(spec=JobConfigView)
        config.set_prefix = MagicMock()
        logger = MagicMock()

        rc = RunContext(
            name="orphan-job",
            config=config,
            logger=logger,
            _execution_engine=None,
        )

        request = PromptRequest(question="Input?", default="safe-fallback")
        result = rc.prompt(request)

        assert result.value == "safe-fallback"
        assert result.source == "default"


# --- Tests for the default stdin fallback (no interactivity plugin) ---


class TestStdinFallback:
    """RunContext.prompt() falls back to the kernel stdin collector at a TTY.

    _get_input_provider() imports get_stdin_collector lazily from
    functualize._engine.capabilities.stdin_collector, so patching it there
    patches the call site. A non-TTY (returns None) preserves the historical
    default / InputNotAvailable behavior.
    """

    def test_bare_app_at_tty_prompts_instead_of_raising(self, monkeypatch):
        """Zero surfaces + TTY fallback available → real answer."""
        from functualize._engine.capabilities import stdin_collector

        monkeypatch.setattr(
            stdin_collector,
            "get_stdin_collector",
            lambda: FakeInputProvider(PromptResponse(value="typed", source="user")),
        )
        rc = _make_rc(input_provider=None)

        # required + no default would have raised before the fallback existed.
        result = rc.prompt(PromptRequest(question="Name?", required=True, default=None))

        assert result.value == "typed"
        assert result.source == "user"

    def test_bare_app_non_tty_still_raises(self, monkeypatch):
        """Zero surfaces + non-TTY (None) → InputNotAvailable as before."""
        from functualize._engine.capabilities import stdin_collector

        monkeypatch.setattr(stdin_collector, "get_stdin_collector", lambda: None)
        rc = _make_rc(input_provider=None)

        with pytest.raises(InputNotAvailable):
            rc.prompt(PromptRequest(question="Name?", required=True, default=None))


# --- Tests for rc.prompt_confirm() ---


class TestPromptConfirm:
    """Tests for RunContext.prompt_confirm() convenience method."""

    def test_confirm_neutral_intent(self):
        """Non-destructive confirm uses CONFIRM_NEUTRAL intent."""
        provider = FakeInputProvider(PromptResponse(value=True, source="user"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_confirm("Proceed?")

        assert result is True
        assert provider.last_request is not None
        assert provider.last_request.intent == PromptIntent.CONFIRM_NEUTRAL
        assert provider.last_request.severity == PromptSeverity.INFO

    def test_confirm_destructive_intent(self):
        """destructive=True uses CONFIRM_DESTRUCTIVE intent with DANGER severity."""
        provider = FakeInputProvider(PromptResponse(value=True, source="user"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_confirm("Delete all?", destructive=True)

        assert result is True
        assert provider.last_request is not None
        assert provider.last_request.intent == PromptIntent.CONFIRM_DESTRUCTIVE
        assert provider.last_request.severity == PromptSeverity.DANGER

    def test_returns_false_on_cancelled(self):
        """Returns False when response source is 'cancelled'."""
        provider = FakeInputProvider(PromptResponse(value=None, source="cancelled"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_confirm("Continue?")

        assert result is False

    def test_returns_false_on_denied(self):
        """Returns False when user explicitly denies."""
        provider = FakeInputProvider(PromptResponse(value=False, source="user"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_confirm("Continue?")

        assert result is False

    def test_string_yes_returns_true(self):
        """Handles string 'yes' response as True."""
        provider = FakeInputProvider(PromptResponse(value="yes", source="user"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_confirm("Continue?")

        assert result is True

    def test_string_no_returns_false(self):
        """Handles string 'no' response as False."""
        provider = FakeInputProvider(PromptResponse(value="no", source="user"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_confirm("Continue?")

        assert result is False

    def test_passes_context_message_and_data(self):
        """context_message and context_data are forwarded to the request."""
        provider = FakeInputProvider(PromptResponse(value=True, source="user"))
        rc = _make_rc(input_provider=provider)

        rc.prompt_confirm(
            "Continue?",
            context_message="This is context",
            context_data={"key": "value"},
        )

        assert provider.last_request is not None
        assert provider.last_request.context_message == "This is context"
        assert provider.last_request.context_data == {"key": "value"}

    def test_default_value_passed_through(self):
        """Default value is passed to PromptRequest and used in no-provider fallback."""
        rc = _make_rc(input_provider=None)

        result = rc.prompt_confirm("Continue?", default=True)

        # With no provider and a default, should return the default interpreted as bool
        assert result is True


# --- Tests for rc.prompt_choice() ---


class TestPromptChoice:
    """Tests for RunContext.prompt_choice() convenience method."""

    def test_accepts_plain_strings(self):
        """Plain string choices are converted to PromptChoice objects."""
        provider = FakeInputProvider(PromptResponse(value="option-b", source="user"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_choice("Pick one:", ["option-a", "option-b", "option-c"])

        assert result == "option-b"
        assert provider.last_request is not None
        assert provider.last_request.intent == PromptIntent.SELECT
        assert provider.last_request.choices is not None
        assert len(provider.last_request.choices) == 3
        assert provider.last_request.choices[0].value == "option-a"

    def test_accepts_prompt_choice_objects(self):
        """PromptChoice objects are passed through directly."""
        choices = [
            PromptChoice(value="a", label="Option A"),
            PromptChoice(value="b", label="Option B"),
        ]
        provider = FakeInputProvider(PromptResponse(value="a", source="user"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_choice("Pick one:", choices)

        assert result == "a"
        assert provider.last_request is not None
        assert provider.last_request.choices == choices

    def test_returns_empty_string_on_none(self):
        """Returns empty string when response value is None."""
        provider = FakeInputProvider(PromptResponse(value=None, source="cancelled"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_choice("Pick one:", ["a", "b"])

        assert result == ""

    def test_passes_default_and_context_message(self):
        """Default and context_message are forwarded to the request."""
        provider = FakeInputProvider(PromptResponse(value="b", source="default"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_choice(
            "Pick one:", ["a", "b"], default="b", context_message="Choose wisely"
        )

        assert result == "b"
        assert provider.last_request is not None
        assert provider.last_request.default == "b"
        assert provider.last_request.context_message == "Choose wisely"


# --- Tests for rc.prompt_text() ---


class TestPromptText:
    """Tests for RunContext.prompt_text() convenience method."""

    def test_text_input_intent(self):
        """Non-secret text uses TEXT_INPUT intent."""
        provider = FakeInputProvider(PromptResponse(value="hello", source="user"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_text("Enter name:")

        assert result == "hello"
        assert provider.last_request is not None
        assert provider.last_request.intent == PromptIntent.TEXT_INPUT

    def test_secret_input_intent(self):
        """secret=True uses SECRET_INPUT intent."""
        provider = FakeInputProvider(PromptResponse(value="s3cret", source="user"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_text("Enter password:", secret=True)

        assert result == "s3cret"
        assert provider.last_request is not None
        assert provider.last_request.intent == PromptIntent.SECRET_INPUT

    def test_passes_placeholder_and_validator(self):
        """placeholder and validator are forwarded to the request."""
        provider = FakeInputProvider(
            PromptResponse(value="test@example.com", source="user")
        )
        rc = _make_rc(input_provider=provider)

        rc.prompt_text(
            "Email:", placeholder="you@example.com", validator=r"[^@]+@[^@]+\.[^@]+"
        )

        assert provider.last_request is not None
        assert provider.last_request.placeholder == "you@example.com"
        assert provider.last_request.validator == r"[^@]+@[^@]+\.[^@]+"

    def test_returns_empty_string_on_none(self):
        """Returns empty string when response value is None."""
        provider = FakeInputProvider(PromptResponse(value=None, source="cancelled"))
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_text("Name:")

        assert result == ""

    def test_default_and_context_message(self):
        """Default and context_message are forwarded."""
        provider = FakeInputProvider(
            PromptResponse(value="default-val", source="default")
        )
        rc = _make_rc(input_provider=provider)

        result = rc.prompt_text(
            "Name:", default="default-val", context_message="Provide a name"
        )

        assert result == "default-val"
        assert provider.last_request is not None
        assert provider.last_request.default == "default-val"
        assert provider.last_request.context_message == "Provide a name"

    def test_no_provider_with_default_returns_default(self):
        """No InputProvider + has default → returns default string."""
        rc = _make_rc(input_provider=None)

        result = rc.prompt_text("Name:", default="fallback")

        assert result == "fallback"
