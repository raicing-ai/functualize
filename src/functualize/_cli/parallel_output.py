"""Three ways to show the output of jobs that all run at once (T40).

Concurrency makes output a real decision rather than a formatting preference.
Ten jobs writing to one stdout produce a transcript in which no line can be
attributed to the job that wrote it — readable while you watch it, useless
afterwards, and useless to CI. So `func builtin parallel` offers:

* ``interleaved`` — write through, as it happens. The default, because it is
  the only mode that shows a long batch making progress, and because it is
  what a pipeline downstream of ``func`` already expects.
* ``prefixed`` — every line tagged ``[job] …``. Attribution without waiting;
  the mode to reach for when a batch hangs and you need to know which job.
* ``grouped`` — buffer each job, emit its whole block when it finishes,
  wrapped in GitHub Actions ``::group::`` markers so a CI log renders it
  collapsed, with ``::error::`` on failure. Loses liveness, gains a log a
  human can actually read a week later.

The routing works because ``WiredStdout`` resolves ``sys.stdout`` lazily on
every write, so replacing it for the duration of the batch reaches jobs already
running — and reaches a plain ``print()`` in a job body too, which a
capability-only interception would miss.

The one thing it cannot follow is a thread a job spawns itself: attribution is
by thread identity, and a job's own worker threads are not in the map. Their
output falls through to the real stdout rather than being dropped, which is the
right failure — visible and unattributed beats invisible.
"""

from __future__ import annotations

import io
import sys
import threading
from typing import IO, Any

__all__ = ["OUTPUT_MODES", "ParallelOutput"]

OUTPUT_MODES: tuple[str, ...] = ("interleaved", "grouped", "prefixed")
"""The valid ``--output`` values, in the order they appear in help."""


class _ThreadRouted(io.TextIOBase):
    """A stdout stand-in that sends each thread's writes to its own sink."""

    def __init__(self, real: IO[Any], sinks: dict[int, Any]) -> None:
        self._real = real
        self._sinks = sinks

    def _target(self) -> Any:
        return self._sinks.get(threading.get_ident(), self._real)

    def write(self, text: str) -> int:
        return int(self._target().write(text))

    def flush(self) -> None:
        target = self._target()
        if hasattr(target, "flush"):
            target.flush()

    def isatty(self) -> bool:
        # Buffered output is never a terminal, whatever the real stream is.
        # Claiming otherwise invites a job to emit colour codes into a CI log.
        return bool(self._sinks) is False and self._real.isatty()


class ParallelOutput:
    """Routes concurrent job output according to the chosen mode.

    Used as a context manager around the batch; jobs claim a slot by calling
    :meth:`claim` from their own worker thread.
    """

    def __init__(self, mode: str, *, stream: IO[Any] | None = None) -> None:
        if mode not in OUTPUT_MODES:  # defensive; click validates first
            raise ValueError(f"unknown output mode {mode!r}")
        self._mode = mode
        self._stream = stream
        self._sinks: dict[int, Any] = {}
        self._names: dict[int, str] = {}
        self._lock = threading.Lock()
        self._saved: Any = None

    @property
    def real(self) -> Any:
        """Where a buffered block is finally written.

        Whatever ``sys.stdout`` was when the batch started — deliberately not
        ``sys.__stdout__``. The CLI may already have redirected stdout (a test
        harness capturing it, a caller piping it), and writing past that to the
        process's original stream would send the output somewhere nobody asked
        for and nobody is reading.
        """
        if self._stream is not None:
            return self._stream
        return self._saved if self._saved is not None else sys.stdout

    def __enter__(self) -> ParallelOutput:
        if self._mode != "interleaved":
            self._saved = sys.stdout
            sys.stdout = _ThreadRouted(self.real, self._sinks)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._saved is not None:
            sys.stdout = self._saved
            self._saved = None

    def claim(self, job_name: str) -> None:
        """Bind the calling thread's output to ``job_name``."""
        if self._mode == "interleaved":
            return
        ident = threading.get_ident()
        with self._lock:
            self._sinks[ident] = io.StringIO()
            self._names[ident] = job_name

    def release(self, job_name: str, *, failed: bool) -> None:
        """Emit what the calling thread buffered, and unbind it."""
        if self._mode == "interleaved":
            return
        ident = threading.get_ident()
        with self._lock:
            buffer = self._sinks.pop(ident, None)
            self._names.pop(ident, None)
        if buffer is None:
            return
        text = buffer.getvalue()
        # The whole block is written under the lock so two jobs finishing at
        # once cannot interleave — which would defeat the point of buffering.
        with self._lock:
            if self._mode == "prefixed":
                self._write_prefixed(job_name, text)
            else:
                self._write_grouped(job_name, text, failed=failed)
            self.real.flush()

    def _write_prefixed(self, job_name: str, text: str) -> None:
        for line in text.splitlines():
            self.real.write(f"[{job_name}] {line}\n")

    def _write_grouped(self, job_name: str, text: str, *, failed: bool) -> None:
        # GitHub Actions collapses `::group::`…`::endgroup::` and surfaces
        # `::error::` in the run summary. Both are plain text elsewhere, so a
        # local run still reads correctly — no terminal detection needed.
        self.real.write(f"::group::{job_name}\n")
        if text:
            self.real.write(text if text.endswith("\n") else text + "\n")
        self.real.write("::endgroup::\n")
        if failed:
            self.real.write(f"::error::{job_name} failed\n")
