"""Duck-type detection for DisplayProvider classes.

The single definition of "looks like a display", shared by every discovery
path — the TUI's ``displays.py`` CWD scan, the ``functualize.displays``
entry-point path, and the job scan's ``exec_module`` pass (which caches the
result so the TUI imports only flagged modules on a warm boot).

Lives in ``_primitives/`` (stdlib-only) because ``_discovery`` runs it inside
the scan and may not import ``_cli``; the TUI reaches it through the public
re-exports in ``functualize.app.utils``.
"""

from __future__ import annotations

from typing import Any

REQUIRED_DISPLAY_PROVIDER_ATTRS = (
    "display_id",
    "display_title",
    "display_priority",
    "should_show",
    "compose_display",
)


def is_display_provider(obj: Any) -> bool:
    """Duck-type check for a DisplayProvider class or instance.

    Only the five required attributes are checked — everything else
    (``refresh``, ``refresh_interval``, ``linked_jobs``,
    ``get_available_actions``) is optional and read with a default at the
    point of use.

    A non-empty ``display_id`` is required, which is also what excludes the
    ``functualize.ui.Display`` **base class** itself: a module that does
    ``from functualize.ui import Display`` puts the base in its namespace, and
    the base satisfies every other attribute by design — so without this it
    would be discovered and registered as a phantom display whose
    ``compose_display`` raises.
    """
    if not all(hasattr(obj, attr) for attr in REQUIRED_DISPLAY_PROVIDER_ATTRS):
        return False
    display_id = getattr(obj, "display_id", "")
    return isinstance(display_id, str) and bool(display_id.strip())


def find_display_providers(module: Any) -> list[type]:
    """Return the DisplayProvider classes defined in a module.

    Runs on an already-executed module object, so it is cheap enough for the
    job scan to call in the same pass as job extraction — letting displays
    co-locate with jobs instead of requiring a dedicated ``displays.py``.
    """
    found: list[type] = []
    for name in dir(module):
        obj = getattr(module, name, None)
        if isinstance(obj, type) and is_display_provider(obj):
            found.append(obj)
    return found
