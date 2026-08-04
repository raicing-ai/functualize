"""Ask, or fail so the caller can act — never hang (Merge B: T-S6b-4 + T45).

``sh.sudo`` with no configured password and a job with an unresolved required
config field are the same problem: a value is missing at the moment it is
needed. They get the same two answers, from one seam, so the two features
cannot drift into disagreeing about what "non-interactive" means.

The non-interactive half carries the weight. A prompt written to a pipe, to CI,
or to an MCP session **hangs** — nothing there can answer, and the process
waits forever holding whatever it started. So the refusal is typed and names
the two facts a caller needs: which field, and which environment variable sets
it. An error naming a variable that does not actually resolve would be worse
than no error, which is why `env_var_for` mirrors the resolution chain's own
convention rather than guessing.
"""

from __future__ import annotations

import pytest

from functualize._engine.missing_value import (
    MissingValueError,
    env_var_for,
    resolve_missing_value,
)
from functualize._types.interactivity import (
    InputNotAvailable,
    PromptIntent,
    PromptResponse,
)


class _Collector:
    """A surface that answers, recording what it was asked."""

    def __init__(self, answer: str = "typed") -> None:
        self.answer = answer
        self.requests: list[object] = []

    def collect(self, request: object) -> PromptResponse:
        self.requests.append(request)
        return PromptResponse(value=self.answer)


class _RefusingCollector:
    """A surface that cannot collect — the non-interactive case."""

    def collect(self, request: object) -> PromptResponse:
        raise InputNotAvailable("no tty")


def _prompt(collector: object):
    from functualize._engine.capabilities.prompt import Prompt

    return Prompt(_provider=collector)


class TestEnvVarNaming:
    def test_a_section_and_field_become_the_documented_variable(self) -> None:
        assert env_var_for("shell", "sudo_password") == "SHELL_SUDO_PASSWORD"

    def test_hyphens_and_dots_flatten(self) -> None:
        """Env vars cannot contain either, and the chain flattens them — so the
        name in the error must flatten identically or it will not work."""
        assert env_var_for("deploy.web", "api-key") == "DEPLOY_WEB_API_KEY"

    def test_no_section_is_just_the_field(self) -> None:
        assert env_var_for("", "token") == "TOKEN"


class TestInteractive:
    def test_a_value_is_collected_when_a_surface_can_answer(self) -> None:
        collector = _Collector("s3cr3t")

        value = resolve_missing_value(
            _prompt(collector), field="pw", env_var="PW", secret=True
        )

        assert value == "s3cr3t"

    def test_a_secret_is_requested_with_the_masking_intent(self) -> None:
        """SECRET_INPUT is what tells a surface to mask the field; asking for a
        password as plain text would echo it to the screen."""
        collector = _Collector()

        resolve_missing_value(_prompt(collector), field="pw", env_var="PW", secret=True)

        assert collector.requests[0].intent is PromptIntent.SECRET_INPUT

    def test_a_non_secret_uses_plain_text_intent(self) -> None:
        collector = _Collector()

        resolve_missing_value(_prompt(collector), field="city", env_var="CITY")

        assert collector.requests[0].intent is PromptIntent.TEXT_INPUT

    def test_an_empty_answer_is_still_missing(self) -> None:
        """Pressing enter did not supply the value, so proceeding would fail
        later and further from the cause."""
        with pytest.raises(MissingValueError):
            resolve_missing_value(_prompt(_Collector("")), field="pw", env_var="PW")


class TestNonInteractive:
    def test_no_prompt_at_all_raises_the_typed_error(self) -> None:
        with pytest.raises(MissingValueError) as excinfo:
            resolve_missing_value(
                None, field="[shell] sudo_password", env_var="SHELL_SUDO_PASSWORD"
            )

        assert excinfo.value.field == "[shell] sudo_password"
        assert excinfo.value.env_var == "SHELL_SUDO_PASSWORD"

    def test_a_refusing_surface_raises_the_typed_error_not_the_capability_one(
        self,
    ) -> None:
        """`InputNotAvailable` tells the caller nothing actionable; the typed
        error names the field and the variable that fixes it."""
        with pytest.raises(MissingValueError) as excinfo:
            resolve_missing_value(
                _prompt(_RefusingCollector()), field="pw", env_var="PW"
            )

        assert excinfo.value.env_var == "PW"

    def test_the_message_tells_you_how_to_fix_it(self) -> None:
        """A CI failure should be self-service: the message names the env var,
        the config file, and the interactive option."""
        with pytest.raises(MissingValueError) as excinfo:
            resolve_missing_value(None, field="token", env_var="APP_TOKEN")

        message = str(excinfo.value)
        assert "APP_TOKEN" in message
        assert "config" in message.lower()
