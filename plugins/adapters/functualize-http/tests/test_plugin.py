"""Unit tests for functualize-http plugin.

Tests the HTTP server core logic: request routing, job execution,
health endpoints, and error handling. Uses direct method calls on
HttpServerCore.handle_request() to avoid needing a running server.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from functualize_http import HttpAdapter, HttpServerCore, HttpServerPlugin

from .conftest import FakeApp, FakeDescriptor


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, fake_app):
        core = HttpServerCore(fake_app)
        status, body = asyncio.run(core.handle_request("GET", "/health", b""))
        assert status == 200
        assert body == {"status": "healthy"}


class TestJobListing:
    """Tests for GET /jobs."""

    def test_lists_all_jobs(self, fake_app):
        core = HttpServerCore(fake_app)
        status, body = asyncio.run(core.handle_request("GET", "/jobs", b""))
        assert status == 200
        assert len(body["jobs"]) == 2
        names = [j["name"] for j in body["jobs"]]
        assert "greet" in names
        assert "deploy" in names

    def test_empty_app_returns_empty_list(self, empty_app):
        core = HttpServerCore(empty_app)
        status, body = asyncio.run(core.handle_request("GET", "/jobs", b""))
        assert status == 200
        assert body == {"jobs": []}


class TestJobExecution:
    """Tests for POST /jobs/{name}/execute."""

    def test_execute_job_success(self, fake_app):
        core = HttpServerCore(fake_app)
        payload = json.dumps({"name": "World"}).encode()
        status, body = asyncio.run(
            core.handle_request("POST", "/jobs/greet/execute", payload)
        )
        assert status == 200
        assert body["return_value"] == "executed greet"

    def test_execute_nonexistent_job_returns_404(self, fake_app):
        core = HttpServerCore(fake_app)
        status, body = asyncio.run(
            core.handle_request("POST", "/jobs/nope/execute", b"")
        )
        assert status == 404
        assert "not found" in body["error"].lower()

    def test_execute_with_invalid_json_returns_400(self, fake_app):
        core = HttpServerCore(fake_app)
        status, body = asyncio.run(
            core.handle_request("POST", "/jobs/greet/execute", b"not json")
        )
        assert status == 400
        assert "Invalid JSON" in body["error"]

    def test_execute_with_non_object_body_returns_400(self, fake_app):
        core = HttpServerCore(fake_app)
        payload = json.dumps([1, 2, 3]).encode()
        status, body = asyncio.run(
            core.handle_request("POST", "/jobs/greet/execute", payload)
        )
        assert status == 400
        assert "must be a JSON object" in body["error"]

    def test_execute_with_empty_body_succeeds(self, fake_app):
        core = HttpServerCore(fake_app)
        status, body = asyncio.run(
            core.handle_request("POST", "/jobs/greet/execute", b"")
        )
        assert status == 200

    def test_execution_error_returns_500(self):
        app = FakeApp(
            descriptors=[FakeDescriptor(name="broken", docstring="Broken")],
            execute_error=RuntimeError("kaboom"),
        )
        core = HttpServerCore(app)
        status, body = asyncio.run(
            core.handle_request("POST", "/jobs/broken/execute", b"")
        )
        assert status == 500
        assert "kaboom" in body["error"]


class TestRouting:
    """Tests for route matching."""

    def test_unknown_path_returns_404(self, fake_app):
        core = HttpServerCore(fake_app)
        status, body = asyncio.run(core.handle_request("GET", "/unknown/path", b""))
        assert status == 404

    def test_build_routes_maps_jobs(self, fake_app):
        core = HttpServerCore(fake_app)
        routes = core.build_routes()
        assert "/jobs/greet/execute" in routes
        assert "/jobs/deploy/execute" in routes


class TestHttpAdapter:
    """Tests for HttpAdapter setup and metadata."""

    def test_adapter_type(self):
        adapter = HttpAdapter()
        assert adapter.adapter_type == "http"

    def test_run_before_setup_raises(self):
        adapter = HttpAdapter()
        with pytest.raises(RuntimeError, match="called before __call__"):
            adapter.run()

    def test_setup_creates_core(self, fake_app):
        adapter = HttpAdapter()
        adapter(fake_app)
        assert adapter._core is not None


class TestHttpServerPlugin:
    """Tests for HttpServerPlugin command registration."""

    def test_registers_serve_command(self, fake_app):
        plugin = HttpServerPlugin()
        plugin(fake_app)
        assert "serve" in fake_app._commands
