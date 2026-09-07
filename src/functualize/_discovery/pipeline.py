"""Resolution pipeline for the Provider/Transform architecture.

Orchestrates the Provider → Transform → Registry flow. Maintains
registration order for deterministic, reproducible behavior.

Only imports from `_types/`, `_primitives/`, `_events/`, and Python stdlib.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from functualize._types import JobDescriptor, JobProvider, JobTransform
from functualize._types.discovery_report import DiscoveryFailure, job_name_collision

if TYPE_CHECKING:
    from functualize._events import EventBus

logger = logging.getLogger(__name__)


def _module_of(descriptor: JobDescriptor) -> str:
    """Best available module name for a descriptor, for a diagnostic.

    A descriptor built by a directory scan carries `module_path`. One built by
    hand — `StaticProvider` over plain callables, a plugin's own provider —
    often does not, and then the live function still knows where it came from.
    """
    if descriptor.module_path:
        return descriptor.module_path
    return getattr(descriptor.function, "__module__", "") or "<provider>"


def _missing_protocol_members(obj: Any, required: list[str]) -> list[str]:
    """Return list of missing methods/attributes from an object."""
    missing = []
    for member in required:
        if not hasattr(obj, member):
            missing.append(member)
        elif not callable(getattr(obj, member, None)):
            missing.append(f"{member} (not callable)")
    return missing


@dataclass
class ProviderEntry:
    """A registered provider with its provider-level transforms."""

    provider: JobProvider
    transforms: list[JobTransform] = field(default_factory=list)


class ResolutionPipeline:
    """Orchestrates Provider → Transform → Registry resolution.

    Maintains registration order for deterministic behavior. Optionally
    emits discovery events via EventBus for observability.

    Args:
        event_bus: Optional EventBus for emitting discovery lifecycle events.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._providers: list[ProviderEntry] = []
        self._app_transforms: list[JobTransform] = []
        self._event_bus = event_bus
        # Name collisions the last `resolve_all` resolved. Read by
        # `_cli/info.py` off the pipeline, the way it already reads
        # `_providers` — a provider assembled by hand (`StaticProvider`, a
        # plugin's own) has no `discovery_failures` of its own to report
        # through, so the pipeline is the only place these can surface.
        self._collisions: list[DiscoveryFailure] = []

    def add_provider(
        self,
        provider: JobProvider,
        transforms: list[JobTransform] | None = None,
    ) -> None:
        """Register a job provider with optional provider-scoped transforms.

        Args:
            provider: A JobProvider instance to register.
            transforms: Optional list of JobTransform instances to apply
                only to this provider's jobs.

        Raises:
            TypeError: If provider does not satisfy JobProvider protocol.
            TypeError: If any transform does not satisfy JobTransform protocol.
        """
        if not isinstance(provider, JobProvider):
            missing = _missing_protocol_members(provider, ["list_jobs", "get_job"])
            raise TypeError(
                f"Expected a JobProvider instance, got {type(provider).__name__}. "
                f"Missing methods/attributes: {missing}"
            )
        if transforms:
            for t in transforms:
                if not isinstance(t, JobTransform):
                    missing = _missing_protocol_members(
                        t, ["transform_list", "transform_get"]
                    )
                    raise TypeError(
                        f"Expected a JobTransform instance, got {type(t).__name__}. "
                        f"Missing methods/attributes: {missing}"
                    )
        self._providers.append(ProviderEntry(provider, transforms or []))

    def add_transform(self, transform: JobTransform) -> None:
        """Register an app-level job transform.

        App-level transforms apply to ALL jobs from ALL providers after
        provider-level transforms and merging are complete.

        Args:
            transform: A JobTransform instance to register.

        Raises:
            TypeError: If transform does not satisfy JobTransform protocol.
        """
        if not isinstance(transform, JobTransform):
            missing = _missing_protocol_members(
                transform, ["transform_list", "transform_get"]
            )
            raise TypeError(
                f"Expected a JobTransform instance, got {type(transform).__name__}. "
                f"Missing methods/attributes: {missing}"
            )
        self._app_transforms.append(transform)

    @property
    def collisions(self) -> list[DiscoveryFailure]:
        """Job-name collisions resolved by the last :meth:`resolve_all`."""
        return list(self._collisions)

    def resolve_all(self) -> list[JobDescriptor]:
        """Execute full list_jobs resolution pipeline.

        Pipeline order:
        1. Each provider's list_jobs() → provider-level transforms in order
        2. Concatenate results from all providers
        3. Resolve duplicate names — first claimant wins, rest reported
        4. Apply app-level transforms in registration order

        A duplicate name used to raise ``ValueError`` here, and the caller in
        ``_app/boot.py`` catches that and returns — so **every** job vanished,
        not just the collider. Measured: an app declaring ``build_wheel`` and
        ``buildWheel`` through ``JobSources(functions=[...])`` booted with
        ``get_jobs() == []`` and an empty registry, behind one logged line.
        That is the third distinct answer this codebase gave to "two functions
        want one job name", and the worst of them.

        Provider order is a declared precedence — ``boot_standard`` adds the
        directory provider before the static one, and which side a name lands
        on is load-bearing — so here the **first** claimant wins, unlike the
        within-a-scan rule where order is alphabetical and arbitrary and the
        pre-existing last-wins outcome was preserved instead.

        Returns:
            Final list of job descriptors after all transforms.
        """
        start = time.perf_counter()

        # Phase 1: Each provider's list_jobs → provider-level transforms
        all_jobs: list[JobDescriptor] = []
        seen: dict[str, JobDescriptor] = {}
        self._collisions = []

        for entry in self._providers:
            provider_jobs = list(entry.provider.list_jobs())

            # Apply provider-level transforms in order
            current: Sequence[JobDescriptor] = provider_jobs
            for transform in entry.transforms:
                current = transform.transform_list(current)

            for job in current:
                incumbent = seen.get(job.name)
                if incumbent is not None:
                    if incumbent is not job:
                        self._collisions.append(
                            job_name_collision(
                                canonical_name=job.name,
                                kept_module=_module_of(incumbent),
                                kept_python_name=incumbent.python_name or job.name,
                                dropped_module=_module_of(job),
                                dropped_python_name=job.python_name or job.name,
                                dropped_path=job.source_file or "<provider>",
                            )
                        )
                    continue
                seen[job.name] = job
                all_jobs.append(job)

        # Phase 2: App-level transforms in pipeline order
        current_list: Sequence[JobDescriptor] = all_jobs
        for transform in self._app_transforms:
            current_list = transform.transform_list(current_list)

        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms > 200:
            logger.warning(
                "Resolution pipeline took %.1fms (%d providers)",
                elapsed_ms,
                len(self._providers),
            )

        result = list(current_list)

        # Emit discovery completed event if bus is available
        if self._event_bus is not None:
            self._event_bus.emit(
                "discovery.pipeline.resolved",
                job_count=len(result),
                provider_count=len(self._providers),
                elapsed_ms=elapsed_ms,
            )

        return result

    def resolve_one(self, name: str) -> JobDescriptor | None:
        """Execute get_job resolution for a single name.

        Queries providers in registration order, stops at first non-None.
        Applies provider-level then app-level transform_get chains.

        Args:
            name: The job name to look up.

        Returns:
            The resolved JobDescriptor or None if not found.
        """
        result: JobDescriptor | None = None

        for entry in self._providers:
            raw = entry.provider.get_job(name)
            if raw is not None:
                # Apply provider-level transform_get chain
                current: JobDescriptor | None = raw
                for transform in entry.transforms:
                    current = transform.transform_get(name, current)
                    if current is None:
                        break
                result = current
                break

        if result is None:
            return None

        # Apply app-level transform_get chain
        for transform in self._app_transforms:
            result = transform.transform_get(name, result)
            if result is None:
                return None

        return result

    @property
    def provider_count(self) -> int:
        """Number of registered providers."""
        return len(self._providers)

    @property
    def transform_count(self) -> int:
        """Number of registered app-level transforms."""
        return len(self._app_transforms)
