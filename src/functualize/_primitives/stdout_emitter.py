"""Stdout emission for Unix pipe composability (§C.2 serialization contract).

The serialization engine behind the explicit ``Stdout`` capability
(``out.emit(value)`` — see ``_engine/capabilities/stdout.py``), so functualize
jobs compose in Unix pipelines. The format is chosen by the ``--output`` global
flag, or — when unset (``"auto"``) — auto-dispatched by the value's type.

Note: a job's *return value* is never emitted here. Emission is always explicit
(``out.emit``); the return value is programmatic-only (``rc.invoke``/``FromJob``).

Public API:
- ``StdoutEmitter`` — serializes a value to stdout per the contract

§C.2 contract (auto-dispatch by value type when ``--output`` is unset):

===========================  ==========================================
Return type                  Emission
===========================  ==========================================
``str`` / ``bytes``          Raw, as-is (no added newline).
``None``                     Nothing.
model / dataclass / dict /   Compact JSON, one document, trailing newline.
list
generator / iterator         NDJSON — one compact JSON document per yielded
                             item, flushed per item (row-wise streaming).
===========================  ==========================================

An explicit ``--output`` value overrides the auto-dispatch:

- ``raw``    — ``str``/``bytes`` written as-is; anything else coerced via ``str``.
- ``json``   — one compact JSON document (a generator is materialized first,
               subject to the spill cap).
- ``ndjson`` — one JSON document per item for iterables; a scalar emits a single
               line.
- ``none``   — nothing.

Q3 (ratified 2026-07-20): JSON serialization of an unbounded value is buffered
up to ``_SPILL_THRESHOLD_BYTES`` in memory, then spilled to a tempfile that is
streamed to stdout and removed — bounding peak memory without truncating data.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
from collections.abc import Iterator
from typing import IO, Any

__all__ = ["StdoutEmitter"]

# Q3: buffer a compact-JSON document up to this many bytes in memory before
# spilling the remainder to a tempfile. 8 MiB keeps small results allocation-free
# while capping peak memory for large ones.
_SPILL_THRESHOLD_BYTES = 8 * 1024 * 1024


def _is_streaming(value: Any) -> bool:
    """A generator/iterator return streams row-wise; str/bytes/mapping do not."""
    if isinstance(value, (str, bytes, bytearray, dict, list, tuple)):
        return False
    return isinstance(value, Iterator)


def _to_jsonable(value: Any) -> Any:
    """Best-effort conversion to a JSON-native structure.

    Pydantic models expose ``model_dump``; dataclasses convert via ``asdict``;
    everything else is handed to ``json`` with ``default=str`` downstream.
    """
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return value


def _compact_json(value: Any) -> str:
    """Compact one-line JSON (no spaces), ``str`` fallback for exotic types."""
    return json.dumps(_to_jsonable(value), separators=(",", ":"), default=str)


class StdoutEmitter:
    """Emits a job's return value to stdout per the §C.2 serialization contract.

    ``format`` is a resolved value from :func:`resolve_output_format`:
    ``"raw"``, ``"json"``, ``"ndjson"``, ``"none"``, or ``"auto"`` (dispatch by
    return type). ``"none"`` and a ``None`` return both emit nothing.
    """

    def __init__(
        self,
        format: str = "none",
        *,
        stream: IO[Any] | None = None,  # noqa: A002
    ) -> None:
        self._format = format
        # Bind lazily at emit time by default so tests that monkeypatch
        # sys.stdout after construction still see the redirect.
        self._stream = stream

    def _out(self) -> IO[Any]:
        return self._stream if self._stream is not None else sys.stdout

    def emit(self, return_value: Any) -> None:
        """Write *return_value* to stdout according to the resolved format.

        Postconditions:
            - ``"none"`` or a ``None`` return → nothing written.
            - ``"auto"`` → dispatch by type (str/bytes raw · JSON doc · NDJSON).
            - ``"raw"`` → str/bytes as-is; else ``str(value)``.
            - ``"json"`` → one compact JSON document (+ newline); generators are
              materialized (spill-capped).
            - ``"ndjson"`` → one JSON document per item, flushed per item; a
              scalar emits a single line.
            - ``rc.log()`` output (routed to stderr) is unaffected.
        """
        fmt = self._format
        if fmt == "none" or return_value is None:
            return

        if fmt == "auto":
            self._emit_auto(return_value)
        elif fmt == "raw":
            self._emit_raw(return_value)
        elif fmt == "json":
            self._emit_json(self._materialize(return_value))
        elif fmt == "ndjson":
            self._emit_ndjson(return_value)
        else:  # pragma: no cover — resolve_output_format constrains fmt
            msg = f"Unknown output format: {fmt!r}"
            raise ValueError(msg)

    # ── auto-dispatch (§C.2 type table) ─────────────────────────────────────

    def _emit_auto(self, value: Any) -> None:
        if isinstance(value, (str, bytes, bytearray)):
            self._emit_raw(value)
        elif _is_streaming(value):
            self._emit_ndjson(value)
        else:
            self._emit_json(value)

    # ── raw ─────────────────────────────────────────────────────────────────

    def _emit_raw(self, value: Any) -> None:
        out = self._out()
        if isinstance(value, (bytes, bytearray)):
            buf = getattr(out, "buffer", None)
            if buf is not None:
                buf.write(bytes(value))
                buf.flush()
            else:  # text-only stream (e.g. StringIO in tests)
                out.write(bytes(value).decode("utf-8", "replace"))
                out.flush()
            return
        out.write(value if isinstance(value, str) else str(value))
        out.flush()

    # ── single JSON document (with Q3 spill cap) ────────────────────────────

    def _emit_json(self, value: Any) -> None:
        text = _compact_json(value)
        out = self._out()
        if len(text) <= _SPILL_THRESHOLD_BYTES:
            out.write(text)
            out.write("\n")
            out.flush()
            return
        # Spill-to-tempfile: never hold two copies of a huge payload; stream it.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as tmp:
            tmp.write(text)
            tmp.write("\n")
            del text
            tmp.seek(0)
            for chunk in iter(lambda: tmp.read(_SPILL_THRESHOLD_BYTES), ""):
                out.write(chunk)
            out.flush()

    def _materialize(self, value: Any) -> Any:
        """Collect a generator into a list for one-document JSON, spill-aware.

        Non-iterators pass through unchanged. This is only reached for
        ``--output json`` over a streaming return; the auto path keeps
        generators streaming as NDJSON instead.
        """
        if _is_streaming(value):
            return list(value)
        return value

    # ── NDJSON (row-wise, flushed per item) ─────────────────────────────────

    def _emit_ndjson(self, value: Any) -> None:
        out = self._out()
        if isinstance(value, (str, bytes, bytearray, dict)) or not isinstance(
            value, (list, tuple, Iterator)
        ):
            # Scalar / mapping / non-iterable → a single NDJSON line.
            out.write(_compact_json(value))
            out.write("\n")
            out.flush()
            return
        for item in value:
            out.write(_compact_json(item))
            out.write("\n")
            out.flush()  # per-item flush: downstream sees rows as produced
