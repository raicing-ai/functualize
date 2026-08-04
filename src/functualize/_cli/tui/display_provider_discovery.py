"""Display-provider discovery for the inline TUI.

Displays reach the TUI by three paths:

1. **Cache-flagged modules** — the job scan detects DisplayProvider classes
   in the modules it imports and records them in the discovery cache's
   ``displays`` section, so displays can co-locate with jobs. The TUI
   imports only the flagged modules.
2. **Project-local** — a ``displays.py`` in the current working directory,
   duck-type scanned. The zero-ceremony / cold-boot fallback path.
3. **Installed packages** — the ``functualize.displays`` entry-point group,
   so a pip-installed package can ship displays. Without this, ``register_display``
   was reachable only from the CWD scan and installed displays had no discovery
   path at all.

Discovery is deliberately eager at TUI startup (a display must be instantiated
to render) and therefore does **not** run on a warm CLI boot — nothing here is
imported unless the TUI launches. The duck-type check itself lives in
``functualize._primitives.display_detection`` (reached here through the public
``functualize.app.utils`` re-exports) so the job scan shares it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize.app.utils import find_display_providers, is_display_provider

if TYPE_CHECKING:
    from functualize._cli.tui.app import FunctualizeInlineTUI

__all__ = [
    "find_display_providers",
    "is_display_provider",
    "register_display_providers",
]

_REQUIRED_DISPLAY_PROVIDER_ATTRS = (
    "display_id",
    "display_title",
    "display_priority",
    "should_show",
    "compose_display",
)

#: Entry-point group installed packages use to publish displays.
_DISPLAY_ENTRY_POINT_GROUP = "functualize.displays"


def register_display_providers(app: FunctualizeInlineTUI) -> None:
    """Discover and register DisplayProviders with the DisplaySlot."""
    _register_entry_point_displays(app)
    _register_cached_displays(app)
    _register_cwd_displays(app)


def _registered_display_ids(app: FunctualizeInlineTUI) -> set[str]:
    """The display_ids already registered with the DisplaySlot.

    Used to dedupe across discovery paths — e.g. a ``displays.py`` that also
    sits inside a scanned jobs directory reaches the slot once, not twice.
    """
    try:
        return {d.display_id for d in app._display_slot._ring._displays}
    except (AttributeError, TypeError):
        return set()


def _register_entry_point_displays(app: FunctualizeInlineTUI) -> None:
    """Register displays published by installed packages.

    An entry point may resolve to either a provider class or a zero-arg
    callable returning one, so a package can decide lazily.
    """
    try:
        from importlib.metadata import entry_points

        found = entry_points(group=_DISPLAY_ENTRY_POINT_GROUP)
    except Exception as exc:
        app.log.warning(
            f"register_display_providers: could not read "
            f"{_DISPLAY_ENTRY_POINT_GROUP} entry points "
            f"({type(exc).__name__}): {exc}"
        )
        return

    for entry_point in found:
        try:
            loaded: Any = entry_point.load()
            instance: Any = loaded() if callable(loaded) else loaded
            if not all(
                hasattr(instance, attr) for attr in _REQUIRED_DISPLAY_PROVIDER_ATTRS
            ):
                app.log.warning(
                    f"register_display_providers: entry point "
                    f"{entry_point.name!r} is not a DisplayProvider, skipping"
                )
                continue
            app._display_slot.register_display(instance)
        except Exception as exc:
            # Loading a third-party entry point executes arbitrary code; one
            # broken package must not cost the others their displays.
            app.log.warning(
                f"register_display_providers: failed to load entry point "
                f"{entry_point.name!r} ({type(exc).__name__}): {exc}"
            )


def _register_cached_displays(app: FunctualizeInlineTUI) -> None:
    """Register displays from the discovery cache's ``displays`` section.

    The job scan already imported these modules once and recorded which of
    them define DisplayProvider classes — so the TUI imports exactly the
    flagged modules and nothing else. A missing/stale cache is not an error:
    the CWD ``displays.py`` fallback still runs, and the next scan rebuilds
    the section.
    """
    try:
        import importlib.util
        import sys

        from functualize.app.utils import (
            read_display_modules_from_cache,
            resolve_cache_path,
        )

        cache_path = resolve_cache_path(Path.cwd())
        flagged = read_display_modules_from_cache(cache_path)
        if not flagged:
            return

        registered = _registered_display_ids(app)
        for source_file, class_names in flagged:
            source_path = Path(source_file)
            if not source_path.is_file():
                continue
            try:
                module_key = f"_functualize_display_mod_.{source_path.stem}"
                spec = importlib.util.spec_from_file_location(module_key, source_path)
                if not spec or not spec.loader:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_key] = module
                spec.loader.exec_module(module)
            except Exception as exc:
                # Importing a user module executes arbitrary code; one broken
                # module must not cost the others their displays.
                app.log.warning(
                    f"register_display_providers: failed to import cached "
                    f"display module {source_file!r} ({type(exc).__name__}): {exc}"
                )
                continue

            for class_name in class_names:
                obj = getattr(module, class_name, None)
                if not (isinstance(obj, type) and is_display_provider(obj)):
                    continue
                display_id = getattr(obj, "display_id", "")
                if display_id in registered:
                    continue
                try:
                    instance: Any = obj()
                    app._display_slot.register_display(instance)
                    registered.add(display_id)
                except Exception as exc:
                    app.log.warning(
                        f"register_display_providers: failed to instantiate/"
                        f"register {class_name!r} from cache "
                        f"({type(exc).__name__}): {exc}"
                    )
    except Exception as exc:
        # The cache path is best-effort; any failure falls through to the
        # CWD displays.py scan.
        app.log.warning(
            f"register_display_providers: cached display discovery failed "
            f"({type(exc).__name__}): {exc}"
        )


def _register_cwd_displays(app: FunctualizeInlineTUI) -> None:
    """Scan for a 'displays.py' in the CWD and register what it defines.

    If found, instantiates any classes with the required DisplayProvider
    attributes and registers them with the DisplaySlot.
    """
    try:
        import importlib.util
        import sys

        cwd = Path.cwd()
        displays_path = cwd / "displays.py"
        if not displays_path.exists():
            return

        spec = importlib.util.spec_from_file_location("_displays_mod", displays_path)
        if not spec or not spec.loader:
            return

        module = importlib.util.module_from_spec(spec)
        sys.modules["_displays_mod"] = module
        spec.loader.exec_module(module)

        registered = _registered_display_ids(app)
        for obj in find_display_providers(module):
            name = obj.__name__
            try:
                if getattr(obj, "display_id", "") in registered:
                    continue
                instance = obj()
                app._display_slot.register_display(instance)
            except Exception as exc:
                # Instantiating/registering a user-supplied DisplayProvider
                # class executes arbitrary code, so any exception type is
                # possible; this is a best-effort, optional feature — log
                # and continue with the remaining classes.
                app.log.warning(
                    f"register_display_providers: failed to instantiate/"
                    f"register {name!r} ({type(exc).__name__}): {exc}"
                )
                continue
    except Exception as exc:
        # Loading a user-supplied displays.py executes arbitrary code, so
        # any exception type is possible here; this is a best-effort,
        # optional feature — log and continue without registering displays.
        app.log.warning(
            f"register_display_providers: failed to load displays.py "
            f"({type(exc).__name__}): {exc}"
        )
