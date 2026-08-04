"""FakeStdout — a test double for the ``Stdout`` capability (Part C).

Records what a job emits so pipeline behavior can be asserted without capturing
real process stdout::

    fake = FakeStdout()
    run_job(export, out=fake)
    assert fake.emitted == [{"id": 1}, {"id": 2}]
    assert fake.text.splitlines() == ['{"id":1}', '{"id":2}']

``emitted`` holds the *objects* handed to :meth:`emit` (assert on data, not on
formatting); ``text`` holds the rendered stream exactly as a pipe would see it
(assert on the wire format). ``writes`` holds raw :meth:`write` payloads.
"""

from __future__ import annotations

from io import StringIO
from typing import Any

from functualize._primitives.stdout_emitter import StdoutEmitter

__all__ = ["FakeStdout"]


class FakeStdout:
    """In-memory ``Stdout`` double.

    Args:
        output_format: The format ``emit`` renders with — ``"auto"`` (default,
            dispatch by value type), ``"json"``, ``"ndjson"``, ``"raw"``, or
            ``"none"``. Mirrors the ``--output`` flag so a test can pin the wire
            shape a caller would get.
    """

    def __init__(self, output_format: str = "auto") -> None:
        self._format = output_format or "auto"
        self._buffer = StringIO()
        #: Objects passed to :meth:`emit`, in order.
        self.emitted: list[Any] = []
        #: Raw payloads passed to :meth:`write`, in order.
        self.writes: list[str | bytes] = []

    @property
    def text(self) -> str:
        """Everything written so far, as a pipe consumer would see it."""
        return self._buffer.getvalue()

    def emit(self, value: Any) -> None:
        """Record ``value`` and render it per the configured format."""
        self.emitted.append(value)
        if self._format == "none" or value is None:
            return
        StdoutEmitter(format=self._format, stream=self._buffer).emit(value)

    def write(self, data: str | bytes) -> None:
        """Record and buffer a raw passthrough write."""
        self.writes.append(data)
        if self._format == "none":
            return
        text = data if isinstance(data, str) else bytes(data).decode("utf-8", "replace")
        self._buffer.write(text)
