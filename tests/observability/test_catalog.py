"""Unit tests for EventCatalog."""

from functualize._events._obs_types import EventMetadata
from functualize._events.catalog import EventCatalog


def _make_metadata(
    event_name: str = "job.execute.start",
    domain: str = "job",
) -> EventMetadata:
    return EventMetadata(
        event_name=event_name,
        description="Test event",
        payload_fields={"job_name": "str"},
        module="functualize._app.app",
        domain=domain,
    )


class TestEventCatalog:
    def test_register_and_get(self) -> None:
        catalog = EventCatalog()
        meta = _make_metadata()
        catalog.register(meta)
        assert catalog.get("job.execute.start") is meta

    def test_get_returns_none_for_unknown(self) -> None:
        catalog = EventCatalog()
        assert catalog.get("nonexistent.event.name") is None

    def test_register_overwrites_existing(self) -> None:
        catalog = EventCatalog()
        meta1 = _make_metadata(event_name="job.execute.start")
        meta2 = EventMetadata(
            event_name="job.execute.start",
            description="Updated",
            payload_fields={},
            module="other.module",
            domain="job",
        )
        catalog.register(meta1)
        catalog.register(meta2)
        assert catalog.get("job.execute.start") is meta2

    def test_all_returns_copy(self) -> None:
        catalog = EventCatalog()
        meta = _make_metadata()
        catalog.register(meta)
        all_entries = catalog.all()
        assert all_entries == {"job.execute.start": meta}
        # Mutating the returned dict does not affect internal state
        all_entries["fake.event.name"] = meta  # type: ignore[assignment]
        assert "fake.event.name" not in catalog.all()

    def test_by_domain_filters_correctly(self) -> None:
        catalog = EventCatalog()
        job_meta = _make_metadata(event_name="job.execute.start", domain="job")
        config_meta = _make_metadata(event_name="config.file.parse", domain="config")
        catalog.register(job_meta)
        catalog.register(config_meta)

        job_events = catalog.by_domain("job")
        assert job_events == {"job.execute.start": job_meta}

        config_events = catalog.by_domain("config")
        assert config_events == {"config.file.parse": config_meta}

    def test_by_domain_returns_empty_for_unknown_domain(self) -> None:
        catalog = EventCatalog()
        catalog.register(_make_metadata())
        assert catalog.by_domain("unknown") == {}

    def test_empty_catalog(self) -> None:
        catalog = EventCatalog()
        assert catalog.all() == {}
        assert catalog.by_domain("job") == {}
        assert catalog.get("anything") is None
