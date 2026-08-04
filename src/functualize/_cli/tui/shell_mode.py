"""The `!` input mode — run a shell command from the bar.

`!ls -la` is not a job and not a builtin. It is the escape hatch that stops the
shell from being a worse terminal than the terminal it is running inside, and
it behaves like one: the command owns the real terminal while it runs, and its
own stdout is the output — nothing is captured, re-rendered, or summarised.

Three things this mode must get right, in descending order of how badly they
break if missed:

**One terminal owner.** Job and builtin execution are both gated by
:func:`_job_worker_running` and both run under ``exclusive=True``. A fresh
submit path is exactly where that guard gets forgotten, and the failure is a
shell command and a job writing over each other on the same terminal. Submitting
while a worker runs is refused here, the same way and with the same log line.

**A real terminal, or nothing.** EXCLUSIVE is the orchestrator's top rung and
its capability floor is a genuine TTY. Without one the command is refused with a
visible message rather than handed off to a terminal that does not exist.

Execution goes through the orchestrator's **handoff**, the same route a
``tty: TTY`` job takes: the shell exits, the command runs on the main thread
with the terminal genuinely released, and the shell relaunches. Not
``App.suspend()`` — Textual raises ``SuspendNotSupported`` in inline mode, so
that route (which the builtin path used, and which this mode originally copied)
reports every command as a failure. Found by running the real TUI, not by any
test; the builtin path now takes this route too.

**History is the kernel's ring, not the argument store.**
``_cli/data/argument_history.py`` is shaped per-job-per-field, which a flat list
of shell commands is not. ``StateStore.append_history`` is the right home.
"""

from __future__ import annotations

import logging
import shlex
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._cli.tui.app import FunctualizeInlineTUI
    from functualize.plugin import InputMode, InputModeRegistry

__all__ = [
    "ASK_SIGIL",
    "SHELL_SIGIL",
    "make_ask_mode",
    "make_shell_mode",
    "register_shell_mode",
]

#: The sigil that selects this mode.
SHELL_SIGIL = "!"

#: Reserved for a future ask/AI mode. Claimed now, built later — see
#: :func:`make_ask_mode`.
ASK_SIGIL = "?"

#: History namespace, so `!` commands stay distinguishable from job runs in the
#: same ring.
HISTORY_NAMESPACE = "shell"


def shell_candidates(text: str, cursor: int) -> list[Any]:
    """Completion for `!` — executables for the first token, paths after it.

    ``text`` has the sigil stripped and ``cursor`` is relative to that, per the
    :class:`InputMode` contract.
    """
    from functualize._cli.completions.engine import (
        executable_candidates,
        path_candidates,
    )
    from functualize._cli.tui.smart_bar_autocomplete import _make_dropdown_item

    head = text[:cursor]
    # A trailing space means the current token is a fresh, empty one.
    in_first_token = " " not in head.strip() and not head.endswith(" ")
    current = head.rsplit(" ", 1)[-1] if head else ""

    if in_first_token:
        raw = executable_candidates(current)
        badge = "PATH"
    else:
        raw = path_candidates(current)
        badge = "path"

    # `completions/engine.py`'s `DropdownItem` is a structural stand-in — it
    # documents itself as such. The mounted widget needs the *real*
    # `textual_autocomplete.DropdownItem`, and rendering a stand-in raises
    # `VisualError: unable to display 'DropdownItem' type`. Go through the same
    # factory the command mode uses so both modes hand the widget one type.
    return [
        _make_dropdown_item(item.main, prefix=badge, insertion_value=item.main)
        for item in raw
    ]


def make_shell_mode(app: FunctualizeInlineTUI) -> InputMode:
    """Build the `!` mode bound to ``app``."""
    from functualize.plugin import InputMode

    return InputMode(
        sigil=SHELL_SIGIL,
        name="shell",
        candidate_source=shell_candidates,
        # A bare `!` is not runnable; anything with a command after it is.
        is_ready=lambda text: bool(text.strip()),
        submit=lambda text: run_shell_command(app, text),
        history_namespace=HISTORY_NAMESPACE,
    )


def make_ask_mode() -> InputMode:
    """The reserved `?` mode — registered, deliberately not implemented.

    This is the "declared slot" from C1b.1. Registering it now does real work
    even though nothing runs: the sigil is **taken**, so a later mode cannot
    quietly claim it, `resolve("?x")` reports the reservation instead of
    silently treating the text as a command name, and the boot validator has a
    concrete reason to reject a job called `?x` today rather than breaking it
    when the ask mode eventually ships.

    Its behaviour raises rather than no-ops: a slot that silently did nothing
    would look like a working feature that ignores you.
    """
    from functualize.plugin import InputMode

    def _unbuilt(*args: object, **kwargs: object) -> Any:
        raise NotImplementedError("the '?' input mode is reserved but not implemented")

    return InputMode(
        sigil=ASK_SIGIL,
        name="ask",
        candidate_source=_unbuilt,
        is_ready=lambda text: False,
        submit=_unbuilt,
        history_namespace="ask",
    )


def register_shell_mode(app: FunctualizeInlineTUI, registry: InputModeRegistry) -> None:
    """Register the `!` and reserved `?` modes on ``registry``.

    Idempotent because the registry rejects a duplicate sigil by design, and a
    shell that re-registers on relaunch should not crash over it.
    """
    if SHELL_SIGIL not in registry:
        registry.register(make_shell_mode(app))
    if ASK_SIGIL not in registry:
        registry.register(make_ask_mode())


# ----------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------


def run_shell_command(app: FunctualizeInlineTUI, command: str) -> None:
    """Check the guards, then hand ``command`` to the orchestrator.

    Does not run anything itself: the actual execution happens in
    :func:`execute_shell_handoff`, after the shell has exited and released the
    terminal. Must be called from the app's own thread — ``request_handoff``
    calls ``App.exit()``.
    """
    from rich.markup import escape
    from textual.widgets import RichLog

    from functualize._cli.tui.job_execution import _job_worker_running

    command = command.strip()
    if not command:
        return

    output_log = app.query_one("#output-log", RichLog)
    output_log.add_class("visible")

    # Same guard as run_job/run_builtin. Two terminal owners is precisely what
    # the EXCLUSIVE contract exists to prevent.
    if _job_worker_running(app):
        app.log.warning(
            "run_shell_command: ignored trigger — a worker is already running"
        )
        output_log.write(
            "[bold yellow]! Busy — a command is already running[/bold yellow]"
        )
        return

    if not _terminal_available():
        # The capability floor. Refusing loudly beats suspending the TUI for a
        # child process that will never get a terminal.
        output_log.write(
            "[bold red]✗ `!` needs a real terminal "
            "(stdin and stdout must both be TTYs)[/bold red]"
        )
        output_log.write("─" * 40)
        return

    output_log.write(f"[bold green]▶ Running:[/bold green] {escape(command)}")

    # Hand off through the orchestrator's EXCLUSIVE branch — the same route a
    # `tty: TTY` job takes. The shell exits, the command runs on the main
    # thread with the terminal genuinely released, and the shell relaunches.
    #
    # **Not `app.suspend()`**: Textual raises `SuspendNotSupported` in inline
    # mode, so that route reports every `!` command as a failure. The builtin
    # path had the same defect and now takes this same route — surface
    # switching is the orchestrator's job, never `suspend()`.
    #
    # The sentinel is safe precisely because C1b.4 reserved it: no job, group,
    # or plugin namespace can be named `!`, so a first token of `!` cannot
    # collide with a real command.
    app.request_handoff([SHELL_SIGIL, command])


def execute_shell_handoff(app: Any, command: str) -> int:
    """Run a `!` command on the main thread, terminal already released.

    Called by the inline-TUI handoff loop, not from inside the shell — by this
    point the TUI has exited, so no suspension is needed and the child simply
    inherits the terminal.

    **Not** ``WiredShell``, which the task sketch named. ``_cli`` may not import
    ``_engine`` ("Peer layers are independent" — caught by ``lint-imports``,
    not by tests), and ``WiredShell`` has no public re-export. Widening the
    public API for this one call site would be the wrong trade, because none of
    what ``WiredShell`` adds applies here: with nothing captured there is no
    output to redact or tee, there is no job context for a perf timeline or
    lifecycle events, and no retry/watcher policy. What is actually needed is
    "hand this string to a shell and let it own the terminal" — which is
    :mod:`subprocess`. The one piece worth keeping is ``[shell] program``, so
    the invocation prefix is resolved the same way ``WiredShell`` resolves it.

    Returns the child's exit code. A non-zero exit is an ordinary result, not
    an error to surface: the child's own output *is* the surfacing — that is
    what EXCLUSIVE buys (contracts §6).
    """
    import subprocess

    argv = [*_shell_invocation(_resolved_shell_program()), command]
    code = subprocess.call(argv)  # noqa: S603
    _record_history_quietly(command, code)
    return code


def _resolved_shell_program() -> str | None:
    """`[shell] program`, read outside the TUI (the handoff has no app.log)."""
    try:
        from functualize._cli.data.func_settings import FuncSettingsStore

        value = FuncSettingsStore.discover().effective_values().get("shell.program")
    except (OSError, ValueError, AttributeError):
        return None
    return str(value) if value else None


def _shell_invocation(program: str | None) -> list[str]:
    """The raw-shell invocation prefix for ``program``.

    Mirrors ``_engine.capabilities.shell._shell_invocation``: the command flag
    is inferred from the binary name (``-Command`` for pwsh/powershell, ``/c``
    for cmd, ``-c`` otherwise). Duplicated rather than imported because of the
    layer rule above; it is six lines of platform trivia, and a divergence
    would show up as `!` using a different shell than a job's `sh(...)`.
    """
    import os

    if not program:
        return ["cmd.exe", "/c"] if os.name == "nt" else ["/bin/sh", "-c"]
    base = os.path.basename(program).lower()
    if base in ("pwsh", "pwsh.exe", "powershell", "powershell.exe"):
        return [program, "-Command"]
    if base in ("cmd", "cmd.exe"):
        return [program, "/c"]
    return [program, "-c"]


def _terminal_available() -> bool:
    """Whether EXCLUSIVE can actually be granted here.

    ``isatty()`` raises ``ValueError`` on a closed stream and ``AttributeError``
    when a stream has been replaced by something that is not file-like (pytest
    capture, some embedding hosts). Both mean the same thing here — there is no
    terminal to hand over — so they answer False rather than propagate.
    """
    import sys

    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def _record_history_quietly(command: str, code: int) -> None:
    """Append the run to the kernel state store's history ring.

    Best-effort and silent: history is a convenience, and a store that cannot
    be written must not turn a successful command into visible noise on the
    terminal the user is watching.
    """
    from pathlib import Path

    from functualize.app.utils import StateStore

    try:
        store = StateStore.for_project(Path.cwd())
        store.append_history(
            {
                "namespace": HISTORY_NAMESPACE,
                "command": command,
                "argv": shlex.split(command),
                "exit_code": code,
            }
        )
    except (OSError, ValueError, KeyError) as exc:
        # Narrow, and logged rather than swallowed: history is a convenience,
        # so a store that cannot be written must not turn a successful command
        # into a visible failure — but it must still be discoverable.
        logging.getLogger(__name__).warning(
            "shell mode: could not record history (%s: %s)", type(exc).__name__, exc
        )
