"""``Stdout`` capability implementation — the explicit stdout data channel.

``WiredStdout`` is what the engine injects for an ``out: Stdout`` parameter. It
wraps the §C.2 serialization engine (``_primitives/stdout_emitter.py``) with the
resolved ``--output`` format and secret redaction.

Two intents (see ``_types/stdout.py``):

- ``emit(value)`` — serialize per ``--output``, one document per call, flushed.
- ``write(data)`` — raw verbatim passthrough, no serialization.

Explicit emission is **never surface-suppressed**: unlike the removed implicit
return-value emission, ``emit``/``write`` always write, on a TTY too. The job
author asked for it.
"""

from __future__ import annotations

import sys
from typing import IO, Any

from functualize._primitives.stdout_emitter import StdoutEmitter
from functualize._types.redaction import redact

__all__ = ["WiredStdout"]


class WiredStdout:
    """Engine-side ``Stdout`` capability (proposal Part C, revised).

    Args:
        output_format: The resolved ``--output`` value — one of ``"auto"``
            (dispatch by value type), ``"json"``, ``"ndjson"``, ``"raw"``, or
            ``"none"`` (suppress). Defaults to ``"auto"``.
        secrets: Secret string values to mask (``•••``) in anything written.
            Sourced from the job's ``secret=True`` config fields / ``Secret[str]``
            values, per schema §5 — secrets must not leak through the data
            channel any more than through a command echo.
        stream: Destination stream. Defaults to ``sys.stdout``, bound lazily so
            a redirect installed after construction is still honored.
    """

    def __init__(
        self,
        output_format: str = "auto",
        *,
        secrets: frozenset[str] | set[str] | None = None,
        stream: IO[Any] | None = None,
    ) -> None:
        self._format = output_format or "auto"
        self._secrets = frozenset(secrets or ())
        self._stream = stream

    def _out(self) -> IO[Any]:
        return self._stream if self._stream is not None else sys.stdout

    # ── emit: serialize per --output ────────────────────────────────────────

    def emit(self, value: Any) -> None:
        """Serialize ``value`` to stdout per the resolved ``--output`` format.

        ``--output`` decides list handling: ``emit([a, b, c])`` is one JSON
        array under ``json`` and one line per item under ``ndjson``. To stream
        rows explicitly, loop ``for r in rows: out.emit(r)``.

        A ``"none"`` format suppresses output entirely; ``None`` emits nothing
        regardless of format.
        """
        if self._format == "none" or value is None:
            return
        if not self._secrets:
            StdoutEmitter(format=self._format, stream=self._out()).emit(value)
            return
        # Redaction needs the rendered text, so serialize into a buffer first,
        # mask, then write. Only pays this cost when the job actually holds
        # secrets — the common path streams straight through above.
        from io import StringIO

        buffer = StringIO()
        StdoutEmitter(format=self._format, stream=buffer).emit(value)
        self._write_text(redact(buffer.getvalue(), self._secrets))

    # ── write: raw passthrough ──────────────────────────────────────────────

    def write(self, data: str | bytes) -> None:
        """Write ``data`` to stdout verbatim — no serialization, no newline.

        ``bytes`` go to the underlying binary buffer when the stream has one
        (a real stdout); text-only streams (a ``StringIO`` in tests) receive a
        UTF-8 decode instead.
        """
        if self._format == "none":
            return
        if isinstance(data, (bytes, bytearray)):
            out = self._out()
            buf = getattr(out, "buffer", None)
            if buf is not None:
                payload = bytes(data)
                if self._secrets:
                    payload = redact(
                        payload.decode("utf-8", "replace"), self._secrets
                    ).encode("utf-8")
                buf.write(payload)
                buf.flush()
                return
            data = bytes(data).decode("utf-8", "replace")
        text = data if isinstance(data, str) else str(data)
        self._write_text(redact(text, self._secrets) if self._secrets else text)

    def _write_text(self, text: str) -> None:
        out = self._out()
        out.write(text)
        out.flush()
