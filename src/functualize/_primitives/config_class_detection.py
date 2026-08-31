"""The single definition of "which parameter is this job's config class".

There were three copies of this rule — the cold path (`_discovery/registry`),
the warm path (`_discovery/lazy_wrapper`) and the single-file peer path
(`_cli/main`) — and they had drifted three different ways. Two of the three
disagreed with the third on signatures the design corpus uses everywhere, and
the divergence was invisible from any one path: a job that ran cold failed
warm, and a `GroupOptions` parameter leaked the group's flags into the job's
own ``--help`` on the peer path alone.

So the rule lives here, once, and the three sites delegate. A future
divergence is not merely fixed, it is unavailable.

Lives in `_primitives/` because both dependencies are legal from here:
`resolved_hints` is `_types`, and `is_group_options_subclass` is a peer
module. pydantic is imported lazily inside the function, the same way
``fingerprint`` does it — a hard dependency, already imported at boot, but not
something `_primitives` pulls at import time.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel

__all__ = ["detect_config_class"]


def detect_config_class(func: Callable[..., Any]) -> type[BaseModel] | None:
    """The job's config class, or None.

    A job's config class is the type of a **parameter** whose resolved
    annotation is a ``BaseModel`` subclass that is neither ``BaseModel``
    itself, nor a ``GroupOptions`` subclass, nor wrapped in ``Annotated[...]``.

    Three exclusions, each of which one of the three former copies got wrong:

    - **A return annotation is never config.** The hints mapping carries a
      ``'return'`` key, so iterating its *values* takes a pydantic return type
      as the job's config and hands the job a validated envelope it never
      asked for. Iterate parameters instead.
    - **An ``Annotated[...]`` parameter is never config.** Hints must be
      resolved with ``include_extras=True``; without it
      ``Annotated[Envelope, FromJob("upstream")]`` collapses to bare
      ``Envelope``, which *is* a ``BaseModel`` subclass and is returned as the
      config class. ``resolved_hints`` passes ``include_extras=True``, and an
      ``Annotated[...]`` object is not a ``type``, so the ``isinstance`` check
      below excludes it. Both halves are load-bearing; either alone is
      insufficient.
    - **A ``GroupOptions`` parameter is never config.** It carries the
      *group's* flags, not this job's config fields.

    Args:
        func: The job function to inspect.

    Returns:
        The config class if one parameter declares it, None otherwise.
    """
    from pydantic import BaseModel

    from functualize._primitives.group_options_detection import (
        is_group_options_subclass,
    )
    from functualize._types.annotations import resolved_hints

    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return None

    # Resolved, not raw: under PEP 563 the annotation is the string
    # "MyConfig", which is not a type, so no config class would ever be
    # detected and the job would run with no config resolution at all.
    # `resolved_hints` returns {} rather than raising when hints cannot be
    # resolved, so the `.get(name, param.annotation)` below degrades to the
    # raw annotation instead of losing the job.
    hints = resolved_hints(func)

    for name, param in sig.parameters.items():
        annotation = hints.get(name, param.annotation)
        if annotation is inspect.Parameter.empty:
            continue
        if (
            isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
            and annotation is not BaseModel
            and not is_group_options_subclass(annotation)
        ):
            return annotation
    return None
