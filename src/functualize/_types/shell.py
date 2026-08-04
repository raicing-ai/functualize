"""Shell capability vocabulary — protocol, result, and error (proposal Part B).

The ``Shell`` protocol is what job authors annotate (``sh: Shell``); the engine
injects a concrete implementation per invocation
(``_engine/capabilities/shell.py``). ``ShellResult`` and ``ShellError`` are the
shared value/error types. Placed in ``_types`` (stdlib-only) so every layer —
and the public ``functualize.job`` / ``functualize.testing`` re-exports — share
one definition.

Signature note (direct-to-final build): options land across S2 tasks; only
implemented parameters appear here at each stage boundary — no forward-looking
no-op parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import re
    from collections.abc import Callable, Mapping, Sequence

    from functualize._types.job_declaration import Retry


@dataclass(frozen=True)
class Responder:
    """Answers an interactive prompt in a command's live output (§B.4).

    When ``pattern`` (a regex) appears in new output, ``response`` is written to
    the child's stdin. Use for scripted interactions — a tool asking
    ``Continue? [y/N]``, a password prompt, etc. ``response`` should include its
    own trailing newline if the program expects Enter.

    Attributes:
        pattern: Regex searched against live output (str or compiled pattern).
        response: Text written to stdin on each new match.
    """

    pattern: str | re.Pattern[str]
    response: str


@dataclass(frozen=True)
class FailingResponder(Responder):
    """A :class:`Responder` that also aborts on a failure sentinel (§B.4).

    Responds like :class:`Responder`, but if ``sentinel`` appears in the output
    the command is killed and a :class:`ShellError` is raised. This is how a
    ``sudo`` password responder aborts on ``Sorry, try again`` instead of
    answering the re-prompt forever.

    Subclasses :class:`Responder` so it is accepted anywhere ``watchers`` are.

    Attributes:
        pattern: Regex whose match triggers ``response`` (inherited).
        response: Text written to stdin on each new ``pattern`` match (inherited).
        sentinel: Regex whose appearance aborts the command.
    """

    sentinel: str | re.Pattern[str]


@dataclass(frozen=True)
class ShellResult:
    """The outcome of a single shell command (proposal §B.2).

    Attributes:
        returncode: Process exit code.
        stdout: Captured standard output (empty string when not captured).
        stderr: Captured standard error (empty string when not captured).
        command: Display form of the command (secrets masked — §B.6).
        duration_ms: Wall-clock duration in milliseconds.
        pid: The child process id (or None if it never started).
    """

    returncode: int
    stdout: str
    stderr: str
    command: str
    duration_ms: float
    pid: int | None = None

    @property
    def ok(self) -> bool:
        """True when the command exited zero."""
        return self.returncode == 0


class ShellError(Exception):
    """Raised when a command exits non-zero under ``check=True`` (§B.2).

    Carries the full :class:`ShellResult` so callers can inspect output.

    Attributes:
        result: The ShellResult for the failed command.
    """

    def __init__(self, result: ShellResult) -> None:
        self.result = result
        super().__init__(f"Command failed (exit {result.returncode}): {result.command}")


@runtime_checkable
class Shell(Protocol):
    """DI-injectable shell-command capability (proposal Part B).

    Three command forms (§B.1), in order of preference:

    - **list** — ``sh(["docker", "build", "-t", tag, "."])`` — no shell, no
      quoting problem. The documented default idiom.
    - **template** — ``sh("docker build -t {tag} .", tag=version)`` — each
      substituted value is ``shlex.quote``-d before interpolation, then run
      without a shell.
    - **raw** — ``sh("a | b", shell=True)`` — explicit shell interpretation;
      the caller owns quoting.

    A raw string with neither ``shell=True`` nor template params is an error
    (never a silent ``shlex.split``) — that ambiguity is where injection bugs
    live.
    """

    def __call__(
        self,
        command: list[str] | str,
        *,
        capture: bool = True,
        stream: Callable[[str], None] | bool | None = None,
        check: bool = True,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        replace_env: bool = False,
        in_stream: str | None = None,
        timeout: float | None = None,
        retry: Retry | None = None,
        shell: bool = False,
        pty: bool = False,
        watchers: Sequence[Responder] | None = None,
        background: bool = False,
        label: str | None = None,
        silent: bool = False,
        **template_params: Any,
    ) -> ShellResult:
        """Run ``command`` and return a :class:`ShellResult`.

        ``stream=True`` routes live output to the **surface's** channel —
        stdout when piped, the panel in the TUI (§C.1); a callable is an
        explicit sink. ``silent=True`` suppresses the command echo, which is
        otherwise written to the surface's *diagnostic* channel (stderr when
        piped) so it can never corrupt piped data.

        ``pty`` allocates a pseudo-terminal (POSIX; degrades to pipes on
        Windows) so programs that check ``isatty()`` behave interactively.
        ``watchers`` are :class:`Responder`/:class:`FailingResponder` objects
        that answer prompts in the live output by writing to stdin.

        Raises:
            ShellError: If the command exits non-zero and ``check`` is True, on
                timeout (always), or when a :class:`FailingResponder` sentinel
                appears.
            ValueError: If a raw string is passed without ``shell=True`` or
                template params (ambiguous — see class docstring).
        """
        ...
