"""ResolutionChain orchestrator for the pluggable configuration system.

Consults an ordered list of Sources to resolve configuration values with
defined precedence. The first source providing a non-None value wins.
Records provenance metadata (source_type, source_id, key) for each
resolved value and supports introspection of alternatives from
lower-priority sources.

Only imports from `_types/`, `_events/`, and Python stdlib.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from functualize._config.errors import MissingKeyError

if TYPE_CHECKING:
    from functualize._events import EventBus
    from functualize._types import Source


@dataclass(frozen=True)
class ResolvedValue:
    """A resolved configuration value with provenance metadata.

    Attributes:
        value: The resolved configuration value.
        source_type: Type of source that provided the value
            (e.g., 'cli', 'env', 'remote', 'file', 'default').
        source_id: Identifier of the source (e.g., file path,
            'environ', provider name).
        key: The configuration key that was resolved.
        alternatives: Values from lower-priority sources that also
            provide this key. Each entry is (source_type, source_id, value).
    """

    value: Any
    source_type: str
    source_id: str
    key: str
    alternatives: list[tuple[str, str, Any]] = field(default_factory=list)


class ResolutionChain:
    """Orchestrates value resolution across ordered sources.

    Sources are consulted in precedence order (index 0 = highest priority).
    The first source that provides a non-None value wins. All consulted
    sources are recorded for introspection.

    Example:
        chain = ResolutionChain([cli_source, env_source, file_source])
        resolved = chain.resolve("port", section="database")
        print(resolved.value, resolved.source_type)
    """

    def __init__(
        self,
        sources: list[Source],
        event_bus: EventBus | None = None,
    ) -> None:
        """Initialize with an ordered list of sources.

        Args:
            sources: List of Source implementations in precedence order.
                Index 0 is the highest-priority source.
            event_bus: Optional EventBus for emitting resolution events.
        """
        self._sources = sources
        self._event_bus = event_bus

    @property
    def sources(self) -> list[Source]:
        """Return the ordered list of sources."""
        return list(self._sources)

    def _emit(self, event_name: str, **payload: Any) -> None:
        """Emit a structured event if an event bus is configured."""
        if self._event_bus is not None:
            resource = payload.pop("resource", "")
            self._event_bus.emit(event_name, resource=resource, **payload)

    def resolve(self, key: str, section: str | None = None) -> ResolvedValue:
        """Resolve a key by consulting sources in precedence order.

        The first source providing a non-None value wins. Alternatives
        from lower-priority sources are collected after the winning source
        is found.

        Args:
            key: The configuration key to resolve.
            section: Optional section/namespace for the key.

        Returns:
            ResolvedValue with the winning value and provenance metadata.

        Raises:
            MissingKeyError: If no source provides a value for the key.
        """
        winner_value: Any = None
        winner_source_type: str | None = None
        winner_source_id: str | None = None
        alternatives: list[tuple[str, str, Any]] = []
        found = False

        for source in self._sources:
            value = source.get(key, section)
            if value is not None:
                if not found:
                    winner_value = value
                    winner_source_type = source.source_type
                    winner_source_id = source.source_id
                    found = True
                else:
                    alternatives.append((source.source_type, source.source_id, value))

        if not found:
            consulted = [source.source_id for source in self._sources]
            raise MissingKeyError(key=key, consulted_sources=consulted)

        assert winner_source_type is not None
        assert winner_source_id is not None

        return ResolvedValue(
            value=winner_value,
            source_type=winner_source_type,
            source_id=winner_source_id,
            key=key,
            alternatives=alternatives,
        )

    def resolve_section(self, section: str) -> dict[str, ResolvedValue]:
        """Resolve all keys in a section by querying each source.

        Gathers all keys that any source has for the given section,
        then resolves each key through the full resolution chain.

        Args:
            section: The section/namespace to resolve.

        Returns:
            Dict mapping key names to their ResolvedValue instances.
        """
        all_keys: set[str] = set()
        for source in self._sources:
            all_keys.update(source.keys(section))

        self._emit(
            "config.resolution.start",
            resource=section,
            section=section,
            field_count=len(all_keys),
        )
        start = time.perf_counter()

        results: dict[str, ResolvedValue] = {}
        for key in sorted(all_keys):
            with contextlib.suppress(MissingKeyError):
                results[key] = self.resolve(key, section)

        duration_ms = (time.perf_counter() - start) * 1000
        self._emit(
            "config.resolution.end",
            resource=section,
            section=section,
            duration_ms=duration_ms,
            sources_consulted=len(self._sources),
        )

        return results

    def introspect(self, key: str, section: str | None = None) -> ResolvedValue:
        """Resolve a key and always gather all alternatives.

        Same as resolve but explicitly gathers values from all sources,
        including those after the winning source.

        Args:
            key: The configuration key to inspect.
            section: Optional section/namespace for the key.

        Returns:
            ResolvedValue with the winning value and all alternatives
            from lower-priority sources.

        Raises:
            MissingKeyError: If no source provides a value for the key.
        """
        winner_value: Any = None
        winner_source_type: str | None = None
        winner_source_id: str | None = None
        alternatives: list[tuple[str, str, Any]] = []
        found = False

        for source in self._sources:
            value = source.get(key, section)
            if value is not None:
                if not found:
                    winner_value = value
                    winner_source_type = source.source_type
                    winner_source_id = source.source_id
                    found = True
                else:
                    alternatives.append((source.source_type, source.source_id, value))

        if not found:
            consulted = [source.source_id for source in self._sources]
            raise MissingKeyError(key=key, consulted_sources=consulted)

        assert winner_source_type is not None
        assert winner_source_id is not None

        return ResolvedValue(
            value=winner_value,
            source_type=winner_source_type,
            source_id=winner_source_id,
            key=key,
            alternatives=alternatives,
        )
