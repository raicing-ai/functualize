"""Tests for EventBus-based lifecycle events in JobExecutionEngine.

Previously tested InteractivityPlugin callback wiring (Task 3.3).
Now tests that the engine emits structured lifecycle events via EventBus,
which replaced the InteractivityPlugin protocol (per event-system-unification).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from functualize._engine.executor import JobExecutionEngine
from functualize._events.bus import EventBus
from functualize._events.hooks import HookRegistry


class _EventRecorder:
    """Records all events emitted via EventBus."""

    def __init__(self):
        self.events: list = []

    def __call__(self, event, **kwargs):
        self.events.append(event)


def _make_engine() -> tuple[JobExecutionEngine, EventBus, _EventRecorder]:
    """Create a minimal JobExecutionEngine with an EventBus for testing."""
    event_bus = EventBus()
    recorder = _EventRecorder()

    # Subscribe to all job events
    event_bus.subscribe("job.*", recorder)

    hook_registry = HookRegistry()
    di_registry = MagicMock()
    di_registry.available_types.return_value = set()
    middleware_chain = MagicMock()
    middleware_chain.has_middleware = False

    engine = JobExecutionEngine(
        di_registry=di_registry,
        hook_registry=hook_registry,
        middleware_chain=middleware_chain,
        event_bus=event_bus,
    )
    return engine, event_bus, recorder


class TestEngineLifecycleEvents:
    """Engine emits structured lifecycle events via EventBus."""

    def test_engine_emits_start_and_end_events(self):
        """execute() emits job.execute.start and job.execute.end events."""
        engine, event_bus, recorder = _make_engine()

        def my_job():
            pass

        engine.execute("my_job", my_job, kwargs={})

        event_names = [e.event_name for e in recorder.events]
        assert "job.execute.start" in event_names
        assert "job.execute.end" in event_names

    def test_start_event_contains_job_name(self):
        """job.execute.start event includes the job_name."""
        engine, event_bus, recorder = _make_engine()

        def my_job():
            pass

        engine.execute("deploy_app", my_job, kwargs={})

        start_events = [
            e for e in recorder.events if e.event_name == "job.execute.start"
        ]
        assert len(start_events) == 1
        assert start_events[0].payload["job_name"] == "deploy_app"

    def test_end_event_contains_success_status(self):
        """job.execute.end event includes status='success' on successful run."""
        engine, event_bus, recorder = _make_engine()

        def my_job():
            return "done"

        engine.execute("my_job", my_job, kwargs={})

        end_events = [e for e in recorder.events if e.event_name == "job.execute.end"]
        assert len(end_events) == 1
        assert end_events[0].payload["status"] == "success"

    def test_end_event_contains_failure_status(self):
        """job.execute.end event includes status='failure' on exception."""
        engine, event_bus, recorder = _make_engine()

        def failing_job():
            raise RuntimeError("boom")

        engine.execute("failing_job", failing_job, kwargs={})

        end_events = [e for e in recorder.events if e.event_name == "job.execute.end"]
        assert len(end_events) == 1
        assert end_events[0].payload["status"] == "failure"

    def test_end_event_contains_duration(self):
        """job.execute.end event includes duration_ms."""
        engine, event_bus, recorder = _make_engine()

        def my_job():
            pass

        engine.execute("my_job", my_job, kwargs={})

        end_events = [e for e in recorder.events if e.event_name == "job.execute.end"]
        assert len(end_events) == 1
        assert "duration_ms" in end_events[0].payload
        assert end_events[0].payload["duration_ms"] >= 0

    def test_exception_does_not_prevent_end_event(self):
        """Even when the job raises, the end event is still emitted."""
        engine, event_bus, recorder = _make_engine()

        def failing():
            raise ValueError("oops")

        engine.execute("failing", failing, kwargs={})

        event_names = [e.event_name for e in recorder.events]
        assert "job.execute.end" in event_names
