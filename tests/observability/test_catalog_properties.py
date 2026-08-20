"""Property-based tests for EventCatalog registration and retrieval.

Tests Property 23 from the design document.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from functualize._events._obs_types import EventMetadata
from functualize._events.catalog import EventCatalog

# --- Strategies ---

# Valid domains as defined in the spec
_DOMAINS = ["job", "config", "plugin", "cli", "tui"]

# Strategy for event name segments: lowercase alpha start, then alphanumeric + underscore
_segment = st.from_regex(r"[a-z][a-z0-9_]*", fullmatch=True).filter(
    lambda s: len(s) <= 20
)

# Strategy for valid event names: {domain}.{resource}.{action} (at least 3 segments)
_event_names = st.builds(
    lambda domain, resource, action: f"{domain}.{resource}.{action}",
    domain=st.sampled_from(_DOMAINS),
    resource=_segment,
    action=_segment,
)

# Strategy for generating EventMetadata instances
_event_metadata = st.builds(
    EventMetadata,
    event_name=_event_names,
    description=st.text(min_size=1),
    payload_fields=st.dictionaries(st.text(min_size=1), st.text(min_size=1)),
    module=st.text(min_size=1),
    domain=st.sampled_from(_DOMAINS),
)


# --- Property 23: Custom event catalog registration ---


class TestProperty23CustomEventCatalogRegistration:
    """Registered metadata appears in all() and by_domain() correctly.

    **Validates: Requirements 10.5**
    """

    @given(entries=st.lists(_event_metadata, min_size=1, max_size=20))
    def test_registered_entries_appear_in_all(
        self, entries: list[EventMetadata]
    ) -> None:
        """Each registered entry appears in all() keyed by event_name."""
        catalog = EventCatalog()
        for meta in entries:
            catalog.register(meta)

        all_entries = catalog.all()

        # Last registration for each event_name wins (overwrite semantics)
        expected: dict[str, EventMetadata] = {}
        for meta in entries:
            expected[meta.event_name] = meta

        for event_name, meta in expected.items():
            assert event_name in all_entries
            assert all_entries[event_name] == meta

    @given(entries=st.lists(_event_metadata, min_size=1, max_size=20))
    def test_registered_entries_appear_in_by_domain(
        self, entries: list[EventMetadata]
    ) -> None:
        """Each entry appears in by_domain(meta.domain) keyed by event_name."""
        catalog = EventCatalog()
        for meta in entries:
            catalog.register(meta)

        # Last registration for each event_name wins
        expected: dict[str, EventMetadata] = {}
        for meta in entries:
            expected[meta.event_name] = meta

        for event_name, meta in expected.items():
            domain_entries = catalog.by_domain(meta.domain)
            assert event_name in domain_entries
            assert domain_entries[event_name] == meta

    @given(entries=st.lists(_event_metadata, min_size=1, max_size=20))
    def test_entries_do_not_appear_in_other_domains(
        self, entries: list[EventMetadata]
    ) -> None:
        """Entries from other domains do NOT appear in a domain-specific query."""
        catalog = EventCatalog()
        for meta in entries:
            catalog.register(meta)

        # Last registration for each event_name wins
        expected: dict[str, EventMetadata] = {}
        for meta in entries:
            expected[meta.event_name] = meta

        for domain in _DOMAINS:
            domain_entries = catalog.by_domain(domain)
            for _event_name, meta in domain_entries.items():
                assert meta.domain == domain

    @given(entries=st.lists(_event_metadata, min_size=1, max_size=20))
    def test_get_returns_registered_metadata(
        self, entries: list[EventMetadata]
    ) -> None:
        """get(event_name) returns the registered metadata."""
        catalog = EventCatalog()
        for meta in entries:
            catalog.register(meta)

        # Last registration for each event_name wins
        expected: dict[str, EventMetadata] = {}
        for meta in entries:
            expected[meta.event_name] = meta

        for event_name, meta in expected.items():
            assert catalog.get(event_name) == meta
