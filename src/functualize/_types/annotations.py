"""Reading parameter annotations that may or may not be strings.

Under ``from __future__ import annotations`` (PEP 563) every annotation in a
module is stored as a *string*, not the type object it names. Code that reads
``inspect.Parameter.annotation`` directly and tests it with ``isinstance(x,
type)`` or ``get_origin(x)`` therefore matches nothing in such a module — and
matches nothing *silently*, because a string annotation is a perfectly valid
annotation. The failure surfaces far away: a config class that is never
detected, a ``Field()`` constraint that stops being enforced, a CLI option that
is never generated.

Every site that decides something from an annotation must go through
:func:`resolved_hints`, and fall back to the raw annotation only for names it
does not answer::

    hints = resolved_hints(func)
    for name, param in inspect.signature(func).parameters.items():
        annotation = hints.get(name, param.annotation)

The fallback matters: ``get_type_hints`` is all-or-nothing, so one
``TYPE_CHECKING``-only import in a module makes it raise for the whole
function. Returning ``{}`` and letting callers fall back keeps such a function
working exactly as well as it did before, rather than making an unresolvable
hint on one parameter break the others.

Lives in ``_types/`` — the lowest layer — because discovery, the engine, the
CLI *and* value objects like ``FromJob`` all need it, and ``_types`` is the
only package every one of them is allowed to import. (It began in
``_primitives``, which was one layer too high: ``_types`` may not import
``_primitives``, so a value object could not have used it.)
"""

from __future__ import annotations

import typing
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["resolved_hints"]


def resolved_hints(func: Callable[..., Any]) -> dict[str, Any]:
    """Type hints for ``func`` with PEP 563 string annotations evaluated.

    ``include_extras=True`` keeps ``Annotated[...]`` metadata intact, which is
    what carries ``Field()``, ``Arg``, ``Option``, and the other markers.

    Returns:
        Parameter (and ``return``) names mapped to live type objects. Empty
        when hints cannot be resolved at all — an unimportable forward
        reference, a name only defined under ``TYPE_CHECKING``, a callable
        with no usable module globals. Callers fall back to the raw
        annotation rather than treating this as an error.
    """
    try:
        return typing.get_type_hints(func, include_extras=True)
    except Exception:
        return {}
