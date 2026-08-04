"""FakeShell — a test double for the ``Shell`` capability (proposal §B.7).

Records calls, answers from a pattern→result table, and fails loudly on
unexpected commands, so jobs that shell out can be unit-tested without spawning
processes::

    fake = FakeShell({
        "git rev-parse HEAD": ShellResult(0, "abc123\\n", "", "git rev-parse HEAD", 1.0),
        re.compile(r"docker build .*"): ShellResult(0, "", "", "docker build", 1.0),
    })
    run_job(deploy, shell=fake)
    assert fake.calls[0].argv[:2] == ["docker", "build"]
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any

from functualize._types.redaction import reveal
from functualize._types.shell import ShellError, ShellResult


@dataclass(frozen=True)
class FakeShellCall:
    """A recorded ``FakeShell`` invocation.

    Attributes:
        argv: The resolved argument vector (list form, or the split display).
        command: The display string the command resolved to.
        kwargs: The keyword options passed to the call.
    """

    argv: list[str]
    command: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class FakeShell:
    """A scripted, recording stand-in for the ``Shell`` capability.

    Args:
        mapping: Maps an exact command string or a compiled regex to the
            ``ShellResult`` to return. The command's display form is matched
            against string keys by equality and against regex keys by
            ``search``.
    """

    def __init__(self, mapping: dict[Any, ShellResult] | None = None) -> None:
        self._mapping: dict[Any, ShellResult] = dict(mapping or {})
        self.calls: list[FakeShellCall] = []

    def __call__(
        self,
        command: list[str] | str,
        *,
        check: bool = True,
        **kwargs: Any,
    ) -> ShellResult:
        """Resolve, record, and answer a command from the mapping.

        Raises:
            AssertionError: If no mapping entry matches (loud on unexpected).
        """
        argv, display = self._resolve(command)
        self.calls.append(FakeShellCall(argv=argv, command=display, kwargs=kwargs))

        result = self._lookup(display)
        if result is None:
            raise AssertionError(
                f"FakeShell received an unexpected command: {display!r}. "
                f"Known commands: {[self._key_repr(k) for k in self._mapping]}"
            )
        if check and result.returncode != 0:
            raise ShellError(result)
        return result

    def sudo(self, command: list[str], **kwargs: Any) -> ShellResult:
        """Record a ``sudo``-prefixed call and answer it from the mapping.

        Mirrors :meth:`WiredShell.sudo` for testability: the recorded command is
        ``sudo <command>`` (no ``-S``/password machinery — a fake never spawns a
        real sudo). ``preserve_env``/``password``/``watchers`` are accepted and
        ignored. Match ``sudo <command>`` in the mapping like any other command.
        """
        if not isinstance(command, (list, tuple)):
            raise ValueError("FakeShell.sudo requires the list command form.")
        for sudo_only in ("preserve_env", "password", "watchers"):
            kwargs.pop(sudo_only, None)
        return self(["sudo", *command], **kwargs)

    def _resolve(self, command: list[str] | str) -> tuple[list[str], str]:
        """Resolve a command to ``(argv, display)`` for matching and recording."""
        if isinstance(command, (list, tuple)):
            argv = [reveal(a) for a in command]
            return argv, shlex.join(argv)
        text = str(command)
        try:
            argv = shlex.split(text)
        except ValueError:
            argv = [text]
        return argv, text

    def _lookup(self, display: str) -> ShellResult | None:
        for key, result in self._mapping.items():
            if isinstance(key, re.Pattern):
                if key.search(display):
                    return result
            elif key == display:
                return result
        return None

    @staticmethod
    def _key_repr(key: Any) -> str:
        return key.pattern if isinstance(key, re.Pattern) else str(key)
