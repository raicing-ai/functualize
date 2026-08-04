"""Inline Textual TUI for bare `func` invocation.

Smart command shell with progressive disclosure:
- Header row with app name and command validity indicator
- Smart input bar for composing commands (autocomplete-style)
- Main output panel showing contextual help / completions / execution output

The smart bar acts like an intellisense-powered command line:
- Typing shows fuzzy-matched completions in the main panel
- Selecting a completion pastes it into the smart bar (not execute)
- Ctrl+R executes when the command is valid (bar turns green)
- Bar color indicates readiness: grey = incomplete, green = executable

This module is one of the files permitted to import textual at runtime.
It uses ONLY the public API (FunctualizeApp facade).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize.app.core import FunctualizeApp


# ─── Main entry point ────────────────────────────────────────────────────


def launch_inline_tui(app: FunctualizeApp) -> int:
    """Launch the inline TUI, driving the orchestrator handoff loop.

    Normally runs the shell once and returns its exit code. When the shell
    steps aside for a job that owns the terminal (``tty: TTY``), it returns a
    handoff request instead of exiting: the orchestrator runs that job on the
    main thread (the shell has released the terminal, so the job's Textual /
    curses UI works), refreshes the app in case the job mutated the project,
    then relaunches a fresh shell — until a plain exit.

    Args:
        app: The booted FunctualizeApp instance.

    Returns:
        Exit code (0 for clean exit, 1 for error).

    Raises:
        ImportError: If Textual is not installed (missing functualize[cli]).
    """
    try:
        from functualize._cli.tui.app import FunctualizeInlineTUI
    except ImportError as e:
        raise ImportError(
            "The TUI requires the [cli] extras group. "
            "Install with: pip install functualize[cli]"
        ) from e

    while True:
        tui = FunctualizeInlineTUI(app)
        _restore_session_state(app, tui)
        tui.run(inline=True)

        handoff = tui.handoff_tokens
        if not handoff:
            return tui.return_code or 0

        # Capture shell state before the relaunch. Persistent stores (argument
        # history, config snapshots) survive on their own because the
        # FunctualizeApp is reused; this carries the in-memory shell state that
        # would otherwise reset to blank on every handoff.
        _capture_session_state(app, tui)

        # The shell has exited and released the terminal. Run the job on THIS
        # (main) thread so its tty.run(app) succeeds, then loop back to a fresh
        # shell. app.refresh() picks up any project mutations the job made.
        _run_handoff(app, handoff)
        app.refresh()


def _capture_session_state(app: FunctualizeApp, tui: object) -> None:
    """Save shell state into ``app.extension_state["orchestrator"]``.

    Kept small and entirely optional: a handoff that fails to capture state
    must still run the job. Anything already persisted by a store belongs
    there, not here.
    """
    try:
        state = app.extension_state.setdefault("orchestrator", {})
        bar = getattr(tui, "_smart_bar", None)
        state["last_command"] = getattr(bar, "value", "") or ""
        panel_host = getattr(tui, "_panel_host", None)
        state["panel_index"] = getattr(panel_host, "current_index", 0)
        state["active_ring"] = getattr(tui, "_active_ring", None)
    except Exception:  # pragma: no cover - defensive; never block a handoff
        pass


def _restore_session_state(app: FunctualizeApp, tui: object) -> None:
    """Reapply captured shell state to a freshly relaunched TUI.

    Only the command line is restored eagerly; panel/ring position is left in
    ``extension_state`` for the TUI to consult once its DOM exists, since
    nothing is mounted at this point.
    """
    try:
        state = app.extension_state.get("orchestrator")
        if not state:
            return
        last_command = state.get("last_command") or ""
        if last_command:
            bar = getattr(tui, "_smart_bar", None)
            if bar is not None:
                bar.value = last_command
    except Exception:  # pragma: no cover - defensive; never block a relaunch
        pass


def _run_tree_node(app: FunctualizeApp, tokens: list[str]) -> bool:
    """Resolve ``tokens`` in the command tree and run the node. True if it ran.

    The terminal is already released at this point, so a node that owns it
    (``builtin config edit`` spawning $EDITOR) simply inherits it. Returns
    False when the path names nothing, leaving the caller's unknown-command
    handling to report it.
    """
    from functualize.app.commands import build_command_tree, resolve_command_path

    try:
        node, remaining = resolve_command_path(build_command_tree(app), tokens)
    except Exception as exc:  # pragma: no cover - defensive; tree build is I/O
        print(f"Error resolving '{' '.join(tokens)}': {exc}", file=sys.stderr)
        return False

    if node is None:
        return False

    try:
        node.execute(remaining)
    except Exception as exc:  # pragma: no cover - defensive; command errors surface
        print(f"Error running '{' '.join(tokens)}': {exc}", file=sys.stderr)
    return True


def _run_handoff(app: FunctualizeApp, tokens: list[str]) -> None:
    """Run a handoff command on the main thread, terminal released.

    Mirrors direct ``func <job> <args>`` execution: parse the tokens against the
    job's cached fields and execute via the app facade (which materializes the
    job). A soft terminal reset afterward keeps a job that exits dirty from
    poisoning the next shell.
    """
    import contextlib
    import logging
    from typing import Any

    from functualize._cli.tui.cli_arg_parser import (
        build_group_option_trie,
        parse_cli_args_to_kwargs,
        resolve_tui_command,
    )
    from functualize._cli.tui.shell_mode import SHELL_SIGIL, execute_shell_handoff

    if not tokens:
        return

    # A `!` handoff is a shell command, not anything in the command tree — the
    # sigil is an input *mode*, not a path. Unambiguous because C1b.4 reserves
    # it: no job, group, or plugin namespace may be named `!`.
    if tokens[0] == SHELL_SIGIL:
        execute_shell_handoff(app, tokens[1] if len(tokens) > 1 else "")
        sys.stdout.write("\033[?25h\033[0m")
        return

    # Walk the space-separated path (S6b), consuming group flags mid-path —
    # the same resolution the in-panel worker and the CLI perform.
    resolution = resolve_tui_command(build_group_option_trie(app), tokens)
    if resolution.dotted_token is not None:
        spaced = resolution.dotted_token.replace(".", " ")
        print(
            f"Error: '{resolution.dotted_token}' — navigate groups with spaces, "
            f"e.g. `{spaced}`.",
            file=sys.stderr,
        )
        sys.stdout.write("\033[?25h\033[0m")
        return

    job_name = resolution.job_name or tokens[0]
    descriptor = app.get_job(job_name)

    # Not a job the kernel can execute — so ask the one command tree and let
    # the node run itself. This is deliberately *not* a test for `builtin`:
    # `CommandNode` exists to erase that question (app/commands.py), and any
    # provider's nodes route here without this function changing.
    if descriptor is None and _run_tree_node(app, tokens):
        sys.stdout.write("\033[?25h\033[0m")
        return

    # After the command, position makes every flag the job's own (D-d); the
    # group's were consumed mid-path by the walk.
    fields = list(descriptor.config_fields) if descriptor is not None else []
    kwargs = parse_cli_args_to_kwargs(resolution.args, fields=fields)
    group_option_values = resolution.group_values

    requires_tty = bool(getattr(descriptor, "requires_tty", False))
    uses_live = bool(getattr(descriptor, "uses_live", False))

    # A STDOUT-resolved `live: Live` job needs a StdoutSurface pushed so its
    # live constructs bind to a live zone (mirrors the direct `func <job>`
    # path). A `tty: TTY` (EXCLUSIVE) job owns the terminal via tty.run and
    # must not get a competing surface, so gate on "live and not tty".
    live_ctx: Any = contextlib.nullcontext()
    if uses_live and not requires_tty:
        with contextlib.suppress(ImportError):
            from functualize.ui import stdout_live_session

            live_ctx = stdout_live_session(app)

    # The bare-`func` TTY path strips stdout/stderr log handlers so log lines
    # don't corrupt the inline TUI's line tracking (main._run). During a STDOUT
    # handoff the shell has stepped aside and we *want* the job's logs on the
    # terminal, so restore a stdout handler for the run. Not for EXCLUSIVE
    # (`tty: TTY`) jobs — they own the screen via tty.run.
    log_handler: logging.Handler | None = None
    if not requires_tty:
        log_handler = logging.StreamHandler(sys.stdout)
        log_handler.setFormatter(
            logging.Formatter("%(levelname)s:%(name)s:%(message)s")
        )
        job_logger = logging.getLogger("functualize.job")
        job_logger.addHandler(log_handler)
        if job_logger.level in (logging.NOTSET, 0) or job_logger.level > logging.INFO:
            job_logger.setLevel(logging.INFO)

    # See job_execution._run_job: job parameters are arbitrarily typed, so the
    # token parser's `dict[str, str]` is widened where it stops being tokens.
    job_kwargs: dict[str, Any] = dict(kwargs)

    try:
        with live_ctx:
            app.execute(
                job_name,
                group_option_values=group_option_values or None,
                **job_kwargs,
            )
    except Exception as exc:  # pragma: no cover - defensive; job errors surface
        print(f"Error running '{job_name}': {exc}", file=sys.stderr)
    finally:
        if log_handler is not None:
            logging.getLogger("functualize.job").removeHandler(log_handler)
        # Soft reset: show cursor + reset attributes (non-destructive).
        sys.stdout.write("\033[?25h\033[0m")
        sys.stdout.flush()
