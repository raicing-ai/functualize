"""Machine-readable registry of event metadata for plugin introspection."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize._events._obs_types import EventMetadata


class EventCatalog:
    """Machine-readable registry of event metadata for plugin introspection."""

    def __init__(self) -> None:
        self._entries: dict[str, EventMetadata] = {}

    def register(self, metadata: EventMetadata) -> None:
        """Register event metadata. Overwrites if event_name already exists."""
        self._entries[metadata.event_name] = metadata

    def contains(self, event_name: str) -> bool:
        """O(1) membership check for event name existence in catalog."""
        return event_name in self._entries

    def get(self, event_name: str) -> EventMetadata | None:
        """Get metadata for a specific event, or None if not registered."""
        return self._entries.get(event_name)

    def all(self) -> dict[str, EventMetadata]:
        """Return all registered event metadata."""
        return dict(self._entries)

    def by_domain(self, domain: str) -> dict[str, EventMetadata]:
        """Return all events for a specific domain (e.g., 'job', 'config')."""
        return {
            name: meta for name, meta in self._entries.items() if meta.domain == domain
        }
