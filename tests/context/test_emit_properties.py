"""Property-based tests for rc.emit() behavior.

Property 29: rc.emit delegates to EventBus and dispatches to OutputRenderers
Property 30: Framework lifecycle events excluded from on_event() dispatch
Property 31: OutputRenderer.on_event() exception isolation

Validates: Requirements 29.1, 29.4, 29.5, 29.9
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from functualize._config.job_config import JobConfigView
from functualize.job.context import RunContext

if TYPE_CHECKING:
    from functualize._events.bus import StructuredEvent

# --- Strategies ---

# Valid custom event names: {domain}.{resource}.{action}
# Must be at least 3 dot-separated segments of lowercase alphanumeric/underscores
_segment = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)

custom_event_names = st.tuples(_segment, _segment, _segment).map(
    lambda parts: f"{parts[0]}.{parts[1]}.{parts[2]}"
)

# Framework lifecycle event prefixes that must NOT be dispatched to on_event()
_framework_prefixes = (
    "job.execute.",
    "job.teardown.",
    "plugin.",
    "config.",
    "cli.",
    "tui.",
)

# Strategy for framework lifecycle event names
framework_event_names = st.one_of(
    st.tuples(
        st.sampled_from(["job.execute", "job.teardown"]),
        _segment,
    ).map(lambda parts: f"{parts[0]}.{parts[1]}"),
    st.tuples(
        st.sampled_from(["plugin", "config", "cli", "tui"]),
        _segment,
        _segment,
    ).map(lambda parts: f"{parts[0]}.{parts[1]}.{parts[2]}"),
)

# Arbitrary resource strings
resource_strings = st.text(
    min_size=0, max_size=50, alphabet=st.characters(categories=("L", "N", "P"))
)

# Payload keys (valid Python identifiers)
payload_keys = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)

# Payload values (simple JSON-like values)
payload_values = st.one_of(
    st.integers(min_value=-10000, max_value=10000),
    st.text(min_size=0, max_size=30),
    st.booleans(),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    st.none(),
)

# Number of renderers (1–6)
num_renderers = st.integers(min_value=1, max_value=6)


# --- Helpers ---


class FakeOutputRenderer:
    """A fake OutputRenderer that records on_event calls."""

    def __init__(self, name: str = "renderer", raise_exc: Exception | None = None):
        self.name = name
        self.events: list[StructuredEvent] = []
        self._raise_exc = raise_exc

    def render_log(self, message: str, level: str) -> None:
        pass

    def render_phase(self, phase: str, status: str) -> None:
        pass

    def render_progress(self, current: int, total: int, label: str) -> None:
        pass

    def on_job_start(self, job_name: str, metadata: dict[str, Any]) -> None:
        pass

    def on_log(self, level: str, message: str) -> None:
        pass

    def on_status_change(self, old_status: Any, new_status: Any, message: str) -> None:
        pass

    def on_phase_change(self, step: Any, action: str) -> None:
        pass

    def on_invoke_start(self, child_job_name: str, kwargs: dict[str, Any]) -> None:
        pass

    def on_invoke_end(self, child_job_name: str, result: Any) -> None:
        pass

    def on_job_end(self, job_name: str, result: Any) -> None:
        pass

    def on_event(self, event: StructuredEvent) -> None:
        if self._raise_exc is not None:
            raise self._raise_exc
        self.events.append(event)


def _make_rc(
    name: str = "test-job",
    renderers: list[Any] | None = None,
    event_bus: Any | None = None,
) -> RunContext:
    """Create a RunContext with optional OutputRenderers and EventBus."""
    config = MagicMock(spec=JobConfigView)
    config.set_prefix = MagicMock()
    logger = MagicMock()

    app = MagicMock()
    plugins: list = renderers if renderers is not None else []
    app._surfaces = plugins

    if event_bus is not None:
        app.event_bus = event_bus
        app._event_bus = None
    else:
        app.event_bus = MagicMock()
        app._event_bus = None

    engine = MagicMock()
    engine._app = app

    rc = RunContext(
        name=name,
        config=config,
        logger=logger,
        _execution_engine=engine,
    )
    return rc


# --- Property 29: rc.emit delegates to EventBus and dispatches to OutputRenderers ---


class TestProperty29EmitDelegatesAndDispatches:
    """For any custom event emitted via rc.emit(event_name, resource, **payload),
    the EventBus SHALL emit a StructuredEvent with the current PropagationContext
    attached, AND all active OutputRenderer instances SHALL receive the event via
    their on_event() method.

    **Validates: Requirements 29.1, 29.4**
    """

    @given(
        event_name=custom_event_names,
        resource=resource_strings,
        payload=st.dictionaries(keys=payload_keys, values=payload_values, max_size=5),
    )
    @settings(max_examples=100)
    def test_event_bus_receives_emit(
        self, event_name: str, resource: str, payload: dict[str, Any]
    ) -> None:
        """EventBus.emit is called with event_name, resource, and payload kwargs.

        **Validates: Requirements 29.1**
        """
        event_bus = MagicMock()
        rc = _make_rc(event_bus=event_bus)

        rc.emit(event_name, resource=resource, **payload)

        event_bus.emit.assert_called_once_with(event_name, resource=resource, **payload)

    @given(
        event_name=custom_event_names,
        resource=resource_strings,
        n=num_renderers,
    )
    @settings(max_examples=100)
    def test_all_output_renderers_receive_event(
        self, event_name: str, resource: str, n: int
    ) -> None:
        """All active OutputRenderers receive the event via on_event().

        **Validates: Requirements 29.4**
        """
        renderers = [FakeOutputRenderer(name=f"renderer-{i}") for i in range(n)]
        rc = _make_rc(renderers=renderers)

        rc.emit(event_name, resource=resource)

        for renderer in renderers:
            assert len(renderer.events) == 1
            event = renderer.events[0]
            assert event.event_name == event_name
            assert event.resource == resource

    @given(
        event_name=custom_event_names,
        resource=resource_strings,
        payload=st.dictionaries(keys=payload_keys, values=payload_values, max_size=5),
    )
    @settings(max_examples=100)
    def test_renderer_receives_structured_event_with_correct_fields(
        self, event_name: str, resource: str, payload: dict[str, Any]
    ) -> None:
        """OutputRenderers receive a StructuredEvent with event_name, resource,
        payload, and propagation context fields.

        **Validates: Requirements 29.1, 29.4**
        """
        renderer = FakeOutputRenderer()
        rc = _make_rc(renderers=[renderer])

        rc.emit(event_name, resource=resource, **payload)

        assert len(renderer.events) == 1
        event = renderer.events[0]
        assert event.event_name == event_name
        assert event.resource == resource
        assert event.payload == payload
        # PropagationContext attached (trace_id and span_id present as attributes)
        assert hasattr(event, "trace_id")
        assert hasattr(event, "span_id")

    @given(
        event_name=custom_event_names,
        resource=resource_strings,
        n=num_renderers,
        payload=st.dictionaries(keys=payload_keys, values=payload_values, max_size=3),
    )
    @settings(max_examples=100)
    def test_both_event_bus_and_renderers_receive_event(
        self, event_name: str, resource: str, n: int, payload: dict[str, Any]
    ) -> None:
        """Both EventBus and OutputRenderers receive the same event for any
        custom event emitted.

        **Validates: Requirements 29.1, 29.4**
        """
        event_bus = MagicMock()
        renderers = [FakeOutputRenderer(name=f"renderer-{i}") for i in range(n)]
        rc = _make_rc(renderers=renderers, event_bus=event_bus)

        rc.emit(event_name, resource=resource, **payload)

        # EventBus received
        event_bus.emit.assert_called_once_with(event_name, resource=resource, **payload)
        # All renderers received
        for renderer in renderers:
            assert len(renderer.events) == 1
            assert renderer.events[0].event_name == event_name


# --- Property 30: Framework lifecycle events excluded from on_event() dispatch ---


class TestProperty30FrameworkEventsExcluded:
    """For any event whose name matches framework patterns (job.execute.*,
    job.teardown.*, plugin.*, config.*, cli.*, tui.*), the engine SHALL NOT
    dispatch it to OutputRenderer.on_event(). These events are routed exclusively
    through typed lifecycle methods.

    **Validates: Requirements 29.5**
    """

    @given(
        event_name=framework_event_names,
        resource=resource_strings,
        n=num_renderers,
    )
    @settings(max_examples=100)
    def test_framework_events_not_dispatched_to_renderers(
        self, event_name: str, resource: str, n: int
    ) -> None:
        """Framework lifecycle events are NOT dispatched to on_event().

        **Validates: Requirements 29.5**
        """
        # Ensure we have a valid framework event
        assume(any(event_name.startswith(prefix) for prefix in _framework_prefixes))

        renderers = [FakeOutputRenderer(name=f"renderer-{i}") for i in range(n)]
        event_bus = MagicMock()
        rc = _make_rc(renderers=renderers, event_bus=event_bus)

        rc.emit(event_name, resource=resource)

        # EventBus still receives the event
        event_bus.emit.assert_called_once()
        # But NO renderer receives it via on_event()
        for renderer in renderers:
            assert len(renderer.events) == 0

    @given(
        event_name=custom_event_names,
        resource=resource_strings,
    )
    @settings(max_examples=100)
    def test_custom_events_are_dispatched_to_renderers(
        self, event_name: str, resource: str
    ) -> None:
        """Non-framework (custom) events ARE dispatched to on_event().

        **Validates: Requirements 29.5**
        """
        # Ensure the custom event does not accidentally match a framework prefix
        assume(not any(event_name.startswith(prefix) for prefix in _framework_prefixes))

        renderer = FakeOutputRenderer()
        rc = _make_rc(renderers=[renderer])

        rc.emit(event_name, resource=resource)

        assert len(renderer.events) == 1
        assert renderer.events[0].event_name == event_name

    @given(
        framework_name=framework_event_names,
        custom_name=custom_event_names,
        resource=resource_strings,
    )
    @settings(max_examples=100)
    def test_framework_filtered_while_custom_dispatched(
        self, framework_name: str, custom_name: str, resource: str
    ) -> None:
        """When both framework and custom events are emitted, only custom events
        reach on_event().

        **Validates: Requirements 29.5**
        """
        assume(any(framework_name.startswith(prefix) for prefix in _framework_prefixes))
        assume(
            not any(custom_name.startswith(prefix) for prefix in _framework_prefixes)
        )

        renderer = FakeOutputRenderer()
        rc = _make_rc(renderers=[renderer])

        rc.emit(framework_name, resource=resource)
        rc.emit(custom_name, resource=resource)

        # Only the custom event should have been dispatched
        assert len(renderer.events) == 1
        assert renderer.events[0].event_name == custom_name


# --- Property 31: OutputRenderer.on_event() exception isolation ---


class TestProperty31ExceptionIsolation:
    """For any OutputRenderer whose on_event() raises an exception, the engine
    SHALL log the error and continue dispatching the event to remaining renderers.

    **Validates: Requirements 29.9**
    """

    @given(
        event_name=custom_event_names,
        resource=resource_strings,
        n=st.integers(min_value=2, max_value=6),
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_failing_renderer_does_not_prevent_remaining_dispatch(
        self, event_name: str, resource: str, n: int, data: st.DataObject
    ) -> None:
        """Remaining renderers still receive the event when earlier ones raise.

        **Validates: Requirements 29.9**
        """
        assume(not any(event_name.startswith(prefix) for prefix in _framework_prefixes))

        # Pick which renderers will fail (at least one fails, at least one healthy)
        fail_positions = data.draw(
            st.lists(
                st.integers(min_value=0, max_value=n - 1),
                min_size=1,
                max_size=n - 1,
                unique=True,
            )
        )
        healthy_positions = [i for i in range(n) if i not in fail_positions]
        assume(len(healthy_positions) >= 1)

        renderers: list[FakeOutputRenderer] = []
        for i in range(n):
            if i in fail_positions:
                renderers.append(
                    FakeOutputRenderer(
                        name=f"failing-{i}",
                        raise_exc=RuntimeError(f"boom-{i}"),
                    )
                )
            else:
                renderers.append(FakeOutputRenderer(name=f"healthy-{i}"))

        rc = _make_rc(renderers=renderers)

        with patch("functualize._engine.capabilities.runcontext._module_logger"):
            rc.emit(event_name, resource=resource)

        # All healthy renderers received the event
        for i in healthy_positions:
            assert len(renderers[i].events) == 1
            assert renderers[i].events[0].event_name == event_name

    @given(
        event_name=custom_event_names,
        resource=resource_strings,
        n=st.integers(min_value=1, max_value=6),
    )
    @settings(max_examples=100)
    def test_all_failing_renderers_logged(
        self, event_name: str, resource: str, n: int
    ) -> None:
        """Each failing renderer's exception is logged at ERROR level.

        **Validates: Requirements 29.9**
        """
        assume(not any(event_name.startswith(prefix) for prefix in _framework_prefixes))

        renderers = [
            FakeOutputRenderer(
                name=f"failing-{i}",
                raise_exc=RuntimeError(f"error-{i}"),
            )
            for i in range(n)
        ]

        rc = _make_rc(renderers=renderers)

        with patch(
            "functualize._engine.capabilities.runcontext._module_logger"
        ) as mock_logger:
            rc.emit(event_name, resource=resource)

        # Each failing renderer produced one ERROR log
        assert mock_logger.error.call_count == n

    @given(
        event_name=custom_event_names,
        resource=resource_strings,
    )
    @settings(max_examples=100)
    def test_exception_does_not_propagate_to_caller(
        self, event_name: str, resource: str
    ) -> None:
        """Exceptions in on_event() do not propagate to the rc.emit() caller.

        **Validates: Requirements 29.9**
        """
        assume(not any(event_name.startswith(prefix) for prefix in _framework_prefixes))

        renderer = FakeOutputRenderer(name="exploding", raise_exc=ValueError("fatal"))
        rc = _make_rc(renderers=[renderer])

        with patch("functualize._engine.capabilities.runcontext._module_logger"):
            # Should not raise
            rc.emit(event_name, resource=resource)

    @given(
        event_name=custom_event_names,
        resource=resource_strings,
    )
    @settings(max_examples=50)
    def test_event_bus_still_called_when_renderers_fail(
        self, event_name: str, resource: str
    ) -> None:
        """EventBus dispatch occurs regardless of OutputRenderer failures.

        **Validates: Requirements 29.1, 29.9**
        """
        assume(not any(event_name.startswith(prefix) for prefix in _framework_prefixes))

        event_bus = MagicMock()
        renderer = FakeOutputRenderer(name="failing", raise_exc=RuntimeError("boom"))
        rc = _make_rc(renderers=[renderer], event_bus=event_bus)

        with patch("functualize._engine.capabilities.runcontext._module_logger"):
            rc.emit(event_name, resource=resource)

        # EventBus was still called
        event_bus.emit.assert_called_once()
