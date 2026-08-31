"""Shell capability implementation (proposal Part B).

``WiredShell`` is the engine-connected implementation of the ``Shell`` protocol
(``_types/shell.py``), injected per job invocation. It runs subprocesses via
``subprocess.Popen`` (never ``os.system``), with three command forms and
injection safety (§B.1).

Q4 (ratified 2026-07-20): the raw-shell program is ``/bin/sh`` on POSIX and
``pwsh`` (falling back to ``cmd``) on Windows; template-form quoting uses
``shlex`` on POSIX and subprocess argv rules on Windows.

Secret values (§B.6) are unwrapped at the trusted materialization points
(argv, env) and masked out of ``ShellResult.command`` via the shared
``_types.redaction`` utility. Interactive commands (``pty``, ``watchers``,
:meth:`WiredShell.sudo`) run through the chunk-reading interactive path so a
prompt without a trailing newline is answered rather than deadlocking.
``defer`` lands in S2/T14.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from functualize._engine.capabilities.spec import CapabilitySpec
from functualize._types.redaction import collect_secret_values, redact, reveal
from functualize._types.shell import (
    FailingResponder,
    Shell,
    ShellError,
    ShellResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from functualize._events.bus import EventBus
    from functualize._events.perf import PerfTimeline
    from functualize._types.job_declaration import Retry
    from functualize._types.redaction import Secret
    from functualize._types.shell import Responder


logger = logging.getLogger(__name__)


def _default_shell_program() -> list[str]:
    """The default raw-shell invocation prefix (Q4).

    POSIX → ``["/bin/sh", "-c"]``; Windows → ``["pwsh", "-Command"]`` when
    available, else ``["cmd", "/c"]``.
    """
    if sys.platform == "win32":
        if shutil.which("pwsh"):
            return ["pwsh", "-Command"]
        return ["cmd", "/c"]
    return ["/bin/sh", "-c"]


def _shell_invocation(program: str | None) -> list[str]:
    """Build the raw-shell invocation prefix for a configured ``program``.

    ``program`` is the shell binary (``[shell] program`` config). The
    command-flag is inferred: ``-Command`` for pwsh/powershell, ``/c`` for cmd,
    ``-c`` otherwise. ``None`` → the platform default (Q4).
    """
    if not program:
        return _default_shell_program()
    base = os.path.basename(program).lower()
    if base in ("pwsh", "pwsh.exe", "powershell", "powershell.exe"):
        return [program, "-Command"]
    if base in ("cmd", "cmd.exe"):
        return [program, "/c"]
    return [program, "-c"]


class WiredShell:
    """Engine-connected ``Shell`` implementation for one job invocation.

    Args:
        cwd: Default working directory for commands (the job's cwd). A per-call
            ``cwd=`` overrides it.
        program: The raw-shell binary from ``[shell] program`` config; ``None``
            uses the platform default (Q4).
        perf: The perf timeline; each call records a ``shell.<label>`` phase
            (§B.8). ``None`` disables perf recording.
        event_bus: The event bus; each call emits ``shell.command.start`` /
            ``shell.command.end`` lifecycle events (§B.8 — output chunks never
            go on the bus). ``None`` disables event emission.
        sudo_password: The password for :meth:`sudo` (``[shell] sudo_password``
            config, a ``secret=True`` field — §B.4). ``None`` requires an
            explicit ``password=`` to :meth:`sudo`.
    """

    def __init__(
        self,
        cwd: str | None = None,
        program: str | None = None,
        perf: PerfTimeline | None = None,
        event_bus: EventBus | None = None,
        sudo_password: Secret | str | None = None,
        echo_sink: Callable[[str], None] | None = None,
        output_sink: Callable[[str], None] | None = None,
        prompt: Any | None = None,
    ) -> None:
        self._cwd = cwd
        self._shell_program = _shell_invocation(program)
        self._perf = perf
        self._event_bus = event_bus
        self._sudo_password = sudo_password
        # Two *different* channels, bound by the engine at surface setup (S6b
        # T-S6b-3 / §C.1). Conflating them corrupts pipelines:
        #   echo_sink   — the command line being run. Diagnostic, like log(),
        #                 so on a piped surface it goes to **stderr**.
        #   output_sink — the command's live output under `stream=True`. Data,
        #                 so on a piped surface it goes to **stdout**.
        self._echo_sink = echo_sink
        self._output_sink = output_sink
        # Used only to ask for a sudo password that was never configured
        # (T-S6b-4). None on a non-interactive surface, which is the refusal.
        self._prompt = prompt
        # cd()/prefix() stacks are thread-local so a job that fans out across
        # threads does not leak context between them (§B.3).
        self._local = threading.local()
        # defer() registrations and background processes are per-invocation
        # (NOT thread-local): the engine unwinds them at job exit whichever
        # thread registered them (§B.5).
        self._deferred: list[tuple[list[str] | str, dict[str, Any]]] = []
        self._background: list[subprocess.Popen[Any]] = []

    @property
    def _cd_stack(self) -> list[str]:
        if not hasattr(self._local, "cd"):
            self._local.cd = []
        return self._local.cd  # type: ignore[no-any-return]

    @property
    def _prefix_stack(self) -> list[list[str]]:
        if not hasattr(self._local, "prefix"):
            self._local.prefix = []
        return self._local.prefix  # type: ignore[no-any-return]

    @contextmanager
    def cd(self, path: str) -> Iterator[None]:
        """Run commands in ``path`` for the duration of the block (§B.3).

        Nestable — a nested ``cd`` resolves relative to the enclosing one.
        Overridden by an explicit per-call ``cwd=``.
        """
        self._cd_stack.append(str(path))
        try:
            yield
        finally:
            self._cd_stack.pop()

    @contextmanager
    def prefix(self, command: list[str] | str) -> Iterator[None]:
        """Prepend ``command`` to every command in the block (§B.3).

        E.g. ``with sh.prefix(["poetry", "run"]): sh(["pytest"])`` runs
        ``poetry run pytest``. Nestable; outer prefixes apply before inner.
        """
        tokens = (
            list(command)
            if isinstance(command, (list, tuple))
            else shlex.split(command)
        )
        self._prefix_stack.append([str(t) for t in tokens])
        try:
            yield
        finally:
            self._prefix_stack.pop()

    def _effective_cwd(self, call_cwd: str | None) -> str | None:
        """Resolve the working directory: per-call ``cwd`` wins, else the cd
        stack joined over the instance default."""
        if call_cwd is not None:
            return call_cwd
        base = self._cwd
        for segment in self._cd_stack:
            base = os.path.join(base, segment) if base else segment
        return base

    def _apply_prefix(self, argv: list[str]) -> list[str]:
        """Prepend all active prefixes (outer→inner) to an argv."""
        prefix: list[str] = []
        for entry in self._prefix_stack:
            prefix.extend(entry)
        return [*prefix, *argv]

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
        """Run a command in one of the three forms (§B.1) and return a result.

        ``stream`` is a sink invoked with each live stdout chunk; it tees with
        ``capture`` (both happen — output is read once and fanned out, §B.2).
        ``in_stream`` feeds the child's stdin. ``timeout`` kills the process
        group and always raises ``ShellError`` (a kill is not a clean exit).
        ``retry`` re-runs on failure per its policy. ``pty`` runs under a
        pseudo-terminal (POSIX; degrades to pipes on Windows). ``watchers``
        answer live prompts by writing to stdin (§B.4). ``background`` starts
        the command and returns immediately — nothing is captured or checked
        because it has not finished; pair it with :meth:`defer` to tear it down
        (§B.5).

        Raises:
            ShellError: On non-zero exit under ``check``, on timeout (always),
                or on a :class:`FailingResponder` sentinel.
        """
        argv, use_shell, display = self._resolve_command(
            command, shell=shell, template_params=template_params
        )
        # Mask any Secret values that flowed into the command or env before the
        # display string is stored on the result / echoed anywhere (§B.6).
        secrets = collect_secret_values(
            [
                *(command if isinstance(command, (list, tuple)) else []),
                *template_params.values(),
                *(env.values() if env is not None else []),
            ]
        )
        display = redact(display, secrets)
        run_env = self._resolve_env(env, replace_env)
        effective_cwd = self._effective_cwd(cwd)

        phase_label = label or _derive_label(display)
        if background:
            return self._start_background(
                argv,
                use_shell=use_shell,
                display=display,
                env=run_env,
                cwd=effective_cwd,
                label=phase_label,
            )

        # The command echo (§B: `silent` suppresses it). On by default because a
        # task runner that hides what it ran is the one thing every make/invoke
        # user notices missing — and `display` is already secret-redacted above,
        # so the echo cannot leak what the ShellResult would not.
        if not silent and self._echo_sink is not None:
            self._echo_sink(f"$ {display}")

        # `stream=True` means "the surface's channel"; a callable is still the
        # explicit sink (T9). Resolving here keeps every downstream runner
        # taking a plain callable.
        if stream is True:
            stream = self._output_sink
        elif stream is False:
            stream = None

        phase = f"shell.{phase_label}"
        self._emit_start(phase_label, display)
        if self._perf is not None:
            self._perf.mark_start(phase)
        try:
            result, timed_out = self._run_with_retry(
                argv,
                use_shell=use_shell,
                display=display,
                capture=capture,
                stream=stream,
                env=run_env,
                cwd=effective_cwd,
                in_stream=in_stream,
                timeout=timeout,
                retry=retry,
                pty=pty,
                watchers=tuple(watchers) if watchers else (),
            )
        finally:
            if self._perf is not None:
                self._perf.mark_end(phase)
        self._emit_end(phase_label, result)

        if timed_out:
            raise ShellError(result)
        if check and result.returncode != 0:
            raise ShellError(result)
        return result

    def _run_with_retry(
        self,
        argv: list[str] | str,
        *,
        use_shell: bool,
        display: str,
        capture: bool,
        stream: Callable[[str], None] | None,
        env: dict[str, str] | None,
        cwd: str | None,
        in_stream: str | None,
        timeout: float | None,
        retry: Retry | None,
        pty: bool,
        watchers: tuple[Responder, ...],
    ) -> tuple[ShellResult, bool]:
        """Run the command, re-running on retryable failure. Returns
        ``(result, timed_out)`` — the last attempt's outcome."""
        attempts = retry.attempts if retry is not None else 1
        result: ShellResult | None = None
        timed_out = False
        for attempt in range(1, attempts + 1):
            result, timed_out = self._run_once(
                argv,
                use_shell=use_shell,
                display=display,
                capture=capture,
                stream=stream,
                env=env,
                cwd=cwd,
                in_stream=in_stream,
                timeout=timeout,
                pty=pty,
                watchers=watchers,
            )
            if result.returncode == 0:
                return result, timed_out
            if (
                retry is not None
                and attempt < attempts
                and self._should_retry(retry, result)
            ):
                _sleep_backoff(retry, attempt)
                continue
            break
        assert result is not None
        return result, timed_out

    def _emit_start(self, label: str, display: str) -> None:
        """Emit ``shell.command.start`` (masked command in payload, §B.8)."""
        if self._event_bus is not None:
            self._event_bus.emit("shell.command.start", resource=label, command=display)

    def _emit_end(self, label: str, result: ShellResult) -> None:
        """Emit ``shell.command.end`` with the outcome (§B.8)."""
        if self._event_bus is not None:
            self._event_bus.emit(
                "shell.command.end",
                resource=label,
                command=result.command,
                returncode=result.returncode,
                duration_ms=result.duration_ms,
                status="success" if result.ok else "failure",
            )

    def _run_once(
        self,
        argv: list[str] | str,
        *,
        use_shell: bool,
        display: str,
        capture: bool,
        stream: Callable[[str], None] | None,
        env: dict[str, str] | None,
        cwd: str | None,
        in_stream: str | None,
        timeout: float | None,
        pty: bool = False,
        watchers: tuple[Responder, ...] = (),
    ) -> tuple[ShellResult, bool]:
        """Run one attempt. Returns ``(result, timed_out)``.

        On POSIX the child gets its own session (``start_new_session``) so a
        timeout can kill the whole process group, not just the shell.

        ``pty`` or ``watchers`` route to the interactive path
        (:meth:`_run_interactive`), which keeps stdin open and answers prompts.
        """
        if pty or watchers:
            return self._run_interactive(
                argv,
                use_shell=use_shell,
                display=display,
                capture=capture,
                stream=stream,
                env=env,
                cwd=cwd,
                in_stream=in_stream,
                timeout=timeout,
                pty=pty,
                watchers=watchers,
            )
        piped = capture or stream is not None
        start = time.perf_counter()
        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                shell=use_shell,
                stdin=subprocess.PIPE if in_stream is not None else None,
                stdout=subprocess.PIPE if piped else None,
                stderr=subprocess.PIPE if piped else None,
                text=True,
                start_new_session=sys.platform != "win32",
            )
        except OSError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            return (
                ShellResult(127, "", str(exc), display, duration_ms, None),
                False,
            )

        timed_out = False
        try:
            if stream is not None:
                stdout, stderr = self._pump(proc, stream, in_stream, timeout=timeout)
            else:
                stdout, stderr = proc.communicate(input=in_stream, timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill_group(proc)
            stdout, stderr = self._drain_after_kill(proc)
            timed_out = True

        duration_ms = (time.perf_counter() - start) * 1000
        returncode = proc.returncode if proc.returncode is not None else 124
        if timed_out:
            returncode = 124
            stderr = (stderr or "") + f"\nTimed out after {timeout}s"
        result = ShellResult(
            returncode=returncode,
            stdout=(stdout or "") if capture else "",
            stderr=(stderr or "") if capture else "",
            command=display,
            duration_ms=duration_ms,
            pid=proc.pid,
        )
        return result, timed_out

    # ------------------------------------------------------------------
    # Interactive execution: pty + watchers/responders (§B.4)
    # ------------------------------------------------------------------

    def _run_interactive(
        self,
        argv: list[str] | str,
        *,
        use_shell: bool,
        display: str,
        capture: bool,
        stream: Callable[[str], None] | None,
        env: dict[str, str] | None,
        cwd: str | None,
        in_stream: str | None,
        timeout: float | None,
        pty: bool,
        watchers: tuple[Responder, ...],
    ) -> tuple[ShellResult, bool]:
        """Run one attempt with stdin kept open so ``watchers`` can answer live
        prompts. ``pty`` uses a pseudo-terminal on POSIX (degrades to pipes on
        Windows). Returns ``(result, timed_out)`` like :meth:`_run_once`; raises
        ``ShellError`` immediately if a :class:`FailingResponder` sentinel fires.
        """
        start = time.perf_counter()
        if pty and sys.platform != "win32":
            return self._run_pty(
                argv,
                use_shell=use_shell,
                display=display,
                capture=capture,
                stream=stream,
                env=env,
                cwd=cwd,
                in_stream=in_stream,
                timeout=timeout,
                watchers=watchers,
                start=start,
            )
        if pty:
            logger.debug("pty=True is unsupported on Windows; using pipes instead")

        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                shell=use_shell,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,  # byte-level reads — see _drain
                start_new_session=sys.platform != "win32",
            )
        except OSError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            return ShellResult(127, "", str(exc), display, duration_ms, None), False

        out_buf: list[str] = []
        err_buf: list[str] = []
        counts: dict[int, int] = {}
        failure: list[str] = []
        lock = threading.Lock()

        def _write(text: str) -> None:
            if proc.stdin is None:
                return
            try:
                proc.stdin.write(text.encode())
                proc.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                pass

        def _handle_output() -> None:
            combined = "".join(out_buf) + "".join(err_buf)
            msg = _drive_watchers(
                watchers, combined, counts, _write, lambda: self._kill_group(proc)
            )
            if msg and not failure:
                failure.append(msg)

        def _drain(pipe: Any, buf: list[str], is_out: bool) -> None:
            # Read raw chunks, never readline: an interactive prompt like
            # ``printf "Name: "`` has no trailing newline, so a line-buffered
            # reader would block forever while the child waits on stdin.
            fd = pipe.fileno()
            try:
                while True:
                    try:
                        data = os.read(fd, 1024)
                    except OSError:
                        break
                    if not data:
                        break
                    text = data.decode(errors="replace")
                    buf.append(text)
                    if is_out and stream is not None:
                        stream(text)
                    with lock:
                        _handle_output()
            finally:
                with contextlib.suppress(OSError):
                    pipe.close()

        threads: list[threading.Thread] = []
        for pipe, buf, is_out in (
            (proc.stdout, out_buf, True),
            (proc.stderr, err_buf, False),
        ):
            if pipe is not None:
                t = threading.Thread(target=_drain, args=(pipe, buf, is_out))
                t.start()
                threads.append(t)
        if in_stream is not None:
            _write(in_stream)

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill_group(proc)
            timed_out = True
        for t in threads:
            t.join()
        if proc.stdin is not None:
            with contextlib.suppress(BrokenPipeError, OSError):
                proc.stdin.close()

        stdout = "".join(out_buf)
        stderr = "".join(err_buf)
        return self._finalize_interactive(
            proc,
            display=display,
            capture=capture,
            stdout=stdout,
            stderr=stderr,
            start=start,
            timeout=timeout,
            timed_out=timed_out,
            failure=failure[0] if failure else None,
        )

    def _run_pty(
        self,
        argv: list[str] | str,
        *,
        use_shell: bool,
        display: str,
        capture: bool,
        stream: Callable[[str], None] | None,
        env: dict[str, str] | None,
        cwd: str | None,
        in_stream: str | None,
        timeout: float | None,
        watchers: tuple[Responder, ...],
        start: float,
    ) -> tuple[ShellResult, bool]:
        """POSIX pty attempt: child sees a real terminal; output is merged onto
        the pty master (stdout only). Watchers write to the master."""
        import pty as _pty
        import select

        master, slave = _pty.openpty()
        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                shell=use_shell,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                text=False,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            os.close(master)
            os.close(slave)
            duration_ms = (time.perf_counter() - start) * 1000
            return ShellResult(127, "", str(exc), display, duration_ms, None), False
        os.close(slave)

        out: list[str] = []
        counts: dict[int, int] = {}
        failure: list[str] = []

        def _write(text: str) -> None:
            with contextlib.suppress(OSError):
                os.write(master, text.encode())

        if in_stream is not None:
            _write(in_stream)

        deadline = None if timeout is None else time.monotonic() + timeout
        timed_out = False
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                self._kill_group(proc)
                timed_out = True
                break
            wait = (
                0.1
                if deadline is None
                else max(0.0, min(0.1, deadline - time.monotonic()))
            )
            ready, _, _ = select.select([master], [], [], wait)
            if master in ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break  # slave closed → EOF
                if not chunk:
                    break
                text = chunk.decode(errors="replace")
                out.append(text)
                if stream is not None:
                    stream(text)
                msg = _drive_watchers(
                    watchers,
                    "".join(out),
                    counts,
                    _write,
                    lambda: self._kill_group(proc),
                )
                if msg and not failure:
                    failure.append(msg)
            if proc.poll() is not None and master not in ready:
                break
        os.close(master)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._kill_group(proc)
        return self._finalize_interactive(
            proc,
            display=display,
            capture=capture,
            stdout="".join(out),
            stderr="",
            start=start,
            timeout=timeout,
            timed_out=timed_out,
            failure=failure[0] if failure else None,
        )

    def _finalize_interactive(
        self,
        proc: subprocess.Popen[Any],
        *,
        display: str,
        capture: bool,
        stdout: str,
        stderr: str,
        start: float,
        timeout: float | None,
        timed_out: bool,
        failure: str | None,
    ) -> tuple[ShellResult, bool]:
        """Build the result for an interactive attempt (shared pty/pipe tail).

        A ``failure`` (FailingResponder sentinel) raises ``ShellError`` at once —
        it is an abort, not a normal exit that retry/`check` should reinterpret.
        """
        duration_ms = (time.perf_counter() - start) * 1000
        returncode = proc.returncode if proc.returncode is not None else 124
        if failure is not None:
            raise ShellError(
                ShellResult(
                    returncode or 1,
                    stdout if capture else "",
                    ((stderr + "\n" + failure) if capture else failure),
                    display,
                    duration_ms,
                    proc.pid,
                )
            )
        if timed_out:
            returncode = 124
            stderr = stderr + f"\nTimed out after {timeout}s"
        result = ShellResult(
            returncode=returncode,
            stdout=stdout if capture else "",
            stderr=stderr if capture else "",
            command=display,
            duration_ms=duration_ms,
            pid=proc.pid,
        )
        return result, timed_out

    def _start_background(
        self,
        argv: list[str] | str,
        *,
        use_shell: bool,
        display: str,
        env: dict[str, str] | None,
        cwd: str | None,
        label: str,
    ) -> ShellResult:
        """Start a command without waiting (``background=True``, §B.5).

        Returns a result describing the *launch*: returncode 0 means "started",
        not "succeeded" — the process is still running. No perf phase and no
        ``shell.command.end`` event, because it has not ended.
        """
        start = time.perf_counter()
        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                shell=use_shell,
                start_new_session=sys.platform != "win32",
            )
        except OSError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            return ShellResult(127, "", str(exc), display, duration_ms, None)
        self._background.append(proc)
        self._emit_start(label, display)
        duration_ms = (time.perf_counter() - start) * 1000
        return ShellResult(0, "", "", display, duration_ms, proc.pid)

    def defer(self, command: list[str] | str, **kwargs: Any) -> None:
        """Register a cleanup command to run when the job exits (§B.5).

        Deferred commands run **LIFO** on the engine's job-exit unwind — on
        success, on failure, on Ctrl+C, and after a timeout — not via user
        ``try``/``finally``, which is exactly what a killed subprocess tree or a
        hard timeout skips::

            sh(["kubectl", "port-forward", "svc/db", "5432:5432"], background=True)
            sh.defer(["pkill", "-f", "port-forward"])

        ``kwargs`` are the same options :meth:`__call__` takes. Only a SIGKILL
        of the functualize process itself can skip the unwind.
        """
        self._deferred.append((command, kwargs))

    def run_deferred(self) -> None:
        """Run and clear all deferred commands, LIFO (engine-owned, §B.5).

        Best-effort: a cleanup command that fails (or raises) must not mask the
        job's own outcome, and must not stop the remaining cleanups — each
        failure is logged and the unwind continues.
        """
        while self._deferred:
            command, kwargs = self._deferred.pop()
            kwargs.setdefault("check", False)
            try:
                self(command, **kwargs)
            except Exception:  # noqa: BLE001 — cleanup must never mask the job
                logger.warning("Deferred command failed: %r", command, exc_info=True)
        self._reap_background()

    def _reap_background(self) -> None:
        """Drop finished background processes (started with ``background=True``).

        Survivors are left running deliberately — a background command outliving
        the job is the caller's choice; ``defer`` is how you tear one down.
        """
        self._background = [p for p in self._background if p.poll() is None]

    def sudo(
        self,
        command: list[str],
        *,
        preserve_env: bool = False,
        password: Secret | str | None = None,
        watchers: Sequence[Responder] | None = None,
        **kwargs: Any,
    ) -> ShellResult:
        """Run ``command`` under ``sudo -S`` with an auto password responder (§B.4).

        The password comes from ``password=`` or the injected
        ``[shell] sudo_password`` secret; it is fed to sudo's stdin via a
        :class:`FailingResponder` (which aborts on ``Sorry, try again``), never
        placed in the echoed command. ``preserve_env`` adds ``--preserve-env``.
        Requires the list command form (safe, explicit).

        Raises:
            ValueError: If no password is available, or ``command`` is not a
                list — precondition errors, caught before anything runs.
            ShellError: If the command itself fails.
        """
        if not isinstance(command, (list, tuple)):
            raise ValueError(
                "sh.sudo requires the list command form, e.g. "
                "sh.sudo(['systemctl', 'restart', 'nginx'])."
            )
        pw = password if password is not None else self._sudo_password
        if pw is None:
            # T-S6b-4: ask, if there is anybody to ask. On a non-interactive
            # surface this raises MissingValueError naming the config field and
            # its env var — the same refusal as before, but typed and
            # actionable rather than a bare ValueError. Still never a hang:
            # prompting where nothing can answer is exactly how CI jobs wedge.
            from functualize._engine.missing_value import (
                env_var_for,
                resolve_missing_value,
            )

            pw = resolve_missing_value(
                self._prompt,
                field="[shell] sudo_password",
                env_var=env_var_for("shell", "sudo_password"),
                message="sudo password",
                secret=True,
            )
        prompt = "functualize-sudo-password:"
        sudo_prefix = ["sudo", "-S", "-p", prompt]
        if preserve_env:
            sudo_prefix.append("--preserve-env")
        pw_watcher = FailingResponder(
            pattern=prompt, response=reveal(pw) + "\n", sentinel="Sorry, try again"
        )
        all_watchers = [pw_watcher, *(watchers or [])]
        return self([*sudo_prefix, *command], watchers=all_watchers, **kwargs)

    def _kill_group(self, proc: subprocess.Popen[Any]) -> None:
        """Kill the child's process group (POSIX) or the process (Windows)."""
        try:
            if sys.platform != "win32":
                import signal

                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()

    def _drain_after_kill(self, proc: subprocess.Popen[str]) -> tuple[str, str]:
        """Best-effort collect any buffered output after a kill."""
        try:
            return proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, ValueError):
            return "", ""

    def _should_retry(self, retry: Retry, result: ShellResult) -> bool:
        """Whether a failed attempt is retryable under ``retry`` (§A.5).

        With ``on_exit_codes`` set, only those codes retry; empty retries any
        non-zero exit.
        """
        if retry.on_exit_codes:
            return result.returncode in retry.on_exit_codes
        return True

    def _pump(
        self,
        proc: subprocess.Popen[str],
        stream: Callable[[str], None],
        in_stream: str | None,
        timeout: float | None = None,
    ) -> tuple[str, str]:
        """Tee live output: drain stdout/stderr in threads (no deadlock), fan
        each stdout line to ``stream`` while buffering both for the result.

        Raises ``subprocess.TimeoutExpired`` if the process outlives ``timeout``.
        """
        out_buf: list[str] = []
        err_buf: list[str] = []

        def _drain(
            pipe: Any, buf: list[str], sink: Callable[[str], None] | None
        ) -> None:
            with pipe:
                for line in iter(pipe.readline, ""):
                    buf.append(line)
                    if sink is not None:
                        sink(line)

        threads: list[threading.Thread] = []
        if proc.stdout is not None:
            t = threading.Thread(target=_drain, args=(proc.stdout, out_buf, stream))
            t.start()
            threads.append(t)
        if proc.stderr is not None:
            t = threading.Thread(target=_drain, args=(proc.stderr, err_buf, None))
            t.start()
            threads.append(t)
        if in_stream is not None and proc.stdin is not None:
            proc.stdin.write(in_stream)
            proc.stdin.close()
        proc.wait(timeout=timeout)  # raises TimeoutExpired if exceeded
        for t in threads:
            t.join()
        return "".join(out_buf), "".join(err_buf)

    # ------------------------------------------------------------------
    # Command-form resolution (§B.1) — the injection-safety boundary
    # ------------------------------------------------------------------

    def _resolve_command(
        self,
        command: list[str] | str,
        *,
        shell: bool,
        template_params: dict[str, Any],
    ) -> tuple[list[str] | str, bool, str]:
        """Resolve a command to ``(argv_or_string, use_shell, display)``.

        - list form → argv, no shell.
        - raw string + ``shell=True`` → shell string via the shell program;
          any template params are ``shlex.quote``-d before interpolation.
        - template string + params (no shell) → quote, interpolate, split to
          argv, run without a shell.
        - bare raw string (no shell, no params) → ``ValueError`` (ambiguous).
        """
        if isinstance(command, (list, tuple)):
            argv = self._apply_prefix([reveal(a) for a in command])
            return argv, False, shlex.join(argv)

        if not isinstance(command, str):
            raise ValueError(
                f"Shell command must be a list or str, got {type(command).__name__}"
            )

        quoted = {k: _quote(v) for k, v in template_params.items()}
        interpolated = command.format(**quoted) if quoted else command

        if shell:
            # Raw form: run under the configured shell. On POSIX the program is
            # ["/bin/sh", "-c"] and Popen(shell=False) with that argv is the
            # safe, explicit equivalent of shell interpretation. The raw string
            # is preserved verbatim (pipes/globs intact); an active prefix is
            # prepended as literal tokens.
            prefix = [t for entry in self._prefix_stack for t in entry]
            command_str = " ".join([*prefix, interpolated]) if prefix else interpolated
            return [*self._shell_program, command_str], False, command_str

        if quoted:
            # Template form: quoting already happened, so splitting is safe.
            argv = self._apply_prefix(shlex.split(interpolated))
            return argv, False, shlex.join(argv)

        raise ValueError(
            "Raw string commands require shell=True (for shell interpretation) "
            "or template params (auto-quoted), never a silent split. Use the "
            "list form for the common case: sh(['git', 'status'])."
        )

    def _resolve_env(
        self, env: Mapping[str, str] | None, replace_env: bool
    ) -> dict[str, str] | None:
        """Merge ``env`` over the inherited environment, or replace it."""
        if env is None:
            return None
        if replace_env:
            return {str(k): reveal(v) for k, v in env.items()}
        import os

        merged = dict(os.environ)
        merged.update({str(k): reveal(v) for k, v in env.items()})
        return merged


def _sleep_backoff(retry: Retry, attempt: int) -> None:
    """Sleep between retry attempts per the backoff policy (§A.5)."""
    if retry.backoff == "constant":
        delay = 0.1
    elif retry.backoff == "linear":
        delay = 0.1 * attempt
    else:  # exponential
        delay = 0.1 * (2 ** (attempt - 1))
    time.sleep(delay)


def _as_pattern(pattern: str | re.Pattern[str]) -> re.Pattern[str]:
    """Compile a watcher pattern (str is treated as a regex)."""
    return pattern if isinstance(pattern, re.Pattern) else re.compile(pattern)


def _pattern_repr(pattern: str | re.Pattern[str]) -> str:
    return pattern.pattern if isinstance(pattern, re.Pattern) else pattern


def _drive_watchers(
    watchers: tuple[Responder, ...],
    combined: str,
    counts: dict[int, int],
    write: Callable[[str], None],
    kill: Callable[[], None],
) -> str | None:
    """Apply ``watchers`` to the ``combined`` output so far (§B.4).

    For each new match of a watcher's ``pattern``, ``write`` its response to the
    child's stdin (``counts`` dedups already-answered matches per watcher). If a
    :class:`FailingResponder` sentinel appears, ``kill`` the process and return a
    failure message; otherwise return ``None``.
    """
    for watcher in watchers:
        if isinstance(watcher, FailingResponder) and _as_pattern(
            watcher.sentinel
        ).search(combined):
            kill()
            return (
                f"aborted: output matched sentinel {_pattern_repr(watcher.sentinel)!r}"
            )
        matches = sum(1 for _ in _as_pattern(watcher.pattern).finditer(combined))
        already = counts.get(id(watcher), 0)
        for _ in range(already, matches):
            write(watcher.response)
        counts[id(watcher)] = matches
    return None


def _derive_label(display: str) -> str:
    """Derive a perf/event label from a command when none is given (§B.8).

    Uses the command's first token (its program), path-stripped — e.g.
    ``/usr/bin/git status`` → ``git``. Falls back to ``command``.
    """
    try:
        first = shlex.split(display)[0]
    except (ValueError, IndexError):
        stripped = display.strip()
        first = stripped.split(" ", 1)[0] if stripped else ""
    return os.path.basename(first) or "command"


def _quote(value: Any) -> str:
    """Quote a template-substituted value for safe interpolation (§B.1).

    Unwraps a :class:`Secret` to its real value so the command runs correctly;
    the caller masks the real value out of the display string afterwards (§B.6).
    """
    if sys.platform == "win32":
        # Windows argv quoting differs from POSIX; wrap in double quotes and
        # escape embedded quotes. (Full argv rules refined with the Windows
        # test matrix.)
        text = reveal(value)
        return '"' + text.replace('"', '\\"') + '"' if text else '""'
    return shlex.quote(reveal(value))


# ── Registry entry (ADR-014) ───────────────────────────────────────────────
#
# Declared here rather than in `_types/shell.py`, where the `Shell` protocol
# lives: `_types` may import nothing internal, so it cannot hold a factory that
# constructs `WiredShell`. See the note in `stdout.py`.


def _make_shell(ctx: Any) -> WiredShell:
    """Build the wired shell for this invocation."""
    from functualize._events.perf import perf_timeline

    engine = ctx.engine
    echo_sink, output_sink = engine._resolve_shell_sinks()
    return WiredShell(
        cwd=str(ctx.context.cwd) if ctx.context.cwd else None,
        program=engine._resolve_shell_program(),
        perf=perf_timeline,
        event_bus=engine._event_bus,
        sudo_password=engine._resolve_sudo_password(),
        echo_sink=echo_sink,
        output_sink=output_sink,
        # For the sudo-password fallback only (T-S6b-4). Built on the same
        # active collector every other prompt resolves through, so an
        # interactive surface can answer and a piped one refuses.
        prompt=engine._resolve_prompt_capability(),
    )


CAPABILITY = CapabilitySpec(
    name="Shell",
    type=Shell,
    factory=_make_shell,
)
