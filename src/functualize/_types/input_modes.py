"""Input modes — what the shell's input bar is currently doing.

The bar has exactly one job today: type a command. `!ls` (run a shell command)
and a future `?` (ask) are not variations on that job; they change what
completion offers, what "ready to submit" means, and where history is recorded.
Modelling them as *modes* keeps those three answers together instead of spread
across three `if text.startswith(...)` branches.

A mode is chosen by its **sigil** — the first character of the input. The
default mode's sigil is the empty string: it is the fallback for anything that
does not start with a registered sigil, and it is shell-inherent, so the shell
registers it itself rather than a plugin supplying it.

This module declares shape only. It lives in ``_types`` and imports nothing
internal; the public re-export is ``functualize.plugin``, beside ``Surface`` and
``CommandNode``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

__all__ = ["DEFAULT_SIGIL", "InputMode", "InputModeRegistry"]

#: The default (command) mode's sigil. Empty string = "matches anything that no
#: other sigil claimed", which is why it cannot collide with a real sigil.
DEFAULT_SIGIL = ""


@dataclass(frozen=True)
class InputMode:
    """One thing the input bar can be doing.

    Attributes:
        sigil: First character that selects this mode (``"!"``, ``"?"``), or
            :data:`DEFAULT_SIGIL` for the fallback command mode.
        name: Short identifier, used in logs and history namespacing.
        candidate_source: Returns completion candidates for ``(text, cursor)``.
            The text **excludes** the sigil, and the cursor offset is relative
            to that stripped text. Completion is cursor-sensitive in every mode
            — a command mode needs to know which token is being edited, a shell
            mode needs it for path completion — so it is part of the contract
            rather than something each mode smuggles in via instance state.
        is_ready: Readiness rule for the input FSM — may this be submitted?
        submit: Runs the input. Also receives text without the sigil.
        history_namespace: Where this mode's history is recorded. Distinct
            namespaces stop `!ls` from polluting job-argument history.
    """

    sigil: str
    name: str
    candidate_source: Callable[[str, int], list[Any]]
    is_ready: Callable[[str], bool]
    submit: Callable[[str], None]
    history_namespace: str

    def strip_sigil(self, text: str) -> str:
        """``text`` with this mode's sigil removed, if present."""
        if self.sigil and text.startswith(self.sigil):
            return text[len(self.sigil) :]
        return text


class InputModeRegistry:
    """Sigil -> mode. One default mode, any number of sigil modes.

    Registration is explicit and collision-checked: two modes claiming ``!``
    would make dispatch order decide behavior, which is exactly the kind of
    silent precedence the convergence exists to remove.
    """

    __slots__ = ("_modes",)

    def __init__(self) -> None:
        self._modes: dict[str, InputMode] = {}

    def register(self, mode: InputMode) -> None:
        """Add ``mode``.

        Raises:
            ValueError: another mode already claims this sigil, or the sigil is
                longer than one character (dispatch reads exactly one).
        """
        if len(mode.sigil) > 1:
            raise ValueError(
                f"sigil {mode.sigil!r} must be a single character "
                f"(or empty for the default mode)"
            )
        existing = self._modes.get(mode.sigil)
        if existing is not None:
            raise ValueError(
                f"sigil {mode.sigil!r} is already registered to "
                f"{existing.name!r}; cannot also register {mode.name!r}"
            )
        self._modes[mode.sigil] = mode

    def resolve(self, text: str) -> InputMode | None:
        """The mode that owns ``text``, by its first character.

        Falls back to the default mode. Returns None only when no default has
        been registered — a shell always registers one, so that is a
        programming error rather than a user-visible state.
        """
        if text:
            mode = self._modes.get(text[0])
            if mode is not None:
                return mode
        return self._modes.get(DEFAULT_SIGIL)

    @property
    def sigils(self) -> list[str]:
        """Registered sigils, default first."""
        return sorted(self._modes, key=lambda s: (s != DEFAULT_SIGIL, s))

    def get(self, sigil: str) -> InputMode | None:
        """The mode registered for ``sigil``, if any."""
        return self._modes.get(sigil)

    def __contains__(self, sigil: object) -> bool:
        return sigil in self._modes

    def __len__(self) -> int:
        return len(self._modes)
