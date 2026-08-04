"""``Stdout`` capability vocabulary — the explicit stdout data channel (Part C).

Job authors annotate ``out: Stdout`` and call ``out.emit(value)`` /
``out.write(data)`` to put data on stdout. The engine injects a concrete
implementation per invocation (``_engine/capabilities/stdout.py``).

Design (ratified 2026-07-23): a job's
**return value is programmatic-only** — it feeds ``rc.invoke()`` and
``FromJob``/``FromStep`` and is never auto-serialized to the pipe. Data reaches
stdout **only** through this explicit capability. ``--output`` selects the wire
format ``emit`` uses; it is *not* ``--format`` (which is MCP/command-owned).

Placed in ``_types`` (stdlib-only Protocol) so every layer and the public
``functualize.job`` / ``functualize.testing`` re-exports share one definition.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Stdout(Protocol):
    """DI-injectable explicit stdout data channel (proposal Part C, revised).

    Two methods, two intents:

    - **``emit(value)``** — serialize ``value`` to stdout per the resolved
      ``--output`` format, one logical document per call, flushed per call.
      ``value`` may be ``str``/``bytes``, ``dict``/``list``, a pydantic model,
      a dataclass, or an iterable of those. ``--output`` decides list handling:
      ``emit([a, b, c])`` is one JSON array under ``json`` and one line per item
      under ``ndjson``. To stream rows explicitly, loop ``for r in rows:
      out.emit(r)``.
    - **``write(data)``** — raw verbatim passthrough (``str`` or ``bytes``), no
      serialization. For ``cat``-like filters and binary output.

    Unlike the old implicit return-value emission, an explicit ``emit``/``write``
    is **never surface-suppressed**: it always writes (on a TTY too), routed so
    it coordinates with an active TUI, with secrets masked.
    """

    def emit(self, value: Any) -> None:
        """Serialize ``value`` to stdout per the resolved ``--output`` format."""
        ...

    def write(self, data: str | bytes) -> None:
        """Write ``data`` to stdout verbatim (no serialization)."""
        ...
