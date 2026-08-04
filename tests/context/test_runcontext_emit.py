"""Unit tests for RunContext.emit() method.

Tests delegation to EventBus, Surface dispatch, framework event
filtering, error isolation, and zero-cost behavior.

Validates: Requirements 29.1, 29.2, 29.3, 29.4, 29.5, 29.6, 29.7, 29.8, 29.9
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from functualize._config.job_config import JobConfigView
from functualize.job.context import RunContext

if TYPE_CHECKING:
    from functualize._events.bus import StructuredEvent

# --- Helpers ---


class FakeSurface:
    """A fake Surface that records handle_event calls."""

    name: str = "fake-surface"

    def __init__(self, raise_on_event: Exception | None = None):
        self.events: list[StructuredEvent] = []
        self._raise_on_event = raise_on_event

    def handle_event(self, event: StructuredEvent) -> None:
        if self._raise_on_event is not None:
            raise self._raise_on_event
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

    # Build a mock app
    app = MagicMock()
    plugins: list = renderers if renderers is not None else []
    app._surfaces = plugins

    if event_bus is not None:
        app.event_bus = event_bus
        app._event_bus = None
    else:
        app.event_bus = MagicMock()
        app._event_bus = None

    # Build a mock execution engine referencing the app
    engine = MagicMock()
    engine._app = app

    rc = RunContext(
        name=name,
        config=config,
        logger=logger,
        _execution_engine=engine,
    )
    return rc


# --- Tests ---


class TestEmitDelegatesToEventBus:
    """Tests that rc.emit() delegates to the app's EventBus."""

    def test_delegates_to_event_bus(self):
        """emit() calls event_bus.emit with event_name, resource, and payload."""
        event_bus = MagicMock()
        rc = _make_rc(event_bus=event_bus)

        rc.emit("deploy.artifact.upload_end", resource="api.tar.gz", duration_ms=1200)

        event_bus.emit.assert_called_once_with(
            "deploy.artifact.upload_end",
            resource="api.tar.gz",
            duration_ms=1200,
        )

    def test_empty_payload(self):
        """emit() with no payload still delegates to EventBus."""
        event_bus = MagicMock()
        rc = _make_rc(event_bus=event_bus)

        rc.emit("custom.domain.action")

        event_bus.emit.assert_called_once_with(
            "custom.domain.action",
            resource="",
        )

    def test_resource_defaults_to_empty_string(self):
        """emit() passes resource="" by default."""
        event_bus = MagicMock()
        rc = _make_rc(event_bus=event_bus)

        rc.emit("custom.domain.action")

        call_kwargs = event_bus.emit.call_args
        assert (
            call_kwargs.kwargs.get(
                "resource", call_kwargs.args[1] if len(call_kwargs.args) > 1 else ""
            )
            == ""
        )


class TestEmitSurfaceDispatch:
    """Tests that rc.emit() dispatches to active Surfaces."""

    def test_dispatches_to_output_renderer(self):
        """emit() dispatches StructuredEvent to Surface.handle_event()."""
        renderer = FakeSurface()
        rc = _make_rc(renderers=[renderer])

        rc.emit("deploy.artifact.upload_end", resource="api.tar.gz", duration_ms=1200)

        assert len(renderer.events) == 1
        event = renderer.events[0]
        assert event.event_name == "deploy.artifact.upload_end"
        assert event.resource == "api.tar.gz"
        assert event.payload == {"duration_ms": 1200}

    def test_dispatches_to_multiple_renderers(self):
        """emit() dispatches to all registered Surfaces."""
        renderer1 = FakeSurface()
        renderer2 = FakeSurface()
        rc = _make_rc(renderers=[renderer1, renderer2])

        rc.emit("custom.domain.action", resource="res")

        assert len(renderer1.events) == 1
        assert len(renderer2.events) == 1

    def test_event_has_propagation_context(self):
        """StructuredEvent includes trace_id and span_id from PropagationContext."""
        renderer = FakeSurface()
        rc = _make_rc(renderers=[renderer])

        rc.emit("custom.domain.action")

        event = renderer.events[0]
        # trace_id and span_id are set from current_context()
        # They should be strings (even if None is possible in some contexts)
        assert hasattr(event, "trace_id")
        assert hasattr(event, "span_id")


class TestEmitFrameworkEventFilter:
    """Tests that framework lifecycle events are excluded from on_event()."""

    @pytest.mark.parametrize(
        "event_name",
        [
            "job.execute.start",
            "job.execute.end",
            "job.teardown.start",
            "job.teardown.end",
            "plugin.load.start",
            "plugin.load.end",
            "config.file.parse",
            "config.resolution.start",
            "cli.command.start",
            "cli.command.end",
            "tui.started.event",
            "tui.render.frame",
        ],
    )
    def test_framework_events_not_dispatched_to_on_event(self, event_name: str):
        """Framework lifecycle events are NOT dispatched to Surface.handle_event()."""
        renderer = FakeSurface()
        event_bus = MagicMock()
        rc = _make_rc(renderers=[renderer], event_bus=event_bus)

        rc.emit(event_name, resource="test")

        # EventBus still receives the event
        event_bus.emit.assert_called_once()
        # But Surface does NOT receive it
        assert len(renderer.events) == 0

    @pytest.mark.parametrize(
        "event_name",
        [
            "deploy.artifact.upload_end",
            "migration.table.created",
            "custom.domain.action",
            "build.step.completed",
        ],
    )
    def test_custom_events_dispatched_to_on_event(self, event_name: str):
        """Custom domain events ARE dispatched to Surface.handle_event()."""
        renderer = FakeSurface()
        rc = _make_rc(renderers=[renderer])

        rc.emit(event_name)

        assert len(renderer.events) == 1
        assert renderer.events[0].event_name == event_name


class TestEmitErrorIsolation:
    """Tests that Surface.handle_event() errors are logged and isolated."""

    def test_renderer_exception_logged_and_continues(self):
        """If on_event() raises, error is logged and remaining renderers still receive."""
        failing_renderer = FakeSurface(raise_on_event=RuntimeError("boom"))
        healthy_renderer = FakeSurface()
        rc = _make_rc(renderers=[failing_renderer, healthy_renderer])

        with patch(
            "functualize._engine.capabilities.runcontext._module_logger"
        ) as mock_logger:
            rc.emit("custom.domain.action")

        # Healthy renderer still got the event
        assert len(healthy_renderer.events) == 1
        # Error was logged
        mock_logger.error.assert_called_once()
        error_msg = mock_logger.error.call_args.args[0]
        assert "fake-surface" in error_msg
        assert "custom.domain.action" in error_msg

    def test_all_renderers_failing_still_logs_all(self):
        """All renderers raising is handled gracefully."""
        renderer1 = FakeSurface(raise_on_event=ValueError("err1"))
        renderer2 = FakeSurface(raise_on_event=TypeError("err2"))
        rc = _make_rc(renderers=[renderer1, renderer2])

        with patch(
            "functualize._engine.capabilities.runcontext._module_logger"
        ) as mock_logger:
            rc.emit("custom.domain.action")

        # Both errors were logged
        assert mock_logger.error.call_count == 2


class TestEmitZeroCost:
    """Tests the zero-cost behavior when no renderers/subscribers."""

    def test_no_engine_returns_immediately(self):
        """emit() is a no-op when no execution engine is set."""
        config = MagicMock(spec=JobConfigView)
        config.set_prefix = MagicMock()
        logger = MagicMock()

        rc = RunContext(
            name="test-job",
            config=config,
            logger=logger,
            _execution_engine=None,
        )

        # Should not raise
        rc.emit("custom.domain.action")

    def test_no_renderers_skips_dispatch(self):
        """emit() skips Surface dispatch when none registered."""
        event_bus = MagicMock()
        rc = _make_rc(renderers=[], event_bus=event_bus)

        rc.emit("custom.domain.action")

        # EventBus still called
        event_bus.emit.assert_called_once()

    def test_non_surface_registrants_are_ignored(self):
        """A registrant without handle_event is not a Surface, so it is
        skipped by the event fan-out (e.g. a collect-only PromptCollector)."""
        # A collector-only object: has collect(), lacks handle_event.
        non_surface = MagicMock(spec=["collect", "name"])
        non_surface.name = "collector-only"

        event_bus = MagicMock()
        rc = _make_rc(renderers=[non_surface], event_bus=event_bus)

        # Should not raise, and the fan-out simply skips it.
        rc.emit("custom.domain.action")


class TestOnEvent:
    """rc.on_event() — the inbound counterpart to emit(), used by job-owned UIs."""

    def test_subscriber_receives_emitted_event(self):
        """A real bus round-trip: subscribe, emit, observe."""
        from functualize._events.bus import EventBus

        received: list[Any] = []
        rc = _make_rc(event_bus=EventBus())

        rc.on_event("custom.*", received.append)
        rc.emit("custom.domain.action", resource="res-1")

        assert len(received) == 1
        assert received[0].event_name == "custom.domain.action"
        assert received[0].resource == "res-1"

    def test_off_event_stops_delivery(self):
        from functualize._events.bus import EventBus

        received: list[Any] = []
        rc = _make_rc(event_bus=EventBus())

        handle = rc.on_event("custom.*", received.append)
        rc.emit("custom.domain.first")
        rc.off_event(handle)
        rc.emit("custom.domain.second")

        assert [e.event_name for e in received] == ["custom.domain.first"]

    def test_returns_none_without_a_bus(self):
        """Callers subscribe unconditionally, so a bus-less context must not
        raise — it just never delivers."""
        rc = RunContext(
            name="test-job",
            config=MagicMock(spec=JobConfigView),
            logger=MagicMock(),
            _execution_engine=None,
        )

        assert rc.on_event("custom.*", lambda _event: None) is None

    def test_off_event_tolerates_none_handle(self):
        """Teardown passes back whatever on_event returned, including None."""
        rc = RunContext(
            name="test-job",
            config=MagicMock(spec=JobConfigView),
            logger=MagicMock(),
            _execution_engine=None,
        )

        rc.off_event(None)  # must not raise
