"""Unit tests for step lifecycle hooks integration in RunContext.track_phase.

Tests task 8.2:
- ON_PHASE_START fires only when step is NEW (first call with that step_name)
- ON_PHASE_FAILURE fires when step transitions to FAILURE
- ON_PHASE_COMPLETE fires when step transitions to SUCCESS
- _fire_step_hook helper with error isolation (log and continue)
- Both global and job-scoped registration
"""

import logging
from unittest.mock import MagicMock

import pytest

from functualize._config.job_config import JobConfigView
from functualize._events.hooks import HookEvent, HookRegistry
from functualize.job.context import RunContext, RunStatus


class FakeExecutionEngine:
    """Minimal fake execution engine providing a HookRegistry."""

    def __init__(self) -> None:
        self._hook_registry = HookRegistry()


@pytest.fixture
def hook_registry() -> HookRegistry:
    return HookRegistry()


@pytest.fixture
def engine(hook_registry: HookRegistry) -> FakeExecutionEngine:
    eng = FakeExecutionEngine()
    eng._hook_registry = hook_registry
    return eng


@pytest.fixture
def rc(engine: FakeExecutionEngine) -> RunContext:
    """Create a RunContext with a fake execution engine for hook dispatch."""
    config = MagicMock(spec=JobConfigView)
    logger = MagicMock(spec=logging.Logger)
    return RunContext(
        name="test-job",
        config=config,
        logger=logger,
        _execution_engine=engine,
    )


class TestOnStepStart:
    """ON_PHASE_START fires only when a step is NEW (first call)."""

    def test_fires_on_new_step(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_START hook is called when a step is created for the first time."""
        calls: list[tuple[str, RunStatus, str]] = []

        def on_start(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            calls.append((name, status, msg))

        hook_registry.register_global(HookEvent.ON_PHASE_START, on_start)
        rc.track_phase("deploy", "starting deploy", RunStatus.RUNNING)

        assert len(calls) == 1
        assert calls[0] == ("deploy", RunStatus.RUNNING, "starting deploy")

    def test_does_not_fire_on_step_update(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_START does NOT fire when an existing step is updated."""
        calls: list[str] = []

        def on_start(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            calls.append(name)

        hook_registry.register_global(HookEvent.ON_PHASE_START, on_start)

        rc.track_phase("build", "building", RunStatus.RUNNING)
        rc.track_phase("build", "done", RunStatus.SUCCESS)

        # Should only fire once (on creation), not on update
        assert len(calls) == 1

    def test_fires_for_each_new_step_name(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_START fires for each distinct new step name."""
        calls: list[str] = []

        def on_start(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            calls.append(name)

        hook_registry.register_global(HookEvent.ON_PHASE_START, on_start)

        rc.track_phase("step1", "msg1", RunStatus.RUNNING)
        rc.track_phase("step2", "msg2", RunStatus.RUNNING)
        rc.track_phase("step3", "msg3", RunStatus.RUNNING)

        assert calls == ["step1", "step2", "step3"]

    def test_fires_even_if_created_with_terminal_status(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_START fires when step is created with a terminal status (e.g. FAILURE)."""
        calls: list[tuple[str, RunStatus]] = []

        def on_start(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            calls.append((name, status))

        hook_registry.register_global(HookEvent.ON_PHASE_START, on_start)
        rc.track_phase("quick-fail", "immediate fail", RunStatus.FAILURE)

        assert len(calls) == 1
        assert calls[0] == ("quick-fail", RunStatus.FAILURE)


class TestOnStepFailure:
    """ON_PHASE_FAILURE fires when step transitions to FAILURE."""

    def test_fires_on_failure_status(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_FAILURE hook fires when step status is FAILURE."""
        calls: list[tuple[str, RunStatus, str]] = []

        def on_failure(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            calls.append((name, status, msg))

        hook_registry.register_global(HookEvent.ON_PHASE_FAILURE, on_failure)

        rc.track_phase("deploy", "starting", RunStatus.RUNNING)
        rc.track_phase("deploy", "deploy failed", RunStatus.FAILURE)

        assert len(calls) == 1
        assert calls[0] == ("deploy", RunStatus.FAILURE, "deploy failed")

    def test_does_not_fire_on_success(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_FAILURE does NOT fire when step transitions to SUCCESS."""
        calls: list[str] = []

        def on_failure(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            calls.append(name)

        hook_registry.register_global(HookEvent.ON_PHASE_FAILURE, on_failure)

        rc.track_phase("build", "building", RunStatus.RUNNING)
        rc.track_phase("build", "done", RunStatus.SUCCESS)

        assert len(calls) == 0

    def test_fires_on_initial_failure(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_FAILURE fires when a step is created directly with FAILURE."""
        calls: list[str] = []

        def on_failure(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            calls.append(name)

        hook_registry.register_global(HookEvent.ON_PHASE_FAILURE, on_failure)
        rc.track_phase("fast-fail", "immediate", RunStatus.FAILURE)

        assert len(calls) == 1
        assert calls[0] == "fast-fail"

    def test_does_not_fire_on_running(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_FAILURE does NOT fire for RUNNING status."""
        calls: list[str] = []

        def on_failure(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            calls.append(name)

        hook_registry.register_global(HookEvent.ON_PHASE_FAILURE, on_failure)
        rc.track_phase("step", "starting", RunStatus.RUNNING)

        assert len(calls) == 0


class TestOnStepComplete:
    """ON_PHASE_COMPLETE fires when step transitions to SUCCESS."""

    def test_fires_on_success_status(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_COMPLETE hook fires when step status is SUCCESS."""
        calls: list[tuple[str, RunStatus, str]] = []

        def on_complete(
            ctx: RunContext, name: str, status: RunStatus, msg: str
        ) -> None:
            calls.append((name, status, msg))

        hook_registry.register_global(HookEvent.ON_PHASE_COMPLETE, on_complete)

        rc.track_phase("build", "building", RunStatus.RUNNING)
        rc.track_phase("build", "build done", RunStatus.SUCCESS)

        assert len(calls) == 1
        assert calls[0] == ("build", RunStatus.SUCCESS, "build done")

    def test_does_not_fire_on_failure(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_COMPLETE does NOT fire when step transitions to FAILURE."""
        calls: list[str] = []

        def on_complete(
            ctx: RunContext, name: str, status: RunStatus, msg: str
        ) -> None:
            calls.append(name)

        hook_registry.register_global(HookEvent.ON_PHASE_COMPLETE, on_complete)

        rc.track_phase("deploy", "deploying", RunStatus.RUNNING)
        rc.track_phase("deploy", "failed", RunStatus.FAILURE)

        assert len(calls) == 0

    def test_fires_on_initial_success(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_COMPLETE fires when a step is created directly with SUCCESS."""
        calls: list[str] = []

        def on_complete(
            ctx: RunContext, name: str, status: RunStatus, msg: str
        ) -> None:
            calls.append(name)

        hook_registry.register_global(HookEvent.ON_PHASE_COMPLETE, on_complete)
        rc.track_phase("cached", "already done", RunStatus.SUCCESS)

        assert len(calls) == 1
        assert calls[0] == "cached"


class TestStepHookErrorIsolation:
    """Error isolation: hook exceptions are logged and don't break step tracking."""

    def test_exception_logged_and_continues(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """Hook exception is logged and remaining hooks continue."""
        second_calls: list[str] = []

        def bad_hook(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            raise RuntimeError("hook exploded")

        def good_hook(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            second_calls.append(name)

        hook_registry.register_global(HookEvent.ON_PHASE_START, bad_hook)
        hook_registry.register_global(HookEvent.ON_PHASE_START, good_hook)

        rc.track_phase("deploy", "starting", RunStatus.RUNNING)

        # Second hook still called despite first failing
        assert second_calls == ["deploy"]

    def test_exception_does_not_prevent_step_tracking(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """Hook exception doesn't prevent the step from being recorded."""

        def bad_hook(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            raise ValueError("kaboom")

        hook_registry.register_global(HookEvent.ON_PHASE_START, bad_hook)
        rc.track_phase("deploy", "starting", RunStatus.RUNNING)

        step = rc.get_phase("deploy")
        assert step is not None
        assert step["status"] == RunStatus.RUNNING

    def test_failure_hook_exception_isolated(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """ON_PHASE_FAILURE hook exception doesn't break subsequent operations."""

        def bad_failure_hook(
            ctx: RunContext, name: str, status: RunStatus, msg: str
        ) -> None:
            raise RuntimeError("failure hook failed")

        hook_registry.register_global(HookEvent.ON_PHASE_FAILURE, bad_failure_hook)

        rc.track_phase("step", "starting", RunStatus.RUNNING)
        rc.track_phase("step", "failed", RunStatus.FAILURE)

        step = rc.get_phase("step")
        assert step is not None
        assert step["status"] == RunStatus.FAILURE


class TestStepHookJobScoped:
    """Job-scoped hook registration support."""

    def test_job_scoped_hook_fires_for_matching_job(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """Job-scoped hook fires when the RunContext name matches."""
        calls: list[str] = []

        def scoped_hook(
            ctx: RunContext, name: str, status: RunStatus, msg: str
        ) -> None:
            calls.append(name)

        hook_registry.register_for_job(
            "test-job", HookEvent.ON_PHASE_START, scoped_hook
        )

        rc.track_phase("deploy", "starting", RunStatus.RUNNING)
        assert calls == ["deploy"]

    def test_job_scoped_hook_does_not_fire_for_other_job(
        self, hook_registry: HookRegistry
    ) -> None:
        """Job-scoped hook does NOT fire for a RunContext with a different name."""
        calls: list[str] = []

        def scoped_hook(
            ctx: RunContext, name: str, status: RunStatus, msg: str
        ) -> None:
            calls.append(name)

        hook_registry.register_for_job(
            "other-job", HookEvent.ON_PHASE_START, scoped_hook
        )

        # Create a RunContext with name="test-job" (different from "other-job")
        engine = FakeExecutionEngine()
        engine._hook_registry = hook_registry
        config = MagicMock(spec=JobConfigView)
        logger = MagicMock(spec=logging.Logger)
        rc2 = RunContext(
            name="test-job",
            config=config,
            logger=logger,
            _execution_engine=engine,
        )

        rc2.track_phase("deploy", "starting", RunStatus.RUNNING)
        assert calls == []

    def test_global_and_job_scoped_both_fire(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """Both global and job-scoped hooks fire (global first)."""
        calls: list[str] = []

        def global_hook(
            ctx: RunContext, name: str, status: RunStatus, msg: str
        ) -> None:
            calls.append("global")

        def scoped_hook(
            ctx: RunContext, name: str, status: RunStatus, msg: str
        ) -> None:
            calls.append("scoped")

        hook_registry.register_global(HookEvent.ON_PHASE_START, global_hook)
        hook_registry.register_for_job(
            "test-job", HookEvent.ON_PHASE_START, scoped_hook
        )

        rc.track_phase("deploy", "starting", RunStatus.RUNNING)
        assert calls == ["global", "scoped"]


class TestStepHookWithoutEngine:
    """When no execution engine is attached, hooks simply don't fire."""

    def test_no_engine_no_error(self) -> None:
        """track_phase works fine without an execution engine."""
        config = MagicMock(spec=JobConfigView)
        logger = MagicMock(spec=logging.Logger)
        rc = RunContext(name="test-job", config=config, logger=logger)

        # Should not raise
        rc.track_phase("deploy", "starting", RunStatus.RUNNING)
        assert rc.get_phase("deploy") is not None


class TestStepHookCombinedEvents:
    """Test that ON_PHASE_START and ON_PHASE_FAILURE/COMPLETE can fire together."""

    def test_new_step_with_failure_fires_both_start_and_failure(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """When a step is created with FAILURE, both ON_PHASE_START and ON_PHASE_FAILURE fire."""
        events: list[str] = []

        def on_start(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            events.append("start")

        def on_failure(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            events.append("failure")

        hook_registry.register_global(HookEvent.ON_PHASE_START, on_start)
        hook_registry.register_global(HookEvent.ON_PHASE_FAILURE, on_failure)

        rc.track_phase("fast-fail", "instant fail", RunStatus.FAILURE)

        assert events == ["start", "failure"]

    def test_new_step_with_success_fires_both_start_and_complete(
        self, rc: RunContext, hook_registry: HookRegistry
    ) -> None:
        """When a step is created with SUCCESS, both ON_PHASE_START and ON_PHASE_COMPLETE fire."""
        events: list[str] = []

        def on_start(ctx: RunContext, name: str, status: RunStatus, msg: str) -> None:
            events.append("start")

        def on_complete(
            ctx: RunContext, name: str, status: RunStatus, msg: str
        ) -> None:
            events.append("complete")

        hook_registry.register_global(HookEvent.ON_PHASE_START, on_start)
        hook_registry.register_global(HookEvent.ON_PHASE_COMPLETE, on_complete)

        rc.track_phase("cached", "already done", RunStatus.SUCCESS)

        assert events == ["start", "complete"]
