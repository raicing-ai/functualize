"""Stdin pipe detection and reading for Stdin-marked parameters.

Handles non-blocking stdin detection, content reading, and resolution of
``Stdin()``-marked function parameters from piped input.

Public API:
- ``is_stdin_available`` — check if stdin has piped data (non-TTY)
- ``read_stdin`` — read all available stdin data
- ``iter_stdin_ndjson`` — lazily yield NDJSON records as they arrive
- ``resolve_stdin_params`` — populate Stdin-marked params from pipe

A parameter typed as an iterator/iterable (``Iterator[dict]``) is fed the *lazy*
NDJSON stream, so a three-stage pipeline (``func extract | func transform |
func load``) flows row-wise instead of each stage blocking until its upstream
closes. Anything else keeps the eager whole-of-stdin string.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

    from functualize.job.markers import Stdin

__all__ = [
    "is_stdin_available",
    "iter_stdin_ndjson",
    "read_stdin",
    "resolve_stdin_params",
]


def is_stdin_available() -> bool:
    """Check if stdin has piped data (non-TTY).

    Returns:
        ``True`` if stdin is not a TTY (i.e., data is piped in),
        ``False`` if stdin is an interactive terminal.
    """
    return not sys.stdin.isatty()


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
        SystemExit: If stdin is a TTY and a required parameter has no default
            value and no CLI value (would block forever waiting for input).
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

    # Rule 3: stdin available (piped) → hand over the stream
    if is_stdin_available():
        # An iterator-typed parameter gets the lazy NDJSON stream: reading it
        # eagerly here would stall the pipeline until the upstream closed,
        # which is exactly what row-wise streaming exists to avoid.
        if streaming and target_name in streaming:
            return {target_name: iter_stdin_ndjson(target_marker.encoding)}
        content = read_stdin(encoding=target_marker.encoding)
        return {target_name: content}

    # Rule 4: stdin is TTY → cannot read without blocking
    # The caller is responsible for determining whether the param has a default.
    # If we reach here, stdin is TTY and there's an unresolved param.
    # Signal this so the caller can decide based on default availability.
    sys.stderr.write(
        f"Error: Parameter '{target_name}' requires piped input or an explicit "
        f"flag value. Stdin is a terminal — refusing to block for input.\n"
    )
    raise SystemExit(1)
