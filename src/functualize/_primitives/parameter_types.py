"""What a job parameter's annotation means: a value, or a dependency.

A job signature mixes three kinds of parameter, and every layer that walks one
has to tell them apart:

* **injected capabilities** — ``log: Log``, ``sh: Shell``. Supplied by the
  engine, never a CLI argument. Listed once in ``capability_names.py``.
* **values** — ``rows: int``, ``to: Path``. Supplied by the caller, converted
  from a string.
* **dependencies** — ``db: Database``. Resolved from the DI registry, and an
  error if nothing registered one.

The boot-time DI gate used to separate the last two by asking "is it a
builtin?", which is not the same question. ``pathlib.Path`` is not a builtin,
so a job taking a directory — close to the most ordinary thing a task runner
does — failed with ``No provider for Path``, and because that gate raises for
the whole app, **one such job took down every command on a cold boot**,
including ``builtin info``. The same held for ``UUID``, ``date``, ``Decimal``
and any ``Enum``, and writing ``Annotated[Path, Option(...)]`` — the marker
that says "this is a command-line option" — did not help.

So the question gets an explicit answer instead of a proxy for one. This is a
**list**, not a rule: a type that is neither listed nor explicitly marked stays
a dependency, because inverting that default would turn a forgotten provider
into a silent CLI flag — trading a loud failure for a quiet one.

Matched by name, like ``INJECTED_PARAM_TYPE_NAMES`` and for the same reason: a
layer forbidden from importing a type still has to classify it. ``Enum`` is the
one exception, checked by subclass, because those names are user-defined.
"""

from __future__ import annotations

import enum
from typing import Annotated, Any, get_args, get_origin

__all__ = [
    "CLI_MARKER_TYPE_NAMES",
    "CLI_VALUE_TYPE_NAMES",
    "has_explicit_cli_marker",
    "is_cli_value_type",
]

#: Standard-library value types a caller can supply as a string on any surface.
#:
#: Deliberately conservative: each has one obvious textual form, so accepting
#: it costs no ambiguity. Builtins (``str``, ``int``, ``float``, ``bool``) are
#: not repeated here — the callers skip those by module, which is correct for
#: them and was only ever wrong as a stand-in for this list.
#:
#: Widening this set is close to a one-way door. A type that becomes a value
#: cannot later become injectable without breaking every job that passes one on
#: the command line, so the escape hatch for anything else is the explicit
#: marker below rather than a longer list.
CLI_VALUE_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "Path",
        "PosixPath",
        "WindowsPath",
        "PurePath",
        "UUID",
        "date",
        "datetime",
        "time",
        "timedelta",
        "Decimal",
    }
)

#: Markers by which an author declares a parameter to be caller-supplied.
#:
#: Matched by class name for the same reason the type names are: ``_engine``
#: and ``_discovery`` may not import the CLI marker module, and
#: ``_discovery/providers.py`` already classifies these markers this way.
CLI_MARKER_TYPE_NAMES: frozenset[str] = frozenset({"Arg", "Option", "Stdin"})


def _base_type(annotation: Any) -> Any:
    """The annotation with any ``Annotated[...]`` wrapper removed."""
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        return args[0] if args else annotation
    return annotation


def is_cli_value_type(annotation: Any) -> bool:
    """Is this annotation a value the caller supplies, rather than a dependency?

    True for the listed standard-library types and for any ``Enum`` subclass,
    whose members already publish as ``choices`` on every surface.

    Unwraps ``Annotated[...]`` first, so ``Annotated[Path, Option()]`` answers
    on ``Path`` rather than on the wrapper.
    """
    base = _base_type(annotation)
    if not isinstance(base, type):
        return False
    if issubclass(base, enum.Enum):
        return True
    return base.__name__ in CLI_VALUE_TYPE_NAMES


def has_explicit_cli_marker(annotation: Any) -> bool:
    """Did the author state that this parameter is caller-supplied?

    ``Annotated[T, Arg()]``, ``Annotated[T, Option()]`` and
    ``Annotated[T, Stdin()]`` say so in as many words. An explicit statement
    outranks the type list — which is what keeps that list a convenience rather
    than a ceiling on what a job may accept.
    """
    if get_origin(annotation) is not Annotated:
        return False
    return any(
        type(meta).__name__ in CLI_MARKER_TYPE_NAMES
        for meta in get_args(annotation)[1:]
    )
