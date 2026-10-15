"""Stdin test seams: a fake stream and a real OS pipe.

`stdin_reader` asks the process stdin three questions — is it a terminal
(`isatty`), is content already waiting (the readiness probe), and what is on
it (`read`). Tests swap the whole stream instead of patching methods on the
real one: a method patch leaves the real `fileno()` behind, and the readiness
probe would then poll the runner's own stdin, making the outcome depend on
where the suite was started.

:class:`FakeStdin` answers the probe through a ``data_ready()`` attribute (the
handshake the probe documents) and has no ``fileno()``, so no code path reaches
a real descriptor. :func:`real_pipe_stdin` exercises the opposite end of the
seam: a real pipe, so the probe's ``select`` path and the wall clock are what
is actually under test.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO


class FakeStdin:
    """A ``sys.stdin`` stand-in with explicit tty/readiness/content answers."""

    def __init__(
        self, *, tty: bool = False, data: str = "", ready: bool = True
    ) -> None:
        self._tty = tty
        self._data = data
        self._ready = ready
        self.read_calls = 0

    def isatty(self) -> bool:
        return self._tty

    def data_ready(self) -> bool:
        return self._ready

    def read(self) -> str:
        self.read_calls += 1
        return self._data


@contextmanager
def fake_stdin(
    *, tty: bool = False, data: str = "", ready: bool = True
) -> Iterator[FakeStdin]:
    """Swap ``sys.stdin`` for a :class:`FakeStdin` for the duration of the block."""
    fake = FakeStdin(tty=tty, data=data, ready=ready)
    previous = sys.stdin
    sys.stdin = fake  # type: ignore[assignment]
    try:
        yield fake
    finally:
        sys.stdin = previous


@contextmanager
def real_pipe_stdin(content: str | None) -> Iterator[IO[str]]:
    """Swap ``sys.stdin`` for one end of a real OS pipe.

    ``content=None`` leaves the write end open and empty — the silent pipe of
    ``sleep 30 | func s``, where the probe must say "nothing there" and the
    reader must not wait. Any other value is written and the writer closes,
    which is what a finished upstream looks like.
    """
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "r", encoding="utf-8")
    writer = os.fdopen(write_fd, "w", encoding="utf-8")
    previous = sys.stdin
    sys.stdin = stream  # type: ignore[assignment]
    try:
        if content is not None:
            writer.write(content)
            writer.close()
        yield stream
    finally:
        sys.stdin = previous
        stream.close()
        if not writer.closed:
            writer.close()
