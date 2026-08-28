"""Command execution orchestration for the inline TUI.

Parses SmartBar tokens into kwargs, launches the job as a Textual thread
worker, and runs it in-process through FunctualizeApp.execute(), routing
the job's log output into the TUI's output panel and recording a config
snapshot on completion.

``run_job`` is the single entry point for both kinds of command the bar
accepts. Builtin `func` commands (cache, config, domains, scaffold,
version, show-info) are Click commands that are never registered as jobs,
so they route to ``run_builtin`` and are invoked through Click instead of
``FunctualizeApp.execute()``.

The synchronous ``FunctualizeApp.execute()`` call runs on a background
thread (``run_worker(fn, thread=True)``) rather than directly inside an
async worker coroutine, so the app's event loop keeps processing timers,
input, and rendering while a job is running. Any UI mutation triggered
from that thread (``RichLog.write`` inside ``_TuiLogHandler.emit``) must
be marshaled back onto the loop thread via ``app.call_from_thread(...)``.
"""

# WARNING: cross-thread contract — any future edit that writes to
# the UI from execute_job_sync/_TuiLogHandler.emit without going through
# call_from_thread (when off the loop thread) reintroduces the original
# freeze bug silently: no exception, just a frozen UI during execution.
# the failure mode has no test/exception signal outside a
# dedicated responsiveness test (see tests/_cli/test_job_execution_thread_worker.py) —
# easy to reintroduce without noticing.

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from textual.widgets import RichLog, Static

from functualize._cli.tui.thread_marshal import needs_marshal

if TYPE_CHECKING:
    from collections.abc import Generator

    from functualize._cli.data.pending_execution import PendingExecution
    from functualize._cli.tui.app import FunctualizeInlineTUI

#: Worker name used for the job-execution thread worker; also used by the
#: re-entry guard to detect an already-running execution.
_JOB_WORKER_NAME = "cmd-exec"


def _needs_marshal(app: FunctualizeInlineTUI) -> bool:
    """Return True if a UI write from the current thread must go through
    ``app.call_from_thread(...)`` instead of writing directly.

    Thin alias for the shared predicate in ``thread_marshal`` — kept as a
    module-level name because this module's cross-thread contract (and the
    warning above) is written in terms of it.
    """
    return needs_marshal(app)


@contextlib.contextmanager
def _panel_live_zone(app: FunctualizeInlineTUI, job_name: str) -> Generator[None]:
    """Push the PANEL live zone for the duration of a job run.

    Makes ``active_live_zone`` resolve to the TUI's own region, so a
    ``live: Live`` job renders into the output panel instead of degrading to
    a no-op. Pushed (not registered) so it is scoped to this run and wins
    top-of-stack; popped and closed in ``finally`` so a crashing job still
    unwinds before the shell resumes.

    Degrades to a plain no-op when the live-zone widget isn't available (a
    unit test constructing the TUI without a full DOM) — a job must never
    fail because its optional live surface could not be mounted.
    """
    zone = None
    try:
        from functualize._cli.tui.panel_live_zone import PanelLiveZone

        widget = app.query_one("#live-zone", Static)
        zone = PanelLiveZone(app, widget)
        # Pre-mount plugin-provided ambient constructs before the body runs,
        # so a flow-viz tree (say) is already there for the first event.
        zone.adopt_ambient(app._func_app, app._func_app.get_job(job_name))
        app._func_app.push_surface(zone)
    except Exception as exc:
        app.log.warning(
            f"_panel_live_zone: live zone unavailable, `live:` will degrade "
            f"({type(exc).__name__}): {exc}"
        )
        zone = None

    try:
        yield
    finally:
        if zone is not None:
            app._func_app.pop_surface(zone)
            zone.close()


class _TuiLogHandler(logging.Handler):
    """Routes log records to the TUI output panel.

    ``emit`` may be called from the job's worker thread (the common case,
    since jobs run via a thread worker) or from the app's own event-loop
    thread. Writing to a Textual widget from a thread other than the loop
    thread is unsafe, so this branches on thread identity: on-loop writes
    go directly to the widget; off-loop writes are marshaled through
    ``app.call_from_thread(...)``.
    """

    def __init__(self, app: FunctualizeInlineTUI, log_widget: RichLog) -> None:
        super().__init__()
        self._app = app
        self._log_widget = log_widget

    def emit(self, record: logging.LogRecord) -> None:
        # This handler must never raise — a broken log write should not
        # take down job execution, so the outer catch stays broad here.
        try:
            msg = self.format(record)
            if _needs_marshal(self._app):
                self._app.call_from_thread(self._log_widget.write, msg)
            else:
                self._log_widget.write(msg)
        except Exception:
            pass


#: Signatures of the failure a job hits when it starts a terminal UI on the
#: worker thread — Textual/curses install signal handlers, which CPython only
#: permits on the main thread. The raw traceback names neither the job nor the
#: fix, so it is translated below.
_MAIN_THREAD_MARKERS = (
    "signal only works in main thread",
    "set_wakeup_fd only works in main thread",
    "main thread of the main interpreter",
)


def _translate_error(exc: Exception) -> str:
    """Render a job error, naming the fix for known-cryptic failure classes.

    A job that grabs Textual/curses without declaring ``tty: TTY`` fails deep
    inside signal-handler setup on the worker thread. The message points at
    Python internals rather than at the missing declaration, so it is
    rewritten into the actionable form.
    """
    text = str(exc)
    if isinstance(exc, (ValueError, RuntimeError)) and any(
        marker in text.lower() for marker in _MAIN_THREAD_MARKERS
    ):
        return (
            "This job appears to start a terminal UI but does not declare "
            "`tty: TTY` in its signature. Add it so the shell hands the "
            f"terminal over instead of running the job on a worker thread. "
            f"(original error: {text})"
        )
    return text


def extract_effective_values(
    pending: PendingExecution | None,
    job_name: str,
    kwargs: dict[str, str],
) -> dict[str, Any]:
    """Extract effective config values for snapshot recording.

    Uses PendingExecution.all_effective() if pending exists for this job,
    otherwise falls back to the kwargs dict.

    Group options are recorded alongside the job's own fields, under their
    **group-prefixed** key (``deploy.env``). The snapshot is a flat dict of
    what this run used, and what a group contributed is part of that: a run
    where `--env prod` was set is not the same run as one where it was not,
    and a diff that cannot see the difference would call them identical. The
    prefix is what keeps a group's `env` from colliding with a job's own.

    Args:
        pending: The current PendingExecution, if any.
        job_name: The job being executed.
        kwargs: The kwargs passed to execution.

    Returns:
        A dict mapping field names to their effective values.
    """
    if pending is not None and pending.job_name == job_name:
        # all_effective() returns dict[str, tuple[value, source]]
        values: dict[str, Any] = {
            k: v for k, (v, _src) in pending.all_effective().items()
        }
        for name, value in pending.group_option_values.items():
            group = pending.group_option_paths.get(name)
            values[f"{group}.{name}" if group else name] = value
        return values
    return dict(kwargs)


def execute_job_sync(
    app: FunctualizeInlineTUI,
    job_name: str,
    kwargs: dict[str, str],
    group_option_values: dict[str, Any] | None = None,
) -> int:
    """Run a job in-process through the FunctualizeApp execution API.

    Captures output via a logging handler attached to the job logger and
    writes results to the RichLog widget. This is the synchronous body
    executed on the thread worker started by ``run_job``; all UI writes
    it triggers are marshaled by ``_TuiLogHandler.emit``.
    """
    output_log = app.query_one("#output-log", RichLog)

    # Attach handler to capture rc.log() output
    job_logger = logging.getLogger(f"functualize.job.{job_name}")
    parent_logger = logging.getLogger("functualize.job")
    tui_handler = _TuiLogHandler(app, output_log)
    tui_handler.setLevel(logging.DEBUG)
    job_logger.addHandler(tui_handler)
    parent_logger.addHandler(tui_handler)

    previous_level = job_logger.level
    previous_parent_level = parent_logger.level
    previous_propagate = job_logger.propagate
    job_logger.setLevel(logging.DEBUG)
    job_logger.propagate = False
    parent_logger.setLevel(logging.DEBUG)

    def _write(msg: str) -> None:
        if _needs_marshal(app):
            app.call_from_thread(output_log.write, msg)
        else:
            output_log.write(msg)

    # Widened at the boundary: these become *job* arguments, whose parameters
    # are arbitrarily typed. `dict[str, str]` describes what the token parser
    # produced, not what `execute` receives.
    job_kwargs: dict[str, Any] = dict(kwargs)

    try:
        with _panel_live_zone(app, job_name):
            result = app._func_app.execute(
                job_name,
                group_option_values=group_option_values or None,
                **job_kwargs,
            )
    except Exception as e:
        # `execute()` is not meant to raise — it reports a failed run by
        # *returning* a FAILURE result — but a genuine bug or a BaseException
        # subclass can still surface here. Treat it as the failure it is.
        _write(f"[bold red]✗ Error: {_translate_error(e)}[/bold red]")
        _write("─" * 40)
        effective_values = extract_effective_values(app._pending, job_name, kwargs)
        app._snapshot_store.record(job_name, effective_values, "failure")
        app._snapshot_store.flush()
        return 1
    finally:
        job_logger.removeHandler(tui_handler)
        parent_logger.removeHandler(tui_handler)
        job_logger.setLevel(previous_level)
        job_logger.propagate = previous_propagate
        parent_logger.setLevel(previous_parent_level)

    # Branch on the run's *status*, not on whether it raised. A missing-config
    # error and a raised job body come back as a FAILURE `JobResult`, not an
    # exception — so a panel that only caught exceptions printed "✓ Done" for a
    # run the engine recorded as a failure. That is precisely the split a user
    # sees between this panel and `func builtin history`, which reads the same
    # status. SKIPPED/BLOCKED are not failures (a blocked workflow did what it
    # was asked and is resumable), matching `func builtin parallel`'s rule.
    from functualize.app.utils import RunStatus, exit_code_for_status

    status = getattr(result, "status", None)
    if status in (RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED):
        _write("[bold green]✓ Done[/bold green]")
        _write("─" * 40)
        outcome = "success"
        return_code = 0
    else:
        exc = getattr(result, "exception", None)
        detail = _translate_error(exc) if exc is not None else str(status)
        _write(f"[bold red]✗ Failed: {detail}[/bold red]")
        _write("─" * 40)
        outcome = "failure"
        return_code = int(exit_code_for_status(status)) if status is not None else 1

    effective_values = extract_effective_values(app._pending, job_name, kwargs)
    app._snapshot_store.record(job_name, effective_values, outcome)
    app._snapshot_store.flush()
    return return_code


def _build_builtin_cli() -> Any:
    """Build a Click command exposing only the builtin `func` commands.

    The builtins are click commands, never entries in the job registry, so
    they cannot be run through ``FunctualizeApp.execute()``. Widening the
    kernel to know about CLI builtins would put a delivery concern in the
    kernel (see .spec/CONSTITUTION.md: "No delivery surface lives in the
    kernel"), so the TUI invokes them through Click instead — the same
    surface ``func`` itself uses for Mode.BUILTIN.
    """
    import click

    from functualize._cli.builtins import register_builtin_commands

    cli_group = click.Group(name="func")
    register_builtin_commands(cli_group)
    return cli_group


def _builtin_context_obj(app: FunctualizeInlineTUI) -> dict[str, Any]:
    """Build the Click context object the builtins expect.

    One copy of this fact lives in ``app.commands.builtin_context_obj``, which
    the tree's nodes use to execute themselves; this is the in-panel path
    borrowing it.
    """
    from functualize.app.commands import builtin_context_obj

    return builtin_context_obj(app._func_app)


def invoke_builtin(app: FunctualizeInlineTUI, tokens: list[str]) -> tuple[int, str]:
    """Invoke a builtin command, returning ``(exit_code, output)``.

    The **in-panel** path, and now the only one: output is always captured and
    written into the TUI's output log. A builtin that owns the terminal never
    comes through here — it hands off to the orchestrator and runs via its
    ``CommandNode``, which is what removed the ``capture=False`` variant.
    """
    import io
    from contextlib import redirect_stderr, redirect_stdout

    import click

    command = _build_builtin_cli()
    obj = _builtin_context_obj(app)
    buffer = io.StringIO()

    def _run() -> int:
        # standalone_mode=False keeps Click from calling sys.exit() out from
        # under the TUI; it returns the value instead and re-raises the
        # exceptions handled below.
        result = command.main(
            args=tokens, prog_name="func", standalone_mode=False, obj=obj
        )
        return int(result) if isinstance(result, int) else 0

    code = 0
    try:
        with redirect_stdout(buffer), redirect_stderr(buffer):
            code = _run()
    except SystemExit as exc:
        # Several builtins raise SystemExit directly (e.g. config edit).
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except click.exceptions.Exit as exc:
        code = exc.exit_code
    except click.exceptions.Abort:
        code = 1
    except click.ClickException as exc:
        # Usage errors (e.g. a missing required subcommand) land here.
        with redirect_stdout(buffer), redirect_stderr(buffer):
            exc.show()
        code = exc.exit_code

    return code, buffer.getvalue()


def execute_builtin_sync(app: FunctualizeInlineTUI, tokens: list[str]) -> int:
    """Run a builtin command and route its output into the TUI output panel.

    This is the thread-worker body, mirroring :func:`execute_job_sync`. No
    config snapshot is recorded: a builtin is not a job, and it has no
    resolved config fields to snapshot.
    """
    from rich.markup import escape

    output_log = app.query_one("#output-log", RichLog)

    def _write(msg: str) -> None:
        if _needs_marshal(app):
            app.call_from_thread(output_log.write, msg)
        else:
            output_log.write(msg)

    try:
        code, output = invoke_builtin(app, tokens)
    except Exception as e:
        _write(f"[bold red]✗ Error: {escape(str(e))}[/bold red]")
        _write("─" * 40)
        return 1

    for line in output.splitlines():
        # The output log has markup enabled; builtin output is plain text
        # and may legitimately contain square brackets (TOML lists, section
        # headers), so it must be escaped rather than interpreted.
        _write(escape(line))

    if code == 0:
        _write("[bold green]✓ Done[/bold green]")
    else:
        _write(f"[bold red]✗ Exited with code {code}[/bold red]")
    _write("─" * 40)
    return code


def run_builtin(app: FunctualizeInlineTUI, tokens: list[str]) -> None:
    """Run a builtin `func` command from the TUI.

    Commands that take over the terminal (``config edit`` spawns $EDITOR) step
    the shell aside through the orchestrator, because they need the real
    terminal and would otherwise fight the TUI for it. Everything else runs on
    the same thread worker jobs use, so the event loop stays responsive.
    """
    if _job_worker_running(app):
        app.log.warning("run_builtin: ignored trigger — a worker is already running")
        return

    output_log = app.query_one("#output-log", RichLog)
    output_log.add_class("visible")
    output_log.write(f"[bold green]▶ Running:[/bold green] func {' '.join(tokens)}")
    output_log.write("─" * 40)

    if _node_needs_terminal(app, tokens):
        _run_builtin_handoff(app, tokens)
        return

    app.run_worker(
        lambda: execute_builtin_sync(app, tokens),
        name=_JOB_WORKER_NAME,
        exclusive=True,
        thread=True,
    )


def _node_needs_terminal(app: FunctualizeInlineTUI, tokens: list[str]) -> bool:
    """Does running ``tokens`` take over the controlling terminal?

    Asks the resolved :class:`~functualize.plugin.CommandNode`, which is where
    that fact is declared — ``requires_tty`` for a job, ``config edit``'s
    ``terminal_subcommands`` collapsed to a per-node bool for a builtin. Reading
    it here rather than re-deriving it from ``BuiltinCommand`` keeps one answer
    for both kinds of command, which is what stops builtins needing their own
    notion of "owns the terminal".
    """
    from functualize.app.commands import build_command_tree, resolve_command_path

    try:
        node, _remaining = resolve_command_path(
            build_command_tree(app._func_app), tokens
        )
    except Exception as exc:  # pragma: no cover - defensive; tree build is I/O
        app.log.warning(f"_node_needs_terminal: tree resolution failed: {exc}")
        return False
    return bool(node is not None and node.needs_terminal)


def _run_builtin_handoff(app: FunctualizeInlineTUI, tokens: list[str]) -> None:
    """Step the shell aside for a command that owns the terminal.

    **Not** ``App.suspend()``, which this path used until now: Textual raises
    ``SuspendNotSupported`` in inline mode, so ``func builtin config edit`` from
    inside the shell reported a failure instead of opening an editor. Switching
    between surfaces — inline TUI, fullscreen TUI, direct stdout — is the
    orchestrator's job, and this is the same EXCLUSIVE route a ``tty: TTY`` job
    and a `!` shell command already take.

    Must be called from the app's own thread — ``request_handoff`` calls
    ``App.exit()``.
    """
    app.request_handoff(tokens)


async def execute_job_async(
    app: FunctualizeInlineTUI, job_name: str, kwargs: dict[str, str]
) -> int:
    """Async-compatible wrapper around :func:`execute_job_sync`.

    Kept for callers that still expect an awaitable (and for direct unit
    testing of the execution body outside a thread worker); ``run_job``
    itself no longer schedules this as an async worker.
    """
    return execute_job_sync(app, job_name, kwargs)


def _job_worker_running(app: FunctualizeInlineTUI) -> bool:
    """Return True if a job-execution worker is already active. re-entry guard: checks ``app.workers`` for a running
    worker in the ``_JOB_WORKER_NAME`` group so a second execute trigger
    while a job is in flight is ignored rather than queued or started
    concurrently.
    """
    return any(
        worker.name == _JOB_WORKER_NAME and worker.is_running for worker in app.workers
    )


def run_job(app: FunctualizeInlineTUI, tokens: list[str]) -> None:
    """Execute a job from parsed tokens and display output in the RichLog.

    Runs the job's synchronous execution body on a thread worker
    (``run_worker(fn, thread=True)``) so the app's event loop stays
    responsive for the job's entire duration. If a job
    worker is already running, the trigger is ignored.

    Args:
        app: The owning TUI app instance.
        tokens: Split command tokens, first element is the job name.
    """
    if not tokens:
        return

    # A node that is not a registered job — today the reserved ``builtin``
    # subtree — cannot go through FunctualizeApp.execute() and has no fields to
    # parse. Ask the one command tree rather than a hardcoded name set, so this
    # keeps working for any provider's nodes.
    if _is_non_job_command(app, tokens[0]):
        run_builtin(app, tokens)
        return

    if _job_worker_running(app):
        app.log.warning("run_job: ignored trigger — a job worker is already running")
        return

    # Resolve the space-separated path (S6b): `deploy web run`, one segment per
    # token, the same walk the CLI performs — group flags are consumed mid-path
    # on the way. The dotted spelling is refused: the shell navigates by spaces.
    resolution = app.resolve_command(tokens)
    output_log = app.query_one("#output-log", RichLog)
    if resolution.dotted_token is not None:
        output_log.add_class("visible")
        output_log.write(
            f"[bold red]Error:[/bold red] '{resolution.dotted_token}' — navigate "
            f"groups with spaces, e.g. "
            f"[bold]{resolution.dotted_token.replace('.', ' ')}[/bold]."
        )
        return
    if resolution.bad_flag is not None:
        output_log.add_class("visible")
        output_log.write(
            f"[bold red]Error:[/bold red] unknown option "
            f"'{resolution.bad_flag}' before a command."
        )
        return
    job_name = resolution.job_name
    if job_name is None:
        output_log.add_class("visible")
        output_log.write(
            f"[bold red]Error:[/bold red] '{' '.join(tokens)}' is not a runnable "
            f"command."
        )
        return

    # EXCLUSIVE handoff: a job that owns the terminal (declares tty: TTY) cannot
    # run on the TUI worker thread — Textual/curses need the main thread. Step
    # the shell aside; the orchestrator runs it after the terminal is released,
    # then relaunches the shell. Read from the cached descriptor flag.
    descriptor = app._func_app.get_job(job_name)
    if descriptor is not None and getattr(descriptor, "requires_tty", False):
        app.request_handoff(tokens)
        return

    # Surface-resolution ladder (surface-architecture §2): a job resolved to
    # STDOUT — by a job hint or the ``tui.default_surface = "stdout"`` setting —
    # renders to the real terminal scrollback, not the panel. Hand off like
    # EXCLUSIVE, but non-exclusive: the shell steps aside, runs the job to
    # stdout, then relaunches. PANEL (the framework default in the TUI) falls
    # through to the in-panel worker below.
    from functualize._cli.orchestrator import RenderSurface, resolve_surface

    surface = resolve_surface(
        requires_tty=False,
        hint=getattr(descriptor, "surface_hint", None),
        setting=app.resolved_default_surface(),
        framework_default=RenderSurface.PANEL,
    )
    if surface is RenderSurface.STDOUT:
        app.request_handoff(tokens)
        return

    # After the command, position makes every flag the job's own (D-d) — the
    # group's were already consumed mid-path by the walk above.
    job_kwargs = app.job_kwargs_for(job_name, resolution.args)
    group_values = resolution.group_values

    # Record invocation history for each provided argument (job + group).
    try:
        from functualize._cli.data.argument_history import ArgumentHistory

        history = ArgumentHistory.load()
        for field_name, value in {**job_kwargs, **group_values}.items():
            if value:
                history.record(job_name, field_name, value)
        history.flush()
    except Exception as exc:
        # Argument-invocation history recording is a best-effort, optional
        # feature (not a query_one lookup); log and continue without it
        # rather than failing the job trigger.
        app.log.warning(
            f"run_job: failed to record argument history for "
            f"{job_name!r} ({type(exc).__name__}): {exc}"
        )

    output_log.add_class("visible")
    output_log.write(f"[bold green]▶ Running:[/bold green] func {' '.join(tokens)}")
    output_log.write("─" * 40)

    app.run_worker(
        lambda: execute_job_sync(app, job_name, job_kwargs, group_values),
        name=_JOB_WORKER_NAME,
        exclusive=True,
        thread=True,
    )


def _is_non_job_command(app: FunctualizeInlineTUI, name: str) -> bool:
    """True when ``name`` is a top-level command tree node that is not a job.

    Replaces the reserved-name membership test: the tree knows which provider a
    node came from, so nothing here has to be told the reserved name.
    """
    try:
        from functualize.app.commands import ClickCommandProvider

        return any(
            node.name == name for node in ClickCommandProvider(app._func_app).nodes()
        )
    except Exception as exc:  # pragma: no cover - defensive
        app.log.warning(f"_is_non_job_command failed: {exc}")
        return False
