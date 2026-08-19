"""Property-based tests for PropagationContext (Properties 16, 17, 18, 19).

Tests the context propagation API: trace/span creation, parent-chain linking,
detach round-trip semantics, and empty context singleton behavior.
"""

from hypothesis import given
from hypothesis import strategies as st

from functualize._events.tracing import (
    _empty_context,
    current_context,
    detach,
    start_span,
    start_trace,
)

_HEX_CHARS = set("0123456789abcdef")


class TestProperty16TraceStartProducesValidIdentifiers:
    """Property 16: Trace start produces valid identifiers.

    *For any* call to start_trace(), the resulting PropagationContext SHALL have
    a non-None trace_id of exactly 32 hex characters and a non-None span_id of
    exactly 16 hex characters, with all characters in [0-9a-f].

    **Validates: Requirements 5.3**
    """

    @given(
        session_id=st.one_of(st.text(), st.none()),
        baggage=st.dictionaries(st.text(), st.text()),
    )
    def test_trace_start_produces_valid_identifiers(
        self,
        session_id: str | None,
        baggage: dict[str, str],
    ) -> None:
        """start_trace() always yields 32 hex trace_id and 16 hex span_id."""
        token = start_trace(session_id=session_id, baggage=baggage)
        try:
            ctx = current_context()

            # trace_id must be non-None and exactly 32 hex chars
            assert ctx.trace_id is not None
            assert len(ctx.trace_id) == 32
            assert set(ctx.trace_id) <= _HEX_CHARS

            # span_id must be non-None and exactly 16 hex chars
            assert ctx.span_id is not None
            assert len(ctx.span_id) == 16
            assert set(ctx.span_id) <= _HEX_CHARS

            # parent_span_id should be None for a fresh trace
            assert ctx.parent_span_id is None
        finally:
            detach(token)


class TestProperty17ChildSpanParentChainInvariant:
    """Property 17: Child span parent-chain invariant.

    *For any* nested sequence of start_span() calls within an active trace,
    each new span's parent_span_id SHALL equal the previous span's span_id,
    the trace_id SHALL remain unchanged throughout the chain, and each new
    span_id SHALL differ from all previous span_ids.

    **Validates: Requirements 5.4**
    """

    @given(
        span_names=st.lists(st.text(min_size=1), min_size=1, max_size=5),
    )
    def test_child_span_parent_chain_invariant(
        self,
        span_names: list[str],
    ) -> None:
        """Nested start_span() links parent_span_id correctly, preserves trace_id, unique span_ids."""
        trace_token = start_trace()
        span_tokens: list[object] = []
        try:
            trace_ctx = current_context()
            original_trace_id = trace_ctx.trace_id
            seen_span_ids: set[str | None] = {trace_ctx.span_id}

            previous_span_id = trace_ctx.span_id

            for name in span_names:
                span_token = start_span(name=name)
                span_tokens.append(span_token)
                ctx = current_context()

                # trace_id preserved across all spans
                assert ctx.trace_id == original_trace_id

                # parent_span_id links to previous span's span_id
                assert ctx.parent_span_id == previous_span_id

                # span_id is valid hex of length 16
                assert ctx.span_id is not None
                assert len(ctx.span_id) == 16
                assert set(ctx.span_id) <= _HEX_CHARS

                # span_id is unique (not seen before)
                assert ctx.span_id not in seen_span_ids

                seen_span_ids.add(ctx.span_id)
                previous_span_id = ctx.span_id
        finally:
            # Detach spans in reverse order
            for span_token in reversed(span_tokens):
                detach(span_token)  # type: ignore[arg-type]
            detach(trace_token)


class TestProperty18ContextDetachRoundTrip:
    """Property 18: Context detach round-trip.

    *For any* PropagationContext state, after calling start_trace() or
    start_span() and receiving a ContextToken, detaching that token SHALL
    restore current_context() to the exact state that existed before the
    token was created.

    **Validates: Requirements 5.5**
    """

    @given(
        session_id=st.one_of(st.text(min_size=1), st.none()),
        baggage=st.dictionaries(st.text(min_size=1), st.text(min_size=1)),
    )
    def test_context_detach_round_trip(
        self,
        session_id: str | None,
        baggage: dict[str, str],
    ) -> None:
        """Detach restores exact previous state."""
        # Record the state before starting a trace
        state_before_trace = current_context()

        # Start trace and record that context
        trace_token = start_trace(session_id=session_id, baggage=baggage)
        try:
            trace_ctx = current_context()
            assert trace_ctx.is_active

            # Start a span within the trace
            span_token = start_span(name="test_span")
            try:
                span_ctx = current_context()
                # Span context is different from trace context
                assert span_ctx.span_id != trace_ctx.span_id
                assert span_ctx.parent_span_id == trace_ctx.span_id
            finally:
                # Detach span → should restore to trace-level context
                detach(span_token)

            restored_after_span = current_context()
            assert restored_after_span.trace_id == trace_ctx.trace_id
            assert restored_after_span.span_id == trace_ctx.span_id
            assert restored_after_span.parent_span_id == trace_ctx.parent_span_id
            assert restored_after_span.session_id == trace_ctx.session_id
            assert restored_after_span.baggage == trace_ctx.baggage
        finally:
            # Detach trace → should restore to empty context
            detach(trace_token)

        restored_after_trace = current_context()
        assert restored_after_trace.trace_id == state_before_trace.trace_id
        assert restored_after_trace.span_id == state_before_trace.span_id
        assert restored_after_trace.parent_span_id == state_before_trace.parent_span_id


class TestProperty19EmptyContextSingletonWhenNoTraceActive:
    """Property 19: Empty context singleton when no trace active.

    *For any* number of calls to current_context() when no trace has been
    started, all calls SHALL return the same object identity (pre-allocated
    singleton) with trace_id=None and span_id=None.

    **Validates: Requirements 7.5**
    """

    @given(
        call_count=st.integers(min_value=2, max_value=20),
    )
    def test_empty_context_singleton_identity(
        self,
        call_count: int,
    ) -> None:
        """current_context() returns same identity with None trace_id/span_id."""
        # Ensure no trace is active by checking current state
        # (tests run with clean context due to try/finally in other tests)
        ctx = current_context()

        # If a trace happens to be active from another test, skip this check.
        # In practice, tests should clean up via detach, so this is defensive.
        if ctx.is_active:
            return

        empty = _empty_context()

        # All calls return the same singleton identity
        contexts = [current_context() for _ in range(call_count)]
        for c in contexts:
            assert c is empty  # Same object identity
            assert c.trace_id is None
            assert c.span_id is None
            assert c.parent_span_id is None
