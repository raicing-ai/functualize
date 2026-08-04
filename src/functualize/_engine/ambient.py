"""Ambient constructs — plugin-provided live constructs that render by default.

Two tiers reach a live zone:

- **Explicit** — the job asks for it: ``live.add(FlowVizConstruct())``.
- **Ambient** — a plugin registered it once at boot, and it renders for every
  eligible job with no job-author code::

      app.register_ambient_construct(
          FlowVizConstruct,
          predicate=lambda d: d.uses_invoke,
      )

This module owns the *evaluation* half: given the app and the job about to run,
which ambient constructs should be pre-mounted. Both live zones (``StdoutSurface``
and the TUI's ``PanelLiveZone``) call :func:`resolve_ambient_constructs`, so the
two surfaces cannot drift on predicates or suppression.

Registration stores a **factory** rather than an instance so each run gets fresh
state — a tree from the previous job must not bleed into the next one.

Suppression has four levers, checked here in order of specificity:

===========================  =========================================
Lever                        Mechanism
===========================  =========================================
Off globally                 plugin skips registration (its own config)
Off for a project            ``[live] suppress = ["flow-viz"]``
Off for a job (declarative)  ``@job(suppress_live=["flow-viz"])``
Off for a run (imperative)   ``live.suppress("flow-viz")``
===========================  =========================================
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = [
    "AmbientEntry",
    "resolve_ambient_constructs",
    "suppressed_names",
]


@dataclass(frozen=True)
class AmbientEntry:
    """One registered ambient construct.

    Attributes:
        factory: Zero-arg callable returning a fresh construct per run.
        name: Identifier used for suppression. Defaults to the factory's name.
        predicate: Optional ``(descriptor) -> bool`` gate. None means always-on.
    """

    factory: Callable[[], Any]
    name: str
    predicate: Callable[[Any], bool] | None = None

    def eligible_for(self, descriptor: Any) -> bool:
        """Whether this entry should render for ``descriptor``.

        A predicate that raises is treated as "not eligible" and logged — a
        buggy plugin predicate must not break job execution.
        """
        if self.predicate is None:
            return True
        try:
            return bool(self.predicate(descriptor))
        except Exception:
            logger.warning(
                "Ambient construct %r predicate raised; treating as not eligible",
                self.name,
                exc_info=True,
            )
            return False


def suppressed_names(app: Any, descriptor: Any = None) -> set[str]:
    """Collect suppressed ambient-construct names for a run.

    Merges the project-level ``[live] suppress`` setting with the job's own
    ``suppress_live`` declaration. The imperative ``live.suppress(...)`` lever
    is applied later, by the zone, since it happens after the job body starts.
    """
    names: set[str] = set()

    # Project config: [live] suppress = ["flow-viz", ...]
    try:
        settings = getattr(app, "settings", None)
        if settings is not None:
            configured = settings.get("live.suppress", None)
            if isinstance(configured, str):
                names.update(
                    part.strip() for part in configured.split(",") if part.strip()
                )
            elif isinstance(configured, (list, tuple, set)):
                names.update(str(item) for item in configured)
    except Exception:
        logger.debug("Could not read [live] suppress setting", exc_info=True)

    # Job declaration: @job(suppress_live=[...])
    declared = getattr(descriptor, "suppress_live", None)
    if isinstance(declared, str):
        names.add(declared)
    elif isinstance(declared, (list, tuple, set)):
        names.update(str(item) for item in declared)

    return names


def resolve_ambient_constructs(app: Any, descriptor: Any = None) -> list[Any]:
    """Instantiate the ambient constructs that should render for this run.

    Returns fresh construct instances, in registration order, for every entry
    whose predicate passes and whose name is not suppressed. Never raises: a
    plugin whose factory blows up costs its own construct, not the job.
    """
    entries = getattr(app, "_ambient_constructs", None)
    if not entries:
        return []

    suppressed = suppressed_names(app, descriptor)
    constructs: list[Any] = []
    for entry in entries:
        if entry.name in suppressed:
            continue
        if not entry.eligible_for(descriptor):
            continue
        try:
            constructs.append(entry.factory())
        except Exception:
            logger.warning(
                "Ambient construct %r factory raised; skipping it",
                entry.name,
                exc_info=True,
            )
    return constructs


def has_eligible_ambient(app: Any, descriptor: Any = None) -> bool:
    """Whether any ambient construct would render for this job.

    Lets the CLI decide to create a ``StdoutSurface`` for a job that does not
    itself declare ``live: Live`` — without this, an ambient construct would
    have no zone to render into on a plain ``func <job>`` run.
    """
    entries = getattr(app, "_ambient_constructs", None)
    if not entries:
        return False
    suppressed = suppressed_names(app, descriptor)
    return any(
        entry.name not in suppressed and entry.eligible_for(descriptor)
        for entry in entries
    )
