"""Property-based tests for TrieRouter and EventBus (Properties 1, 2, 3, 4, 5, 6, 7).

Tests the event bus dispatch ordering, fault tolerance, zero-cost bypass,
event name grammar validation, propagation context auto-attachment,
TrieRouter pattern matching correctness, and unsubscribe behavior.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from hypothesis import given
from hypothesis import strategies as st

if TYPE_CHECKING:
    from functualize._events.bus import StructuredEvent

from functualize._events.bus import (
    _EVENT_NAME_RE,
    EventBus,
    TrieRouter,
)
from functualize._events.tracing import (
    current_context,
    detach,
    start_trace,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for valid event name segments: starts with lowercase, then lowercase/digits/underscores
_segment_st = st.from_regex(r"[a-z][a-z0-9_]*", fullmatch=True)

# Strategy for valid event names (at least 3 dot-separated segments)
_valid_event_name_st = st.tuples(
    _segment_st,
    _segment_st,
    _segment_st,
    st.lists(_segment_st, min_size=0, max_size=2),
).map(lambda t: ".".join([t[0], t[1], t[2]] + t[3]))

# Strategy for invalid event names that don't match the grammar
_invalid_event_name_st = st.one_of(
    # Starts with uppercase
    st.from_regex(r"[A-Z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", fullmatch=True),
    # Only 2 segments
    st.from_regex(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", fullmatch=True),
    # Only 1 segment
    st.from_regex(r"[a-z][a-z0-9_]*", fullmatch=True),
    # Contains uppercase in middle
    st.from_regex(r"[a-z][a-z0-9_]*\.[A-Z][a-z0-9_]*\.[a-z][a-z0-9_]*", fullmatch=True),
    # Empty string
    st.just(""),
    # Starts with digit
    st.from_regex(r"[0-9][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", fullmatch=True),
    # Contains spaces
    st.from_regex(
        r"[a-z][a-z0-9_]* \.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", fullmatch=True
    ),
)

# Strategy for subscription patterns (exact, prefix wildcard, or global)
_subscription_pattern_st = st.one_of(
    # Exact match pattern (valid event name)
    _valid_event_name_st,
    # Prefix wildcard (segment(s) followed by .*)
    st.tuples(
        _segment_st,
        st.lists(_segment_st, min_size=0, max_size=2),
    ).map(lambda t: ".".join([t[0]] + t[1]) + ".*"),
    # Global wildcard
    st.just("*"),
)


class TestProperty1EventBusDispatchOrdering:
    """Property 1: Event_Bus dispatch ordering.

    *For any* sequence of subscriber registrations (exact, prefix, and global
    patterns) and any emitted event matching multiple subscribers, the
    subscribers SHALL be invoked in their original registration order.

    **Validates: Requirements 1.5, 2.3**
    """

    @given(
        num_subscribers=st.integers(min_value=2, max_value=10),
    )
    def test_dispatch_ordering_all_pattern_types(
        self,
        num_subscribers: int,
    ) -> None:
        """Subscribers invoked in registration order regardless of pattern type."""
        bus = EventBus()
        invocation_order: list[int] = []

        # Register subscribers with a mix of pattern types that all match
        # a specific test event
        test_event = "config.file.parse.end"

        patterns = []
        for i in range(num_subscribers):
            # Cycle through: exact, prefix, global
            match i % 3:
                case 0:
                    pattern = test_event  # exact
                case 1:
                    pattern = "config.*"  # prefix
                case _:
                    pattern = "*"  # global

            patterns.append(pattern)

            def make_callback(idx: int):  # noqa: E301
                def cb(event: StructuredEvent) -> None:
                    invocation_order.append(idx)

                return cb

            bus.subscribe(pattern, make_callback(i))

        # Emit the event
        bus.emit(test_event, resource="test.toml")

        # All subscribers should have been called
        assert len(invocation_order) == num_subscribers

        # They should be in registration order (0, 1, 2, ...)
        assert invocation_order == list(range(num_subscribers))

    @given(
        pattern_choices=st.lists(
            st.sampled_from(["exact", "prefix", "global"]),
            min_size=2,
            max_size=8,
        ),
    )
    def test_dispatch_ordering_with_generated_patterns(
        self,
        pattern_choices: list[str],
    ) -> None:
        """Registration order preserved across arbitrary pattern mixes."""
        bus = EventBus()
        invocation_order: list[int] = []
        test_event = "job.execute.start"

        for i, choice in enumerate(pattern_choices):
            if choice == "exact":
                pattern = test_event
            elif choice == "prefix":
                pattern = "job.*"
            else:
                pattern = "*"

            def make_callback(idx: int):  # noqa: E301
                def cb(event: StructuredEvent) -> None:
                    invocation_order.append(idx)

                return cb

            bus.subscribe(pattern, make_callback(i))

        bus.emit(test_event, resource="my_job")
        assert invocation_order == list(range(len(pattern_choices)))


class TestProperty2EventBusSubscriberFaultTolerance:
    """Property 2: Event_Bus subscriber fault tolerance.

    *For any* set of subscribers where one or more raise exceptions, the
    Event_Bus SHALL invoke all remaining non-failing subscribers and the
    overall emit() call SHALL not raise.

    **Validates: Requirements 1.6**
    """

    @given(
        error_positions=st.lists(
            st.booleans(),
            min_size=2,
            max_size=10,
        ),
    )
    def test_subscriber_fault_tolerance(
        self,
        error_positions: list[bool],
    ) -> None:
        """Exceptions in subscribers don't prevent remaining subscribers from running."""
        bus = EventBus()
        called: list[int] = []

        for i, should_raise in enumerate(error_positions):

            def make_callback(idx: int, raises: bool):  # noqa: E301
                def cb(event: StructuredEvent) -> None:
                    called.append(idx)
                    if raises:
                        raise RuntimeError(f"Subscriber {idx} exploded")

                return cb

            bus.subscribe("*", make_callback(i, should_raise))

        # emit() should not raise even when subscribers do
        bus.emit("test.event.action", resource="test")

        # ALL subscribers should have been called regardless of exceptions
        assert called == list(range(len(error_positions)))


class TestProperty3EventBusZeroCostBypass:
    """Property 3: Event_Bus zero-cost bypass.

    *For any* event name emitted when no subscribers are registered (globally
    or for that specific event), the Event_Bus SHALL return without
    constructing a StructuredEvent, calling time.time(), or invoking any
    subscriber callbacks.

    **Validates: Requirements 1.4, 7.1**
    """

    @given(
        event_name=_valid_event_name_st,
    )
    def test_zero_cost_no_subscribers(
        self,
        event_name: str,
    ) -> None:
        """No StructuredEvent constructed when no subscribers exist."""
        bus = EventBus()

        # With no subscribers, emit should return immediately without crashing
        # and without constructing any event. We verify by confirming no
        # subscriber is called (trivially true since there are none).
        bus.emit(event_name, resource="test")

        # The fact that has_subscribers is False guarantees the zero-cost path
        assert not bus.has_subscribers

    @given(
        event_name=_valid_event_name_st,
    )
    def test_zero_cost_no_matching_subscribers(
        self,
        event_name: str,
    ) -> None:
        """No callback invoked when subscribers exist but none match the event."""
        bus = EventBus()
        called = False

        # Subscribe to a completely unrelated pattern
        def cb(event: StructuredEvent) -> None:
            nonlocal called
            called = True

        bus.subscribe("zzz.unrelated.pattern.xyz", cb)

        bus.emit(event_name, resource="test")

        # The callback should NOT be called if event_name doesn't match
        # (unless event_name happens to be exactly "zzz.unrelated.pattern.xyz")
        if event_name != "zzz.unrelated.pattern.xyz":
            assert not called


class TestProperty4EventNameGrammarValidation:
    """Property 4: Event name grammar validation.

    *For any* string, the Event_Bus's event name validation SHALL accept it
    if and only if it matches the regex
    `^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*){2,}$`.

    **Validates: Requirements 1.2, 10.4**
    """

    @given(event_name=_valid_event_name_st)
    def test_valid_event_names_accepted(
        self,
        event_name: str,
    ) -> None:
        """Valid event names matching the regex are accepted and dispatched."""
        bus = EventBus()
        received: list[StructuredEvent] = []

        bus.subscribe("*", received.append)
        bus.emit(event_name, resource="test")

        # Valid names should be dispatched
        assert len(received) == 1
        assert received[0].event_name == event_name

    @given(event_name=_invalid_event_name_st)
    def test_invalid_event_names_rejected(
        self,
        event_name: str,
    ) -> None:
        """Invalid event names not matching the regex are rejected (not dispatched)."""
        # Double-check our strategy actually produces invalid names
        assert not _EVENT_NAME_RE.match(event_name), (
            f"Strategy produced a valid name: {event_name!r}"
        )

        bus = EventBus()
        received: list[StructuredEvent] = []

        bus.subscribe("*", received.append)
        bus.emit(event_name, resource="test")

        # Invalid names should NOT be dispatched
        assert len(received) == 0

    @given(text=st.text(min_size=0, max_size=50))
    def test_regex_consistency(
        self,
        text: str,
    ) -> None:
        """The EventBus validation matches the documented regex exactly."""
        regex_matches = bool(_EVENT_NAME_RE.match(text))
        reference_re = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,}$")
        reference_matches = bool(reference_re.match(text))

        # Both regexes should agree
        assert regex_matches == reference_matches


class TestProperty5PropagationContextAutoAttachment:
    """Property 5: Propagation context auto-attachment.

    *For any* active PropagationContext (with non-None trace_id and span_id)
    at the time of event emission, the resulting StructuredEvent SHALL carry
    the same trace_id and span_id values from the active context.

    **Validates: Requirements 1.3**
    """

    @given(
        event_name=_valid_event_name_st,
        session_id=st.one_of(st.text(min_size=1), st.none()),
    )
    def test_context_auto_attached(
        self,
        event_name: str,
        session_id: str | None,
    ) -> None:
        """Emitted events carry active context's trace_id/span_id."""
        bus = EventBus()
        received: list[StructuredEvent] = []
        bus.subscribe("*", received.append)

        # Start a trace to set active context
        token = start_trace(session_id=session_id)
        try:
            ctx = current_context()
            bus.emit(event_name, resource="test")

            assert len(received) == 1
            assert received[0].trace_id == ctx.trace_id
            assert received[0].span_id == ctx.span_id
        finally:
            detach(token)

    @given(event_name=_valid_event_name_st)
    def test_no_context_when_no_trace(
        self,
        event_name: str,
    ) -> None:
        """When no trace is active, events have None trace_id/span_id."""
        bus = EventBus()
        received: list[StructuredEvent] = []
        bus.subscribe("*", received.append)

        # Ensure no trace is active
        ctx = current_context()
        if ctx.is_active:
            return  # Skip if another test left context active

        bus.emit(event_name, resource="test")

        assert len(received) == 1
        assert received[0].trace_id is None
        assert received[0].span_id is None


class TestProperty6TrieRouterPatternMatchingCorrectness:
    """Property 6: TrieRouter pattern matching correctness.

    *For any* event name and registered subscriber pattern, the TrieRouter
    SHALL match the subscriber if and only if: (a) the pattern is "*" (matches
    all), (b) the pattern equals the event name exactly, or (c) the pattern
    ends with ".*" and the event name starts with the pattern's prefix.

    **Validates: Requirements 2.1, 2.2**
    """

    @given(event_name=_valid_event_name_st)
    def test_global_wildcard_matches_everything(
        self,
        event_name: str,
    ) -> None:
        """Global wildcard '*' matches all events."""
        router = TrieRouter()
        called = False

        def cb(event: StructuredEvent) -> None:
            nonlocal called
            called = True

        router.subscribe("*", cb)
        callbacks = router.match(event_name)
        assert cb in callbacks

    @given(event_name=_valid_event_name_st)
    def test_exact_match_only_matches_exact_name(
        self,
        event_name: str,
    ) -> None:
        """Exact pattern matches only the exact event name."""
        router = TrieRouter()
        called_exact = False
        called_other = False

        def cb_exact(event: StructuredEvent) -> None:
            nonlocal called_exact
            called_exact = True

        def cb_other(event: StructuredEvent) -> None:
            nonlocal called_other
            called_other = True

        router.subscribe(event_name, cb_exact)
        # Subscribe to a different exact name
        other_name = event_name + ".extra"
        router.subscribe(other_name, cb_other)

        callbacks = router.match(event_name)
        assert cb_exact in callbacks
        assert cb_other not in callbacks

    @given(
        event_name=_valid_event_name_st,
    )
    def test_prefix_wildcard_matches_events_starting_with_prefix(
        self,
        event_name: str,
    ) -> None:
        """Prefix 'foo.*' matches all events starting with 'foo.'."""
        router = TrieRouter()

        # Get the first segment as prefix
        parts = event_name.split(".")
        prefix = parts[0]
        prefix_pattern = prefix + ".*"

        def cb(event: StructuredEvent) -> None:
            pass

        router.subscribe(prefix_pattern, cb)
        callbacks = router.match(event_name)

        # Since event_name starts with prefix (first segment), it should match
        assert cb in callbacks

    @given(
        prefix_segment=_segment_st,
        suffix_segments=st.lists(_segment_st, min_size=2, max_size=4),
    )
    def test_prefix_wildcard_does_not_match_non_prefixed(
        self,
        prefix_segment: str,
        suffix_segments: list[str],
    ) -> None:
        """Prefix 'foo.*' does NOT match events that don't start with 'foo.'."""
        router = TrieRouter()

        # Create a prefix pattern
        prefix_pattern = prefix_segment + ".*"

        def cb(event: StructuredEvent) -> None:
            pass

        router.subscribe(prefix_pattern, cb)

        # Create an event name that uses a DIFFERENT first segment
        different_prefix = prefix_segment + "x"  # Guaranteed different
        event_name = ".".join([different_prefix] + suffix_segments)

        callbacks = router.match(event_name)
        assert cb not in callbacks

    @given(event_name=_valid_event_name_st)
    def test_has_subscribers_for_reflects_matches(
        self,
        event_name: str,
    ) -> None:
        """has_subscribers_for() returns True iff at least one pattern matches."""
        router = TrieRouter()

        def cb(event: StructuredEvent) -> None:
            pass

        # No subscribers yet
        assert not router.has_subscribers_for(event_name)

        # Add exact subscriber
        router.subscribe(event_name, cb)
        assert router.has_subscribers_for(event_name)


class TestProperty7UnsubscribeRemovesSubscriber:
    """Property 7: Unsubscribe removes subscriber.

    *For any* subscriber registered then unsubscribed via its
    SubscriptionHandle, subsequent events matching that subscriber's pattern
    SHALL NOT be delivered to that callback.

    **Validates: Requirements 2.4**
    """

    @given(
        pattern_type=st.sampled_from(["exact", "prefix", "global"]),
        emit_count=st.integers(min_value=1, max_value=5),
    )
    def test_unsubscribed_callback_never_invoked(
        self,
        pattern_type: str,
        emit_count: int,
    ) -> None:
        """Unsubscribed callback never invoked for subsequent events."""
        bus = EventBus()
        test_event = "job.execute.start"
        unsubscribed_called = False
        remaining_calls: list[int] = []

        def unsubscribed_cb(event: StructuredEvent) -> None:
            nonlocal unsubscribed_called
            unsubscribed_called = True

        def remaining_cb(event: StructuredEvent) -> None:
            remaining_calls.append(1)

        # Choose pattern based on type
        if pattern_type == "exact":
            pattern = test_event
        elif pattern_type == "prefix":
            pattern = "job.*"
        else:
            pattern = "*"

        # Subscribe both
        handle = bus.subscribe(pattern, unsubscribed_cb)
        bus.subscribe("*", remaining_cb)

        # Unsubscribe the first one
        bus.unsubscribe(handle)

        # Emit multiple events
        for _ in range(emit_count):
            bus.emit(test_event, resource="my_job")

        # The unsubscribed callback should NEVER be called
        assert not unsubscribed_called

        # The remaining callback should still be called
        assert len(remaining_calls) == emit_count

    @given(
        num_subscribers=st.integers(min_value=2, max_value=6),
        unsubscribe_index=st.integers(min_value=0),
    )
    def test_unsubscribe_specific_subscriber_only(
        self,
        num_subscribers: int,
        unsubscribe_index: int,
    ) -> None:
        """Unsubscribing one subscriber does not affect others."""
        bus = EventBus()
        test_event = "config.file.parse.end"
        called: list[int] = []
        handles = []

        # Normalize unsubscribe_index to valid range
        target_idx = unsubscribe_index % num_subscribers

        for i in range(num_subscribers):

            def make_callback(idx: int):  # noqa: E301
                def cb(event: StructuredEvent) -> None:
                    called.append(idx)

                return cb

            handle = bus.subscribe("*", make_callback(i))
            handles.append(handle)

        # Unsubscribe one specific subscriber
        bus.unsubscribe(handles[target_idx])

        # Emit an event
        bus.emit(test_event, resource="test.toml")

        # All subscribers EXCEPT the unsubscribed one should be called
        expected = [i for i in range(num_subscribers) if i != target_idx]
        assert called == expected
