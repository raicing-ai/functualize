"""Unit tests for functualize-lambda plugin.

Tests the Lambda adapter's fat-lambda routing, thin-lambda handler creation,
and error handling.
"""

from __future__ import annotations

import pytest
from functualize_lambda import LambdaAdapter


class TestFatLambda:
    """Tests for fat-Lambda (internal routing via event['job'])."""

    def test_routes_to_correct_job(self, fake_app):
        adapter = LambdaAdapter()
        adapter(fake_app)
        result = adapter.run({"job": "deploy", "kwargs": {"env": "prod"}}, None)
        assert result["statusCode"] == 200
        assert result["body"] == "executed deploy"

    def test_missing_job_field_returns_400(self, fake_app):
        adapter = LambdaAdapter()
        adapter(fake_app)
        result = adapter.run({}, None)
        assert result["statusCode"] == 400
        assert "Missing required field" in result["body"]

    def test_execution_error_returns_500(self, failing_app):
        adapter = LambdaAdapter()
        adapter(failing_app)
        result = adapter.run({"job": "deploy"}, None)
        assert result["statusCode"] == 500
        assert "deploy failed" in result["body"]

    def test_run_before_setup_raises(self):
        adapter = LambdaAdapter()
        with pytest.raises(RuntimeError, match="called before __call__"):
            adapter.run({"job": "test"}, None)

    def test_kwargs_default_to_empty(self, fake_app):
        adapter = LambdaAdapter()
        adapter(fake_app)
        result = adapter.run({"job": "deploy"}, None)
        assert result["statusCode"] == 200


class TestThinLambda:
    """Tests for thin-Lambda (per-job handlers via make_handler)."""

    def test_make_handler_creates_callable(self, fake_app):
        adapter = LambdaAdapter()
        adapter(fake_app)
        handler = adapter.make_handler("deploy")
        assert callable(handler)

    def test_handler_executes_bound_job(self, fake_app):
        adapter = LambdaAdapter()
        adapter(fake_app)
        handler = adapter.make_handler("deploy")
        result = handler({"kwargs": {"env": "staging"}}, None)
        assert result["statusCode"] == 200
        assert result["body"] == "executed deploy"

    def test_handler_error_returns_500(self, failing_app):
        adapter = LambdaAdapter()
        adapter(failing_app)
        handler = adapter.make_handler("deploy")
        result = handler({}, None)
        assert result["statusCode"] == 500
        assert "deploy failed" in result["body"]

    def test_make_handler_before_setup_raises(self):
        adapter = LambdaAdapter()
        with pytest.raises(RuntimeError, match="called before __call__"):
            adapter.make_handler("deploy")

    def test_handler_has_descriptive_name(self, fake_app):
        adapter = LambdaAdapter()
        adapter(fake_app)
        handler = adapter.make_handler("deploy")
        assert "deploy" in handler.__name__


class TestAdapterMetadata:
    """Tests for adapter metadata attributes."""

    def test_has_required_attributes(self):
        adapter = LambdaAdapter()
        assert adapter.name == "functualize-lambda"
        assert adapter.adapter_type == "lambda"
        assert adapter.version

    def test_shutdown_is_noop(self, fake_app):
        adapter = LambdaAdapter()
        adapter(fake_app)
        adapter.shutdown()  # Should not raise
