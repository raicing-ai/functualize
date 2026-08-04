"""Ask for a value, or fail in a way the caller can act on (Merge B: T-S6b-4 + T45).

Two features need the identical decision and must not answer it twice:

* **T-S6b-4** — ``sh.sudo`` with no ``[shell] sudo_password`` configured.
* **T45** — a job whose required config field resolved to nothing.

Both are "a value is missing at the moment it is needed", and both have the
same two answers:

* **Interactive surface** → ask for it. Secret fields are collected masked.
* **Non-interactive** → a **typed error naming the field and its environment
  variable**, exit 2 (the T39 usage/config code).

The non-interactive half is the one worth being strict about. A prompt written
to a pipe, to CI, or to an MCP session is a **hang**: nothing is there to
answer it, so the process waits forever holding whatever it had already
started. Failing immediately with the two facts the caller needs — which field,
and which env var sets it — is the only outcome that lets a script recover.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize._engine.capabilities.prompt import Prompt

__all__ = ["MissingValueError", "env_var_for", "resolve_missing_value"]


class MissingValueError(Exception):
    """A required value was absent and could not be collected.

    Carries the field and env var rather than only a message so a caller
    (or a test) can act on the parts without parsing prose.
    """

    def __init__(self, field: str, env_var: str, *, hint: str = "") -> None:
        self.field = field
        self.env_var = env_var
        detail = f" {hint}" if hint else ""
        super().__init__(
            f"Missing required value {field!r}. "
            f"Set it with the {env_var} environment variable, in your config "
            f"file, or run interactively to be prompted.{detail}"
        )


def env_var_for(section: str, field: str) -> str:
    """The environment variable that sets ``section.field``.

    Mirrors the resolution chain's own convention (``SECTION_FIELD``, upper
    case, hyphens and dots flattened) so the name in the error is the name that
    actually works — an error naming a variable that does not resolve is worse
    than no error at all.
    """
    token = f"{section}_{field}" if section else field
    return token.upper().replace("-", "_").replace(".", "_")


def resolve_missing_value(
    prompt: Prompt | None,
    *,
    field: str,
    env_var: str,
    message: str | None = None,
    secret: bool = False,
) -> str:
    """Collect ``field`` interactively, or raise :class:`MissingValueError`.

    Args:
        prompt: The ``Prompt`` capability, or ``None`` when the job did not get
            one. A ``Prompt`` whose surface cannot collect counts as absent.
        field: The field being asked for, as the user names it.
        env_var: The environment variable that would set it.
        message: Override for the prompt text.
        secret: Collect masked, and never echo the value.

    Returns:
        The collected value.

    Raises:
        MissingValueError: When there is no interactive surface to ask.
    """
    if prompt is None:
        raise MissingValueError(field, env_var)

    from functualize._types.interactivity import (
        InputNotAvailable,
        PromptIntent,
        PromptRequest,
    )

    text = message or f"Enter {field}"
    # SECRET_INPUT is what tells a surface to mask the field — a masked
    # terminal read, a password widget in the TUI. Going through `ask` rather
    # than a convenience method is what makes that intent expressible.
    request = PromptRequest(
        question=text,
        intent=PromptIntent.SECRET_INPUT if secret else PromptIntent.TEXT_INPUT,
        required=True,
    )
    try:
        response = prompt.ask(request)
    except InputNotAvailable as exc:
        # The surface refused (no TTY, no registered collector). That is the
        # non-interactive answer, so it becomes the typed error rather than
        # propagating a capability-level exception the caller cannot act on.
        raise MissingValueError(field, env_var) from exc

    value = getattr(response, "value", response)
    if value is None or value == "":
        raise MissingValueError(field, env_var, hint="(no value entered)")
    return str(value)
