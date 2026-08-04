"""Unit tests for LambdaAdapter (Task 17.1).

Tests the LambdaAdapter implementation covering:
- AdapterPlugin Protocol satisfaction
- Fat Lambda pattern (internal routing via event["job"])
- Thin Lambda pattern (per-job handler via make_handler())
- Error handling (missing job, execution failure, missing event fields)
- No-op shutdown

# Feature: unified-architecture-redesign, Task 17.1
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from functualize_lambda import LambdaAdapter

from functualize.app.adapters import AdapterPlugin, validate_adapter

# =============================================================================
# Helpers
# =============================================================================


@dataclass(frozen=True)
class FakeJobResult:
    """Minimal stand-in for JobResult."""

    status: str = "success"
    duration_ms: float = 1.0
    return_value: Any = None
    exception: BaseException | None = None
    job_name: str = "test-job"
    metadata: dict[str, Any] | None = None


class FakeApp:
    """Minimal FunctualizeApp stand-in for testing adapter behavior."""

    def __init__(self, jobs: dict[str, Any] | None = None):
        self._jobs = jobs or {}

    def execute(self, job_name: str, **kwargs: Any) -> FakeJobResult:
        if job_name not in self._jobs:
            raise KeyError(f"Job '{job_name}' not found")
        handler = self._jobs[job_name]
        result = handler(**kwargs)
        return FakeJobResult(return_value=result, job_name=job_name)


class FailingApp:
    """App that raises on execute for error path testing."""

    def execute(self, job_name: str, **kwargs: Any) -> Any:
        raise RuntimeError(f"Execution failed for '{job_name}'")


# =============================================================================
# Unit Tests: Protocol Compliance
# =============================================================================


class TestLambdaAdapterProtocol:
    """Tests that LambdaAdapter satisfies the AdapterPlugin Protocol."""

    def test_satisfies_adapter_plugin_protocol(self):
        """LambdaAdapter instances pass isinstance(_, AdapterPlugin)."""
        adapter = LambdaAdapter()
        assert isinstance(adapter, AdapterPlugin)

    def test_passes_validate_adapter(self):
        """LambdaAdapter passes the validate_adapter() check."""
        adapter = LambdaAdapter()
        validate_adapter(adapter)

    def test_adapter_type_is_lambda(self):
        """adapter_type field is 'lambda'."""
        adapter = LambdaAdapter()
        assert adapter.adapter_type == "lambda"

    def test_has_required_fields(self):
        """All required protocol fields are present and non-empty."""
        adapter = LambdaAdapter()
        assert adapter.name
        assert adapter.version
        assert adapter.description
        assert adapter.adapter_type == "lambda"

    def test_no_inheritance_from_protocol(self):
        """LambdaAdapter satisfies protocol via structural typing, not inheritance."""
        assert AdapterPlugin not in LambdaAdapter.__mro__


# =============================================================================
# Unit Tests: __call__ (Setup Phase)
# =============================================================================


class TestLambdaAdapterSetup:
    """Tests for the __call__ setup phase."""

    def test_stores_app_reference(self):
        """__call__(app) stores the app for later use."""
        adapter = LambdaAdapter()
        app = FakeApp()
        adapter(app)
        assert adapter._app is app

    def test_run_before_call_raises(self):
        """run() raises RuntimeError if called before __call__(app)."""
        adapter = LambdaAdapter()
        with pytest.raises(RuntimeError, match="called before __call__"):
            adapter.run({"job": "test"}, None)

    def test_make_handler_before_call_raises(self):
        """make_handler() raises RuntimeError if called before __call__(app)."""
        adapter = LambdaAdapter()
        with pytest.raises(RuntimeError, match="called before __call__"):
            adapter.make_handler("test")


# =============================================================================
# Unit Tests: run() — Fat Lambda Pattern
# =============================================================================


class TestLambdaAdapterFatLambda:
    """Tests for the fat Lambda pattern (internal routing via event['job'])."""

    def test_routes_to_correct_job(self):
        """run() executes the job named in event['job']."""
        app = FakeApp(jobs={"deploy": lambda: "deployed"})
        adapter = LambdaAdapter()
        adapter(app)

        result = adapter.run({"job": "deploy"}, None)

        assert result["statusCode"] == 200
        assert result["body"] == "deployed"

    def test_passes_kwargs_from_event(self):
        """run() passes event['kwargs'] to the job function."""
        app = FakeApp(jobs={"greet": lambda name="world": f"hello {name}"})
        adapter = LambdaAdapter()
        adapter(app)

        result = adapter.run({"job": "greet", "kwargs": {"name": "lambda"}}, None)

        assert result["statusCode"] == 200
        assert result["body"] == "hello lambda"

    def test_empty_kwargs_default(self):
        """run() defaults to empty kwargs when event has no 'kwargs' key."""
        app = FakeApp(jobs={"noop": lambda: "done"})
        adapter = LambdaAdapter()
        adapter(app)

        result = adapter.run({"job": "noop"}, None)

        assert result["statusCode"] == 200
        assert result["body"] == "done"

    def test_missing_job_field_returns_400(self):
        """run() returns 400 when event has no 'job' field."""
        app = FakeApp()
        adapter = LambdaAdapter()
        adapter(app)

        result = adapter.run({"kwargs": {}}, None)

        assert result["statusCode"] == 400
        assert "job" in result["body"].lower()

    def test_empty_event_returns_400(self):
        """run() returns 400 for an empty event dict."""
        app = FakeApp()
        adapter = LambdaAdapter()
        adapter(app)

        result = adapter.run({}, None)

        assert result["statusCode"] == 400

    def test_execution_failure_returns_500(self):
        """run() returns 500 when job execution raises."""
        app = FailingApp()
        adapter = LambdaAdapter()
        adapter(app)

        result = adapter.run({"job": "anything"}, None)

        assert result["statusCode"] == 500
        assert "anything" in result["body"]

    def test_job_not_found_returns_500(self):
        """run() returns 500 when the job name is not registered."""
        app = FakeApp(jobs={})  # no jobs registered
        adapter = LambdaAdapter()
        adapter(app)

        result = adapter.run({"job": "nonexistent"}, None)

        assert result["statusCode"] == 500
        assert "nonexistent" in result["body"]

    def test_context_is_accepted(self):
        """run() accepts a context argument (even if unused)."""
        app = FakeApp(jobs={"ping": lambda: "pong"})
        adapter = LambdaAdapter()
        adapter(app)

        mock_context = MagicMock()
        result = adapter.run({"job": "ping"}, mock_context)

        assert result["statusCode"] == 200
        assert result["body"] == "pong"

    def test_result_is_always_dict_with_statuscode_and_body(self):
        """run() always returns a dict with exactly 'statusCode' and 'body'."""
        app = FakeApp(jobs={"job1": lambda: 42})
        adapter = LambdaAdapter()
        adapter(app)

        result = adapter.run({"job": "job1"}, None)

        assert isinstance(result, dict)
        assert "statusCode" in result
        assert "body" in result


# =============================================================================
# Unit Tests: make_handler() — Thin Lambda Pattern
# =============================================================================


class TestLambdaAdapterThinLambda:
    """Tests for the thin Lambda pattern (per-job handler via make_handler())."""

    def test_returns_callable(self):
        """make_handler() returns a callable."""
        app = FakeApp(jobs={"deploy": lambda: "deployed"})
        adapter = LambdaAdapter()
        adapter(app)

        handler = adapter.make_handler("deploy")
        assert callable(handler)

    def test_handler_executes_bound_job(self):
        """Thin handler executes the specified job."""
        app = FakeApp(jobs={"deploy": lambda: "deployed"})
        adapter = LambdaAdapter()
        adapter(app)

        handler = adapter.make_handler("deploy")
        result = handler({}, None)

        assert result["statusCode"] == 200
        assert result["body"] == "deployed"

    def test_handler_passes_event_kwargs(self):
        """Thin handler passes event['kwargs'] to the job."""
        app = FakeApp(jobs={"greet": lambda name="world": f"hi {name}"})
        adapter = LambdaAdapter()
        adapter(app)

        handler = adapter.make_handler("greet")
        result = handler({"kwargs": {"name": "thin"}}, None)

        assert result["statusCode"] == 200
        assert result["body"] == "hi thin"

    def test_handler_default_empty_kwargs(self):
        """Thin handler defaults to empty kwargs when event lacks 'kwargs'."""
        app = FakeApp(jobs={"noop": lambda: "done"})
        adapter = LambdaAdapter()
        adapter(app)

        handler = adapter.make_handler("noop")
        result = handler({}, None)

        assert result["statusCode"] == 200
        assert result["body"] == "done"

    def test_handler_execution_failure_returns_500(self):
        """Thin handler returns 500 when the job raises."""
        app = FailingApp()
        adapter = LambdaAdapter()
        adapter(app)

        handler = adapter.make_handler("broken")
        result = handler({}, None)

        assert result["statusCode"] == 500
        assert "broken" in result["body"]

    def test_multiple_handlers_for_different_jobs(self):
        """make_handler() can create handlers for different jobs."""
        app = FakeApp(
            jobs={
                "deploy": lambda: "deployed",
                "rollback": lambda: "rolled_back",
            }
        )
        adapter = LambdaAdapter()
        adapter(app)

        deploy_handler = adapter.make_handler("deploy")
        rollback_handler = adapter.make_handler("rollback")

        assert deploy_handler({}, None)["body"] == "deployed"
        assert rollback_handler({}, None)["body"] == "rolled_back"

    def test_handler_ignores_event_job_field(self):
        """Thin handler ignores event['job'] — always uses bound job name."""
        app = FakeApp(
            jobs={
                "deploy": lambda: "deployed",
                "other": lambda: "other_result",
            }
        )
        adapter = LambdaAdapter()
        adapter(app)

        handler = adapter.make_handler("deploy")
        # Even if event has a different job name, thin handler uses bound name
        result = handler({"job": "other", "kwargs": {}}, None)

        assert result["body"] == "deployed"

    def test_handler_has_descriptive_name(self):
        """Thin handler has a useful __name__ for debugging."""
        app = FakeApp(jobs={"deploy": lambda: None})
        adapter = LambdaAdapter()
        adapter(app)

        handler = adapter.make_handler("deploy")
        assert "deploy" in handler.__name__


# =============================================================================
# Unit Tests: shutdown()
# =============================================================================


class TestLambdaAdapterShutdown:
    """Tests for the no-op shutdown method."""

    def test_shutdown_is_noop(self):
        """shutdown() does nothing and does not raise."""
        adapter = LambdaAdapter()
        # Should not raise even without setup
        adapter.shutdown()

    def test_shutdown_after_setup(self):
        """shutdown() is safe to call after __call__(app)."""
        app = FakeApp()
        adapter = LambdaAdapter()
        adapter(app)
        adapter.shutdown()
        # Should still be functional after shutdown (Lambda is stateless)

    def test_shutdown_returns_none(self):
        """shutdown() returns None."""
        adapter = LambdaAdapter()
        result = adapter.shutdown()
        assert result is None
