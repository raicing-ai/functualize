"""Tests for PRE_EXECUTE hook integration in JobExecutionEngine."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from functualize._app.state import AppState
from functualize._config.chain import ResolutionChain
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain
from functualize._events.bus import EventBus
from functualize._events.hooks import HookDecision, HookEvent, HookRegistry
from functualize._events.middleware_stack import MiddlewareStack
from functualize._types.enums import RunStatus


def _make_app() -> MagicMock:
    app = MagicMock()
    app.event_bus = EventBus()
    app.middleware = MiddlewareStack()
    app._resolution_chain = ResolutionChain([])
    app.plugin_config_registry = MagicMock()
    app.plugin_config_registry.get_all.return_value = {}
    app._surfaces = []
    return app


@pytest.fixture(autouse=True)
def setup_app_state():
    AppState.reset()
    AppState.set("config_directory", ".")
    AppState.set("environment", "DEV")


class TestEnginePreExecuteBlock:
    """Engine skips job and returns FAILURE on PRE_EXECUTE BLOCK."""

    def test_block_skips_job_execution(self):
        """When PRE_EXECUTE returns BLOCK, the job function is never called."""
        hook_registry = HookRegistry()
        engine = JobExecutionEngine(
            di_registry=MagicMock(),
            event_bus=MagicMock(),
            hook_registry=hook_registry,
            middleware_chain=ExecutionMiddlewareChain(),
        )

        hook_registry.register_global(
            HookEvent.PRE_EXECUTE,
            lambda rc, kwargs: HookDecision.BLOCK("permission denied"),
        )

        executed = []

        def my_job():
            executed.append(True)

        result = engine.execute("my_job", my_job, kwargs={})

        assert executed == []
        assert result.status == RunStatus.FAILURE

    def test_block_fires_on_teardown(self):
        """When PRE_EXECUTE returns BLOCK, ON_TEARDOWN hooks are still invoked."""
        hook_registry = HookRegistry()
        engine = JobExecutionEngine(
            di_registry=MagicMock(),
            event_bus=MagicMock(),
            hook_registry=hook_registry,
            middleware_chain=ExecutionMiddlewareChain(),
        )

        teardown_called = []

        hook_registry.register_global(
            HookEvent.PRE_EXECUTE,
            lambda rc, kwargs: HookDecision.BLOCK("blocked"),
        )
        hook_registry.register_global(
            HookEvent.ON_TEARDOWN,
            lambda rc: teardown_called.append(True),
        )

        result = engine.execute("my_job", lambda: None, kwargs={})

        assert result.status == RunStatus.FAILURE
        assert teardown_called == [True]

    def test_block_does_not_fire_before_job(self):
        """When PRE_EXECUTE returns BLOCK, BEFORE_JOB hooks are NOT invoked."""
        hook_registry = HookRegistry()
        engine = JobExecutionEngine(
            di_registry=MagicMock(),
            event_bus=MagicMock(),
            hook_registry=hook_registry,
            middleware_chain=ExecutionMiddlewareChain(),
        )

        before_job_called = []

        hook_registry.register_global(
            HookEvent.PRE_EXECUTE,
            lambda rc, kwargs: HookDecision.BLOCK("blocked"),
        )
        hook_registry.register_global(
            HookEvent.BEFORE_JOB,
            lambda rc: before_job_called.append(True),
        )

        engine.execute("my_job", lambda: None, kwargs={})

        assert before_job_called == []


class TestEnginePreExecuteModify:
    """Engine replaces call kwargs on PRE_EXECUTE MODIFY."""

    def test_modify_changes_job_kwargs(self):
        """When PRE_EXECUTE returns MODIFY, the job receives modified kwargs."""
        hook_registry = HookRegistry()
        engine = JobExecutionEngine(
            di_registry=MagicMock(),
            event_bus=MagicMock(),
            hook_registry=hook_registry,
            middleware_chain=ExecutionMiddlewareChain(),
        )

        hook_registry.register_global(
            HookEvent.PRE_EXECUTE,
            lambda rc, kwargs: HookDecision.MODIFY({"value": 42}),
        )

        received = []

        def my_job(value=0):
            received.append(value)

        engine.execute("my_job", my_job, kwargs={"value": 1})

        assert received == [42]

    def test_modify_chain_accumulates(self):
        """Multiple MODIFY hooks chain — each sees the previous modification."""
        hook_registry = HookRegistry()
        engine = JobExecutionEngine(
            di_registry=MagicMock(),
            event_bus=MagicMock(),
            hook_registry=hook_registry,
            middleware_chain=ExecutionMiddlewareChain(),
        )

        def add_ten(rc, kwargs):
            return HookDecision.MODIFY({"value": kwargs["value"] + 10})

        def add_hundred(rc, kwargs):
            return HookDecision.MODIFY({"value": kwargs["value"] + 100})

        hook_registry.register_global(HookEvent.PRE_EXECUTE, add_ten)
        hook_registry.register_global(HookEvent.PRE_EXECUTE, add_hundred)

        received = []

        def my_job(value=0):
            received.append(value)

        engine.execute("my_job", my_job, kwargs={"value": 1})

        assert received == [111]


class TestEnginePreExecuteProceed:
    """Engine continues normally on PROCEED/None."""

    def test_proceed_does_not_alter_kwargs(self):
        """PROCEED hooks don't modify the kwargs passed to the job."""
        hook_registry = HookRegistry()
        engine = JobExecutionEngine(
            di_registry=MagicMock(),
            event_bus=MagicMock(),
            hook_registry=hook_registry,
            middleware_chain=ExecutionMiddlewareChain(),
        )

        hook_registry.register_global(
            HookEvent.PRE_EXECUTE,
            lambda rc, kwargs: HookDecision.PROCEED(),
        )

        received = []

        def my_job(value=0):
            received.append(value)

        engine.execute("my_job", my_job, kwargs={"value": 7})

        assert received == [7]

    def test_no_pre_execute_hooks_normal_execution(self):
        """Without PRE_EXECUTE hooks, job executes normally."""
        hook_registry = HookRegistry()
        engine = JobExecutionEngine(
            di_registry=MagicMock(),
            event_bus=MagicMock(),
            hook_registry=hook_registry,
            middleware_chain=ExecutionMiddlewareChain(),
        )

        executed = []

        def my_job():
            executed.append(True)

        result = engine.execute("my_job", my_job, kwargs={})

        assert executed == [True]
        assert result.status == RunStatus.SUCCESS


class TestEnginePreExecuteExceptionHandling:
    """Engine treats PRE_EXECUTE hook exceptions as PROCEED."""

    def test_exception_in_hook_continues_execution(self):
        """A PRE_EXECUTE hook that raises does not prevent job execution."""
        hook_registry = HookRegistry()
        engine = JobExecutionEngine(
            di_registry=MagicMock(),
            event_bus=MagicMock(),
            hook_registry=hook_registry,
            middleware_chain=ExecutionMiddlewareChain(),
        )

        def bad_hook(rc, kwargs):
            raise RuntimeError("hook error")

        hook_registry.register_global(HookEvent.PRE_EXECUTE, bad_hook)

        executed = []

        def my_job():
            executed.append(True)

        result = engine.execute("my_job", my_job, kwargs={})

        assert executed == [True]
        assert result.status == RunStatus.SUCCESS
