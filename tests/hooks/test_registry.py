"""Unit tests for HookRegistry and HookEvent."""

import logging
from unittest.mock import MagicMock

import pytest

from functualize._events.hooks import HookEvent, HookRegistry
from functualize.job.context import RunContext


@pytest.fixture
def registry():
    """Create a fresh HookRegistry instance."""
    return HookRegistry()


@pytest.fixture
def mock_rc():
    """Create a mock RunContext."""
    return MagicMock(spec=RunContext)


class TestHookEvent:
    """Tests for HookEvent constants."""

    def test_before_job_value(self):
        assert HookEvent.BEFORE_JOB == "before_job"

    def test_after_success_value(self):
        assert HookEvent.AFTER_SUCCESS == "after_success"

    def test_after_failure_value(self):
        assert HookEvent.AFTER_FAILURE == "after_failure"

    def test_on_teardown_value(self):
        assert HookEvent.ON_TEARDOWN == "on_teardown"


class TestRegisterGlobal:
    """Tests for register_global method."""

    def test_register_single_hook(self, registry, mock_rc):
        called = []
        registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: called.append("hook1")
        )
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc)
        assert called == ["hook1"]

    def test_register_multiple_hooks_same_event(self, registry, mock_rc):
        called = []
        registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: called.append("hook1")
        )
        registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: called.append("hook2")
        )
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc)
        assert called == ["hook1", "hook2"]

    def test_register_hooks_different_events(self, registry, mock_rc):
        called = []
        registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: called.append("before")
        )
        registry.register_global(
            HookEvent.AFTER_SUCCESS, lambda rc: called.append("after")
        )
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc)
        assert called == ["before"]


class TestRegisterForJob:
    """Tests for register_for_job method."""

    def test_register_job_scoped_hook(self, registry, mock_rc):
        called = []
        registry.register_for_job(
            "my_job", HookEvent.BEFORE_JOB, lambda rc: called.append("job_hook")
        )
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc)
        assert called == ["job_hook"]

    def test_job_scoped_hook_not_invoked_for_other_jobs(self, registry, mock_rc):
        called = []
        registry.register_for_job(
            "my_job", HookEvent.BEFORE_JOB, lambda rc: called.append("job_hook")
        )
        registry.invoke(HookEvent.BEFORE_JOB, "other_job", mock_rc)
        assert called == []

    def test_multiple_job_scoped_hooks(self, registry, mock_rc):
        called = []
        registry.register_for_job(
            "my_job", HookEvent.BEFORE_JOB, lambda rc: called.append("h1")
        )
        registry.register_for_job(
            "my_job", HookEvent.BEFORE_JOB, lambda rc: called.append("h2")
        )
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc)
        assert called == ["h1", "h2"]


class TestInvoke:
    """Tests for invoke method."""

    def test_global_hooks_invoked_before_job_hooks(self, registry, mock_rc):
        called = []
        registry.register_for_job(
            "my_job", HookEvent.BEFORE_JOB, lambda rc: called.append("job")
        )
        registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: called.append("global")
        )
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc)
        assert called == ["global", "job"]

    def test_after_failure_passes_exception(self, registry, mock_rc):
        received = []

        def failure_hook(rc, exc):
            received.append(exc)

        registry.register_global(HookEvent.AFTER_FAILURE, failure_hook)
        test_exc = ValueError("test error")
        registry.invoke(HookEvent.AFTER_FAILURE, "my_job", mock_rc, exception=test_exc)
        assert received == [test_exc]

    def test_hook_error_is_logged_and_continues(self, registry, mock_rc, caplog):
        called = []

        def bad_hook(rc):
            raise RuntimeError("hook failed")

        def good_hook(rc):
            called.append("good")

        registry.register_global(HookEvent.BEFORE_JOB, bad_hook)
        registry.register_global(HookEvent.BEFORE_JOB, good_hook)

        with caplog.at_level(logging.ERROR, logger="functualize._events.hooks"):
            registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc)

        assert called == ["good"]
        assert "bad_hook" in caplog.text
        assert "hook failed" in caplog.text

    def test_no_hooks_registered_does_nothing(self, registry, mock_rc):
        # Should not raise
        registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc)

    def test_invoke_with_no_exception_for_non_failure_events(self, registry, mock_rc):
        received_args = []

        def hook(rc):
            received_args.append(rc)

        registry.register_global(HookEvent.ON_TEARDOWN, hook)
        registry.invoke(HookEvent.ON_TEARDOWN, "my_job", mock_rc)
        assert received_args == [mock_rc]

    def test_multiple_failing_hooks_all_logged(self, registry, mock_rc, caplog):
        called = []

        def bad1(rc):
            raise RuntimeError("error1")

        def bad2(rc):
            raise RuntimeError("error2")

        def good(rc):
            called.append("good")

        registry.register_global(HookEvent.BEFORE_JOB, bad1)
        registry.register_global(HookEvent.BEFORE_JOB, bad2)
        registry.register_global(HookEvent.BEFORE_JOB, good)

        with caplog.at_level(logging.ERROR, logger="functualize._events.hooks"):
            registry.invoke(HookEvent.BEFORE_JOB, "my_job", mock_rc)

        assert called == ["good"]
        assert "error1" in caplog.text
        assert "error2" in caplog.text

    def test_global_and_job_hooks_both_receive_rc(self, registry, mock_rc):
        received = []

        def global_hook(rc):
            received.append(("global", rc))

        def job_hook(rc):
            received.append(("job", rc))

        registry.register_global(HookEvent.AFTER_SUCCESS, global_hook)
        registry.register_for_job("my_job", HookEvent.AFTER_SUCCESS, job_hook)
        registry.invoke(HookEvent.AFTER_SUCCESS, "my_job", mock_rc)

        assert received == [("global", mock_rc), ("job", mock_rc)]


class TestJobRegisteredEvent:
    """Tests for JOB_REGISTERED hook event and invoke_job_registered."""

    def test_job_registered_value(self):
        assert HookEvent.JOB_REGISTERED == "job_registered"

    def test_invoke_job_registered_calls_hooks_with_metadata(self, registry):
        received = []
        registry.register_global(
            HookEvent.JOB_REGISTERED, lambda meta: received.append(meta)
        )
        metadata = {
            "name": "my_job",
            "group": "default",
            "config_schema": None,
            "docstring": "A test job.",
        }
        registry.invoke_job_registered(metadata)
        assert received == [metadata]

    def test_invoke_job_registered_multiple_hooks_in_order(self, registry):
        called: list[str] = []
        registry.register_global(
            HookEvent.JOB_REGISTERED, lambda meta: called.append("h1")
        )
        registry.register_global(
            HookEvent.JOB_REGISTERED, lambda meta: called.append("h2")
        )
        registry.invoke_job_registered(
            {"name": "x", "group": "", "config_schema": None, "docstring": None}
        )
        assert called == ["h1", "h2"]

    def test_invoke_job_registered_no_hooks_does_nothing(self, registry):
        # Should not raise
        registry.invoke_job_registered(
            {"name": "x", "group": "", "config_schema": None, "docstring": None}
        )

    def test_invoke_job_registered_hook_failure_logged_and_continues(
        self, registry, caplog
    ):
        called: list[str] = []

        def bad_hook(meta):
            raise RuntimeError("boom")

        def good_hook(meta):
            called.append("good")

        registry.register_global(HookEvent.JOB_REGISTERED, bad_hook)
        registry.register_global(HookEvent.JOB_REGISTERED, good_hook)

        with caplog.at_level(logging.WARNING, logger="functualize._events.hooks"):
            registry.invoke_job_registered(
                {"name": "j", "group": "g", "config_schema": None, "docstring": None}
            )

        assert called == ["good"]
        assert "boom" in caplog.text
        assert HookEvent.JOB_REGISTERED in caplog.text

    def test_invoke_job_registered_metadata_contains_config_schema(self, registry):
        received = []
        registry.register_global(
            HookEvent.JOB_REGISTERED, lambda meta: received.append(meta)
        )

        class MyConfig:
            pass

        metadata = {
            "name": "configured_job",
            "group": "analytics",
            "config_schema": MyConfig,
            "docstring": "Does analytics.",
        }
        registry.invoke_job_registered(metadata)
        assert received[0]["config_schema"] is MyConfig
        assert received[0]["group"] == "analytics"
