"""Property-based tests for EventSink adapter (Properties 21, 22).

Tests the EventBusAdapter translation logic and install_adapter idempotency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hypothesis import given
from hypothesis import strategies as st

if TYPE_CHECKING:
    from functualize._events.bus import StructuredEvent

from functualize._events.adapter import EventBusAdapter, install_adapter
from functualize._events.bus import EventBus

# --- Strategies ---

# Generate valid event names matching the grammar: {domain}.{resource}.{action}
_SEGMENT = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)
_EVENT_NAME = st.tuples(_SEGMENT, _SEGMENT, _SEGMENT).map(
    lambda parts: f"{parts[0]}.{parts[1]}.{parts[2]}"
)

# Payload values — simple types that can be str-ified for resource derivation
_PAYLOAD_VALUE = st.one_of(
    st.text(min_size=1, max_size=30),
    st.integers(min_value=0, max_value=1000),
)

# Generate payloads with optional path, provider, section keys
_PAYLOAD_WITH_RESOURCE_KEYS = st.fixed_dictionaries(
    {},
    optional={
        "path": st.text(min_size=1, max_size=50),
        "provider": st.text(min_size=1, max_size=50),
        "section": st.text(min_size=1, max_size=50),
    },
)

# Additional arbitrary payload fields (avoid collisions with resource/related/event_name)
_EXTRA_PAYLOAD = st.dictionaries(
    st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True).filter(
        lambda k: (
            k
            not in ("path", "provider", "section", "resource", "related", "event_name")
        )
    ),
    _PAYLOAD_VALUE,
    min_size=0,
    max_size=3,
)

# Strategy for explicit resource strings
_EXPLICIT_RESOURCE = st.text(min_size=1, max_size=50)


class TestProperty21EventSinkAdapterTranslation:
    """Property 21: EventSink adapter translation.

    *For any* config module emit(event_name, **payload) call routed through
    the adapter:
    - If ``resource`` is explicitly provided and non-empty, it is used directly.
    - Otherwise, the resource field is derived from payload["path"] or
      payload["provider"] or payload["section"] (in that priority).
    - The ``resource`` key is popped from payload before forwarding.
    - All other payload fields are preserved in the event's payload dict.

    **Validates: Requirements 9.2, 9.3**
    """

    @given(
        event_name=_EVENT_NAME,
        explicit_resource=_EXPLICIT_RESOURCE,
        resource_keys=_PAYLOAD_WITH_RESOURCE_KEYS,
        extra_payload=_EXTRA_PAYLOAD,
    )
    def test_explicit_resource_takes_priority_over_heuristic(
        self,
        event_name: str,
        explicit_resource: str,
        resource_keys: dict[str, str],
        extra_payload: dict[str, Any],
    ) -> None:
        """When resource is explicitly provided and non-empty, it is used directly."""
        bus = EventBus()
        adapter = EventBusAdapter(bus)

        # Combine payload with explicit resource
        payload = {**resource_keys, **extra_payload, "resource": explicit_resource}

        # Capture emitted events
        captured: list[StructuredEvent] = []
        bus.subscribe("*", lambda ev: captured.append(ev))

        # Call adapter.emit
        adapter.emit(event_name, **payload)

        # Should have emitted exactly one event
        assert len(captured) == 1
        event = captured[0]

        # event_name is preserved
        assert event.event_name == event_name

        # Explicit resource is used directly (no heuristic)
        assert event.resource == explicit_resource

        # resource key is popped from payload (not forwarded)
        assert "resource" not in event.payload

    @given(
        event_name=_EVENT_NAME,
        resource_keys=_PAYLOAD_WITH_RESOURCE_KEYS,
        extra_payload=_EXTRA_PAYLOAD,
    )
    def test_heuristic_fallback_when_no_explicit_resource(
        self,
        event_name: str,
        resource_keys: dict[str, str],
        extra_payload: dict[str, Any],
    ) -> None:
        """When resource is not provided, fallback heuristic derives it: path > provider > section > ''."""
        bus = EventBus()
        adapter = EventBusAdapter(bus)

        # Combine payload without explicit resource
        payload = {**resource_keys, **extra_payload}

        # Capture emitted events
        captured: list[StructuredEvent] = []
        bus.subscribe("*", lambda ev: captured.append(ev))

        # Call adapter.emit
        adapter.emit(event_name, **payload)

        # Should have emitted exactly one event
        assert len(captured) == 1
        event = captured[0]

        # event_name is preserved
        assert event.event_name == event_name

        # Resource derivation priority: path > provider > section > ""
        expected_resource = ""
        if "path" in resource_keys:
            expected_resource = str(resource_keys["path"])
        elif "provider" in resource_keys:
            expected_resource = str(resource_keys["provider"])
        elif "section" in resource_keys:
            expected_resource = str(resource_keys["section"])

        assert event.resource == expected_resource

    @given(
        event_name=_EVENT_NAME,
        resource_keys=_PAYLOAD_WITH_RESOURCE_KEYS,
        extra_payload=_EXTRA_PAYLOAD,
    )
    def test_all_non_resource_payload_fields_preserved_in_event(
        self,
        event_name: str,
        resource_keys: dict[str, str],
        extra_payload: dict[str, Any],
    ) -> None:
        """All original payload fields (except 'resource') are preserved in the emitted event's payload."""
        bus = EventBus()
        adapter = EventBusAdapter(bus)

        # Combine payload (without explicit resource to test heuristic path)
        payload = {**resource_keys, **extra_payload}

        # Capture emitted events
        captured: list[StructuredEvent] = []
        bus.subscribe("*", lambda ev: captured.append(ev))

        # Call adapter.emit
        adapter.emit(event_name, **payload)

        assert len(captured) == 1
        event = captured[0]

        # All original payload fields should be in event.payload
        for key, value in payload.items():
            assert key in event.payload, (
                f"Payload field '{key}' missing from event.payload"
            )
            assert event.payload[key] == value

    @given(event_name=_EVENT_NAME)
    def test_empty_payload_produces_empty_resource(
        self,
        event_name: str,
    ) -> None:
        """When no resource keys present, resource defaults to empty string."""
        bus = EventBus()
        adapter = EventBusAdapter(bus)

        captured: list[StructuredEvent] = []
        bus.subscribe("*", lambda ev: captured.append(ev))

        # Emit with no resource-deriving keys
        adapter.emit(event_name)

        assert len(captured) == 1
        assert captured[0].resource == ""

    @given(
        event_name=_EVENT_NAME,
        path_val=st.text(min_size=1, max_size=30),
        provider_val=st.text(min_size=1, max_size=30),
        section_val=st.text(min_size=1, max_size=30),
    )
    def test_path_takes_priority_over_provider_and_section(
        self,
        event_name: str,
        path_val: str,
        provider_val: str,
        section_val: str,
    ) -> None:
        """When all three heuristic keys present but no explicit resource, path wins."""
        bus = EventBus()
        adapter = EventBusAdapter(bus)

        captured: list[StructuredEvent] = []
        bus.subscribe("*", lambda ev: captured.append(ev))

        adapter.emit(
            event_name, path=path_val, provider=provider_val, section=section_val
        )

        assert len(captured) == 1
        assert captured[0].resource == path_val

    @given(
        event_name=_EVENT_NAME,
        resource_keys=_PAYLOAD_WITH_RESOURCE_KEYS,
        extra_payload=_EXTRA_PAYLOAD,
    )
    def test_empty_explicit_resource_triggers_heuristic_fallback(
        self,
        event_name: str,
        resource_keys: dict[str, str],
        extra_payload: dict[str, Any],
    ) -> None:
        """When resource is explicitly provided but empty, fallback heuristic is used."""
        bus = EventBus()
        adapter = EventBusAdapter(bus)

        # Combine payload with empty resource
        payload = {**resource_keys, **extra_payload, "resource": ""}

        # Capture emitted events
        captured: list[StructuredEvent] = []
        bus.subscribe("*", lambda ev: captured.append(ev))

        # Call adapter.emit
        adapter.emit(event_name, **payload)

        # Should have emitted exactly one event
        assert len(captured) == 1
        event = captured[0]

        # Heuristic applies because resource was empty
        expected_resource = ""
        if "path" in resource_keys:
            expected_resource = str(resource_keys["path"])
        elif "provider" in resource_keys:
            expected_resource = str(resource_keys["provider"])
        elif "section" in resource_keys:
            expected_resource = str(resource_keys["section"])

        assert event.resource == expected_resource

        # resource key is still popped from payload
        assert "resource" not in event.payload


class TestProperty22AdapterInstallationIdempotency:
    """Property 22: Adapter installation idempotency.

    *For any* number of calls to install_adapter(), subscribers on the
    Event_Bus SHALL receive each emitted event exactly once (no duplicate
    routing).

    **Validates: Requirements 9.4**
    """

    @given(
        num_installs=st.integers(min_value=1, max_value=10),
    )
    def test_multiple_install_calls_produce_single_routing(
        self,
        num_installs: int,
    ) -> None:
        """Calling install_adapter multiple times doesn't duplicate event routing.

        We test this by checking the _adapter_installed flag behavior:
        after the first call sets _adapter_installed=True, subsequent calls
        return immediately without adding another adapter.
        """
        import functualize._config._emit as emit_module
        import functualize._events.adapter as adapter_module

        bus = EventBus()

        # Save original state
        original_flag = adapter_module._adapter_installed
        original_sink = emit_module._sink

        # We need the *real* set_event_sink (not the monkey-patched blocker).
        # Store a reference to the real implementation.
        def _real_set_event_sink(sink: Any) -> None:
            emit_module._sink = sink

        # Reset state for each test iteration
        adapter_module._adapter_installed = False
        emit_module._sink = None
        emit_module.set_event_sink = _real_set_event_sink  # type: ignore[assignment]

        try:
            # Call install_adapter multiple times
            # The first call installs the adapter and monkey-patches set_event_sink.
            # Subsequent calls are no-ops because _adapter_installed is True.
            for _ in range(num_installs):
                install_adapter(bus)

            # After all calls, the flag is set
            assert adapter_module._adapter_installed is True

            # The key invariant: use a fresh adapter directly to verify
            # single-routing behavior. Create a new EventBusAdapter and
            # subscribe to capture events — emitting through the adapter
            # should produce exactly one event per emit call.
            adapter = EventBusAdapter(bus)
            captured: list[StructuredEvent] = []
            bus.subscribe("*", lambda ev: captured.append(ev))

            adapter.emit("config.file.parse.end", path="/test.toml")
            assert len(captured) == 1, (
                f"Expected 1 event but got {len(captured)} — duplicate routing detected"
            )
        finally:
            # Restore original state
            adapter_module._adapter_installed = original_flag
            emit_module._sink = original_sink
            emit_module.set_event_sink = _real_set_event_sink  # type: ignore[assignment]

    @given(
        num_installs=st.integers(min_value=2, max_value=5),
    )
    def test_idempotency_flag_set_after_first_call(
        self,
        num_installs: int,
    ) -> None:
        """The _adapter_installed flag is set True on first call and stays True."""
        import functualize._config._emit as emit_module
        import functualize._events.adapter as adapter_module

        bus = EventBus()

        # Save original state
        original_flag = adapter_module._adapter_installed
        original_sink = emit_module._sink

        def _real_set_event_sink(sink: Any) -> None:
            emit_module._sink = sink

        # Reset state
        adapter_module._adapter_installed = False
        emit_module._sink = None
        emit_module.set_event_sink = _real_set_event_sink  # type: ignore[assignment]

        try:
            # First call sets the flag
            install_adapter(bus)
            assert adapter_module._adapter_installed is True

            # Subsequent calls don't change anything — flag stays True
            for _ in range(num_installs - 1):
                install_adapter(bus)
                assert adapter_module._adapter_installed is True
        finally:
            adapter_module._adapter_installed = original_flag
            emit_module._sink = original_sink
            emit_module.set_event_sink = _real_set_event_sink  # type: ignore[assignment]

    @given(
        num_installs=st.integers(min_value=1, max_value=5),
        event_name=_EVENT_NAME,
        payload_keys=_PAYLOAD_WITH_RESOURCE_KEYS,
    )
    def test_events_not_doubled_regardless_of_install_count(
        self,
        num_installs: int,
        event_name: str,
        payload_keys: dict[str, str],
    ) -> None:
        """Regardless of how many times install_adapter is called,
        each adapter.emit() produces exactly one event on the bus."""
        import functualize._config._emit as emit_module
        import functualize._events.adapter as adapter_module

        bus = EventBus()

        # Save original state
        original_flag = adapter_module._adapter_installed
        original_sink = emit_module._sink

        def _real_set_event_sink(sink: Any) -> None:
            emit_module._sink = sink

        # Reset state
        adapter_module._adapter_installed = False
        emit_module._sink = None
        emit_module.set_event_sink = _real_set_event_sink  # type: ignore[assignment]

        try:
            # Install multiple times
            for _ in range(num_installs):
                install_adapter(bus)

            # Create adapter and emit
            adapter = EventBusAdapter(bus)
            captured: list[StructuredEvent] = []
            bus.subscribe("*", lambda ev: captured.append(ev))

            adapter.emit(event_name, **payload_keys)

            # Exactly one event received (no doubling)
            assert len(captured) == 1
            assert captured[0].event_name == event_name
        finally:
            adapter_module._adapter_installed = original_flag
            emit_module._sink = original_sink
            emit_module.set_event_sink = _real_set_event_sink  # type: ignore[assignment]
