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

if TYPE_CHECKING:
    from functualize._events import EventBus

logger = logging.getLogger(__name__)


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

    def resolve_all(self) -> list[JobDescriptor]:
        """Execute full list_jobs resolution pipeline.

        Pipeline order:
        1. Each provider's list_jobs() → provider-level transforms in order
        2. Concatenate results from all providers
        3. Detect duplicate names across providers (raise ValueError)
        4. Apply app-level transforms in registration order

        Returns:
            Final list of job descriptors after all transforms.

        Raises:
            ValueError: If duplicate job names are detected after provider-level
                transforms across different providers.
        """
        start = time.perf_counter()

        # Phase 1: Each provider's list_jobs → provider-level transforms
        all_jobs: list[JobDescriptor] = []
        seen_names: dict[str, int] = {}  # name → provider index

        for idx, entry in enumerate(self._providers):
            provider_jobs = list(entry.provider.list_jobs())

            # Apply provider-level transforms in order
            current: Sequence[JobDescriptor] = provider_jobs
            for transform in entry.transforms:
                current = transform.transform_list(current)

            # Check for duplicates across providers
            for job in current:
                if job.name in seen_names:
                    conflicting_idx = seen_names[job.name]
                    raise ValueError(
                        f"Duplicate job name '{job.name}' from provider index "
                        f"{conflicting_idx} and {idx}"
                    )
                seen_names[job.name] = idx
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
