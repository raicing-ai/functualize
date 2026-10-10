"""Stdin pipe detection and reading for Stdin-marked parameters.

Handles non-blocking stdin detection, content reading, and resolution of
``Stdin()``-marked function parameters from piped input.

Public API:
- ``stdin_state`` — classify stdin without waiting: ``TTY`` / ``NO_INPUT`` / ``READY``
- ``is_stdin_available`` — whether a read of stdin returns promptly
- ``read_stdin`` — read all available stdin data
- ``iter_stdin_ndjson`` — lazily yield NDJSON records as they arrive
- ``resolve_stdin_params`` — populate Stdin-marked params from pipe

A parameter typed as an iterator/iterable (``Iterator[dict]``) is fed the *lazy*
NDJSON stream, so a three-stage pipeline (``func extract | func transform |
func load``) flows row-wise instead of each stage blocking until its upstream
closes. Anything else keeps the eager whole-of-stdin string.
"""

from __future__ import annotations

import enum
import json
import select
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from functualize._types.cli_markers import Stdin

__all__ = [
    "StdinState",
    "is_stdin_available",
    "stdin_markers_for",
    "stdin_state",
    "streaming_stdin_params",
    "iter_stdin_ndjson",
    "read_stdin",
    "resolve_stdin_params",
]


class StdinState(enum.Enum):
    """What a non-blocking probe can know about stdin.

    ``READY`` means *a read returns promptly*: input is already there, or
    end-of-stream is — an empty-but-present stream reads as ``""``.
    ``NO_INPUT`` means the pipe that is stdin is never written; waiting on it
    is waiting forever. ``TTY`` means nothing was piped at all.
    """

    TTY = "tty"
    NO_INPUT = "no_input"
    READY = "ready"


def _readiness(stream: Any) -> bool | None:
    """Whether a read on ``stream``'s fd returns promptly; None if unprobeable.

    ``select.poll`` with a zero timeout — the "poll(), not select()" lesson of
    ``_engine/capabilities/shell.py``: ``select()`` carries a hard FD_SETSIZE
    ceiling that wide test sessions reach. POLLHUP/POLLERR are reported even
    for a POLLIN-only registration, so end-of-stream reads as ready and the
    read then returns ``""``, which is the truth.

    Unprobeable streams yield ``None``: no ``fileno()`` (``io.StringIO``, test
    doubles), no ``select.poll`` (Windows — its ``select()`` is sockets-only),
    or a probe that raises. Readiness is unknowable without consuming there,
    so the caller keeps the eager rule that predates this probe.
    """
    try:
        fd = stream.fileno()
        poller = select.poll()
        poller.register(fd, select.POLLIN)
        try:
            events = poller.poll(0)
        finally:
            poller.unregister(fd)
    except (OSError, ValueError, AttributeError):
        return None
    return bool(events)


def stdin_state(stream: Any | None = None) -> StdinState:
    """Classify stdin without waiting for it.

    Never blocks: a pipe that is never written is ``NO_INPUT`` in constant
    time, so ``sleep 30 | func s`` returns instead of hanging on the read.
    An unprobeable stream is ``READY`` — the eager rule this probe refines,
    where the read itself decides what is there.
    """
    stream = sys.stdin if stream is None else stream
    if stream.isatty():
        return StdinState.TTY
    ready = _readiness(stream)
    if ready is None:
        return StdinState.READY
    return StdinState.READY if ready else StdinState.NO_INPUT


def is_stdin_available() -> bool:
    """Check whether a read of stdin returns promptly.

    Returns:
        ``True`` when stdin carries input or is at end-of-stream — an
        empty-but-present stream is available and reads as ``""``;
        ``False`` for a TTY and for a pipe that is never written.
    """
    return stdin_state() is StdinState.READY


def read_stdin(encoding: str = "utf-8") -> str:
    """Read all available stdin data.

    Preconditions:
        - ``is_stdin_available()`` returns ``True``
        - Should NOT be called when stdin is a TTY (would block forever)

    Postconditions:
        - Returns complete stdin content as a string
        - Stdin buffer is consumed (cannot read again)

    Args:
        encoding: Character encoding for stdin. Currently used for
            documentation purposes — ``sys.stdin`` uses the process-level
            encoding. Defaults to ``"utf-8"``.

    Returns:
        The full content read from stdin.
    """
    return sys.stdin.read()


def iter_stdin_ndjson(encoding: str = "utf-8") -> Iterator[Any]:
    """Yield one parsed record per NDJSON line, as the line arrives.

    Iterating ``sys.stdin`` (rather than ``.read()``) is what makes a pipeline
    stream: each upstream ``out.emit(row)`` flushes a line, and this yields it
    immediately instead of waiting for the writer to close.

    Blank lines are skipped (a trailing newline is not a record). A line that is
    not valid JSON is yielded **as its raw string** rather than raising — a
    pipeline stage should not die on one malformed row it may not even use.

    Args:
        encoding: Accepted for symmetry with :func:`read_stdin`; ``sys.stdin``
            uses the process-level encoding.

    Yields:
        The parsed JSON value for each non-empty line, or the raw line when it
        does not parse.
    """
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            yield json.loads(stripped)
        except (ValueError, TypeError):
            yield stripped


def resolve_stdin_params(
    stdin_markers: dict[str, Stdin],
    cli_values: dict[str, Any],
    streaming: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Populate Stdin-marked params from stdin pipe if no CLI value provided.

    Resolution rules (in priority order):
        1. If a CLI value is provided for a param → use CLI value (explicit > implicit)
        2. If multiple Stdin params need resolution → error (ambiguous)
        3. If stdin is available (piped) and one param needs it → read stdin
        4. If stdin is TTY and a param is required (no default) → error (never block)

    Args:
        stdin_markers: Mapping of parameter name → ``Stdin`` marker for all
            parameters annotated with ``Stdin()``.
        cli_values: Mapping of parameter name → value for parameters that
            received an explicit CLI flag value. A value of ``None`` is treated
            as "not provided" (no explicit CLI value).
        streaming: Names of parameters whose annotation is an iterator/iterable.
            These receive the **lazy** NDJSON stream
            (:func:`iter_stdin_ndjson`) instead of the eager whole-of-stdin
            string, which is what lets a multi-stage pipeline flow row-wise.

    Returns:
        Dictionary of parameter name → stdin content for params that should be
        populated from piped stdin — a ``str``, or a lazy iterator for a
        ``streaming`` parameter. Empty dict if stdin is not available or all
        params already have CLI values.

    Raises:
        ValueError: If multiple Stdin-marked parameters need stdin (ambiguous —
            stdin can only feed one parameter).
    """
    # Rule 1: explicit CLI value always wins — filter to unresolved params
    unresolved = {
        name: marker
        for name, marker in stdin_markers.items()
        if name not in cli_values or cli_values[name] is None
    }

    if not unresolved:
        return {}

    # Rule 2: multiple unresolved Stdin params → ambiguous error
    if len(unresolved) > 1:
        param_names = sorted(unresolved.keys())
        msg = (
            f"Multiple Stdin-marked parameters ({param_names}) require stdin "
            "input, but stdin can only feed one parameter. Provide explicit "
            "CLI flag values for all but one."
        )
        raise ValueError(msg)

    # At this point, exactly one param needs resolution
    target_name = next(iter(unresolved))
    target_marker = unresolved[target_name]

    # Rule 3: an iterator-typed parameter gets the lazy NDJSON stream on any
    # non-TTY stdin. Reading it eagerly here would stall the pipeline until
    # the upstream closed, which is exactly what row-wise streaming exists to
    # avoid — waiting for that producer is the type's documented contract,
    # the one opt-in to waiting this resolution recognises.
    if streaming and target_name in streaming and stdin_state() is not StdinState.TTY:
        return {target_name: iter_stdin_ndjson(target_marker.encoding)}

    # Rule 4: stdin says a read returns promptly — input is already there, or
    # end-of-stream is. Deposit what it carries: the content, or "" when the
    # stream was empty but present. "" is what the user actually piped — an
    # empty document is still a document — so it lands like any other piped
    # content instead of the parameter's default silently standing in for it.
    if is_stdin_available():
        return {target_name: read_stdin(encoding=target_marker.encoding)}

    # Rule 5: nothing was piped — stdin is a terminal, or a pipe that is never
    # written (the classifier does not wait for one: `sleep 30 | func s` used
    # to hang exactly here) — resolve
    # nothing, and let the job's own default win.
    #
    # This used to `raise SystemExit(1)` here, under a comment reading "the
    # caller is responsible for determining whether the param has a default …
    # signal this so the caller can decide". It exited instead of signalling, so
    # no caller ever could, and a parameter written as
    #
    #     data: Annotated[str, Stdin()] = "nothing was piped"
    #
    # could not use the default it declared: `func shout` with no pipe and no
    # flag failed outright. A default means optional everywhere else in the
    # framework, and it means optional here (maintainer's decision, 2026-09-10).
    #
    # Returning an empty mapping is what "resolve nothing" has to look like:
    # `engine.run` drops a marked parameter it could not resolve rather than
    # passing `None`, so the signature default is what the job receives. A
    # parameter with **no** default still fails, but as the ordinary
    # missing-argument error every other parameter raises — one rule, not two.
    return {}


def stdin_markers_for(function: Callable[..., Any]) -> dict[str, Stdin]:
    """Which of ``function``'s parameters carry a ``Stdin`` marker.

    Re-derived from the signature rather than handed in, because the engine is
    now the only place that resolves stdin (run-request/T11) and it is reached
    from surfaces that never built click parameters. The click builder finds
    the same markers through ``_cli/annotation_utils.py``; both are asking the
    one question "is there a ``Stdin`` instance in this parameter's
    ``Annotated`` metadata", so the answers agree by construction.

    Annotations are read through ``resolved_hints`` so a module compiled under
    ``from __future__ import annotations`` (PEP 563) still yields live marker
    objects rather than strings. An unresolvable signature yields no markers,
    which is the same outcome as declaring none.
    """
    import typing as _typing

    from functualize._types.annotations import resolved_hints
    from functualize._types.cli_markers import Stdin as _Stdin

    markers: dict[str, Stdin] = {}
    for pname, hint in resolved_hints(function).items():
        if pname == "return" or _typing.get_origin(hint) is not _typing.Annotated:
            continue
        for meta in _typing.get_args(hint)[1:]:
            if isinstance(meta, _Stdin):
                markers[pname] = meta
                break
    return markers


def streaming_stdin_params(
    function: Callable[..., Any], stdin_markers: Mapping[str, Any]
) -> frozenset[str]:
    """Which ``Stdin``-marked params are typed as a stream (§C.2).

    A parameter annotated ``Iterator[Row]`` / ``Iterable[Row]`` /
    ``Generator[...]`` wants the lazy NDJSON stream; anything else keeps the
    eager whole-of-stdin string. ``str``/``bytes`` are iterable but are
    emphatically *not* streams, and are excluded by construction: this tests
    the annotation's generic **origin**, which is ``None`` for a bare ``str``.

    Annotations are read through ``resolved_hints`` rather than raw, so a
    module compiled under ``from __future__ import annotations`` (PEP 563) does
    not silently report every type as the string ``"Iterator[Row]"``.
    """
    import collections.abc as _abc
    import typing as _typing

    if not stdin_markers:
        return frozenset()
    try:
        from functualize._types.annotations import resolved_hints

        hints = resolved_hints(function)
    except Exception:
        return frozenset()

    stream_origins = {
        _abc.Iterator,
        _abc.Iterable,
        _abc.Generator,
        _abc.AsyncIterator,
        _abc.AsyncIterable,
    }
    streaming: set[str] = set()
    for pname in stdin_markers:
        hint = hints.get(pname)
        if hint is None:
            continue
        # Unwrap Annotated[...] so `Annotated[Iterator[Row], Stdin()]` is seen.
        if _typing.get_origin(hint) is _typing.Annotated:
            hint = _typing.get_args(hint)[0]
        if _typing.get_origin(hint) in stream_origins:
            streaming.add(pname)
    return frozenset(streaming)
