"""Duck-type detection for ``GroupOptions`` subclasses (S6a).

The single definition of "looks like a bound group-options declaration",
used by the job scan's ``exec_module`` pass so a group's flags are cached
alongside the jobs found in the same sweep.

Lives in ``_primitives/`` (stdlib-only) for the same reason as
``display_detection``: ``_discovery`` runs it inside the scan and must not
pull ``_types``/pydantic to answer "is this a group-options class?". The
check is therefore structural — a non-empty ``__group_path__`` plus pydantic's
``model_fields`` — never an ``issubclass`` against the real base.
"""

from __future__ import annotations

from typing import Any


def is_group_options_class(obj: Any) -> bool:
    """Duck-type check for a ``GroupOptions`` subclass bound to a group.

    A **non-empty** ``__group_path__`` is required, which is exactly what
    excludes the ``GroupOptions`` **base class** itself: a module that does
    ``from functualize.job import GroupOptions`` puts the base in its
    namespace, and the base satisfies every other check by design — so
    without this it would be discovered as a phantom declaration bound to the
    empty group. (The same trap ``is_display_provider`` guards with a
    non-empty ``display_id``.)
    """
    if not isinstance(obj, type):
        return False
    path = getattr(obj, "__group_path__", None)
    if not (isinstance(path, str) and path.strip()):
        return False
    return hasattr(obj, "model_fields")


def is_group_options_subclass(obj: Any) -> bool:
    """Duck-type check for *any* class in the ``GroupOptions`` hierarchy.

    Unlike :func:`is_group_options_class`, this does **not** require a bound
    group path, so it also matches an abstract intermediate. Used to keep a
    ``GroupOptions`` parameter from being mistaken for the job's own config
    class: such a parameter is an injection point for the *group's* flags,
    and expanding its fields as job-level CLI options would put the same
    field behind two competing flags.
    """
    if not isinstance(obj, type):
        return False
    return isinstance(getattr(obj, "__group_path__", None), str) and hasattr(
        obj, "model_fields"
    )


def find_group_options(module: Any) -> list[type]:
    """Return the ``GroupOptions`` subclasses *defined in* a module.

    Runs on an already-executed module object, so the job scan can call it in
    the same pass as job extraction.

    Only classes whose ``__module__`` matches the module are returned. A class
    merely *imported* into the namespace (``from ._group import DeployOptions``)
    is skipped — otherwise the same declaration would be discovered once per
    importing module and trip the "one declaration per group path" duplicate
    check with a phantom conflict. This mirrors the ``inspect.getmodule(attr)
    is module`` test the job sweep applies to functions.
    """
    found: list[type] = []
    module_name = getattr(module, "__name__", None)
    for name in dir(module):
        obj = getattr(module, name, None)
        if not isinstance(obj, type) or not is_group_options_class(obj):
            continue
        if getattr(obj, "__module__", None) != module_name:
            continue
        found.append(obj)
    return found
