"""Unit tests for HttpAdapter, HttpServerPlugin, and HttpServerCore (Task 17.3).

Tests the core logic (route building, request handling) without actually
starting a server. Uses a mock FunctualizeApp to isolate adapter behavior.

# Feature: unified-architecture-redesign, Task 17.3
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
from functualize_http import HttpAdapter, HttpServerCore, HttpServerPlugin

from functualize.app.adapters import AdapterPlugin

# =============================================================================
# Helpers / Fixtures
# =============================================================================


@dataclass(frozen=True)
class FakeJobDescriptor:
    """Minimal job descriptor for testing."""

    name: str
    group: str | None = None
    docstring: str | None = None
    module_path: str = "<test>"
    source_file: str = "<test>"
    source_mtime: float = 0.0
    content_hash: str = ""
    config_fields: list[Any] = field(default_factory=list)
    dependencies: dict[str, Any] = field(default_factory=dict)
    metadata: Any = None


class FakeRunStatus:
    """Fake run status with a .value attribute."""

    def __init__(self, value: str) -> None:
        self.value = value


@dataclass(frozen=True)
class FakeJobResult:
    """Minimal job result for testing."""

    status: FakeRunStatus
    duration_ms: float
    return_value: Any
    exception: BaseException | None = None
    job_name: str = "test-job"
    metadata: dict[str, Any] = field(default_factory=dict)


def make_mock_app(
    jobs: list[FakeJobDescriptor] | None = None,
    execute_result: FakeJobResult | None = None,
    execute_side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mock FunctualizeApp with configurable jobs and execution."""
    app = MagicMock()
    app.get_jobs.return_value = jobs or []

    def get_job(name: str) -> FakeJobDescriptor | None:
        for j in jobs or []:
            if j.name == name:
                return j
        return None

    app.get_job.side_effect = get_job

    if execute_side_effect:
        app.execute.side_effect = execute_side_effect
    elif execute_result:
        app.execute.return_value = execute_result
    else:
        app.execute.return_value = FakeJobResult(
            status=FakeRunStatus("success"),
            duration_ms=42.0,
            return_value=None,
        )

    app.register_plugin_command = MagicMock()
    app.get_plugin_commands.return_value = []

    return app


# =============================================================================
# Unit Tests: HttpAdapter Protocol Compliance
# =============================================================================


class TestHttpAdapterProtocol:
    """Verify HttpAdapter satisfies the AdapterPlugin Protocol."""

    def test_satisfies_adapter_protocol(self):
        """HttpAdapter passes isinstance check for AdapterPlugin."""
        adapter = HttpAdapter()
        assert isinstance(adapter, AdapterPlugin)

    def test_adapter_type_is_http(self):
        """HttpAdapter.adapter_type is 'http'."""
        adapter = HttpAdapter()
        assert adapter.adapter_type == "http"

    def test_has_required_fields(self):
        """HttpAdapter has name, version, description, adapter_type."""
        adapter = HttpAdapter()
        assert adapter.name == "functualize-http"
        assert adapter.version == "1.0.0"
        assert (
            adapter.description
            == "HTTP delivery adapter plugin for functualize using asyncio"
        )
        assert adapter.adapter_type == "http"

    def test_call_stores_app_reference(self):
        """__call__(app) stores the app and creates HttpServerCore."""
        adapter = HttpAdapter()
        mock_app = make_mock_app()
        adapter(mock_app)
        assert adapter._app is mock_app
        assert adapter._core is not None

    def test_run_raises_if_not_initialized(self):
        """run() raises RuntimeError if __call__ was not invoked first."""
        adapter = HttpAdapter()
        with pytest.raises(RuntimeError, match="called before __call__"):
            adapter.run()

    def test_shutdown_no_op_when_no_server(self):
        """shutdown() does not raise when no server is running."""
        adapter = HttpAdapter()
        adapter.shutdown()  # Should not raise


# =============================================================================
# Unit Tests: HttpServerCore Route Building
# =============================================================================


class TestHttpServerCoreRouteBuilding:
    """Test route building logic in HttpServerCore."""

    def test_build_routes_empty_when_no_jobs(self):
        """build_routes() returns empty dict when no jobs registered."""
        app = make_mock_app(jobs=[])
        core = HttpServerCore(app)
        routes = core.build_routes()
        assert routes == {}

    def test_build_routes_maps_jobs_to_post_endpoints(self):
        """Each job maps to POST /jobs/{name}/execute."""
        jobs = [
            FakeJobDescriptor(name="deploy"),
            FakeJobDescriptor(name="test"),
            FakeJobDescriptor(name="build"),
        ]
        app = make_mock_app(jobs=jobs)
        core = HttpServerCore(app)
        routes = core.build_routes()

        assert "/jobs/deploy/execute" in routes
        assert "/jobs/test/execute" in routes
        assert "/jobs/build/execute" in routes

        for _path, route_info in routes.items():
            assert route_info["method"] == "POST"

    def test_build_routes_includes_job_name_in_info(self):
        """Route info contains the job_name for dispatching."""
        jobs = [FakeJobDescriptor(name="migrate")]
        app = make_mock_app(jobs=jobs)
        core = HttpServerCore(app)
        routes = core.build_routes()

        assert routes["/jobs/migrate/execute"]["job_name"] == "migrate"


# =============================================================================
# Unit Tests: HttpServerCore Request Handling
# =============================================================================


class TestHttpServerCoreRequestHandling:
    """Test request handling logic in HttpServerCore."""

    def test_health_endpoint(self):
        """GET /health returns 200 with healthy status."""
        app = make_mock_app()
        core = HttpServerCore(app)

        status, body = asyncio.run(core.handle_request("GET", "/health", b""))
        assert status == 200
        assert body == {"status": "healthy"}

    def test_list_jobs_endpoint(self):
        """GET /jobs returns list of registered jobs."""
        jobs = [
            FakeJobDescriptor(name="deploy", group="ops", docstring="Deploy stuff"),
            FakeJobDescriptor(name="test", group=None, docstring=None),
        ]
        app = make_mock_app(jobs=jobs)
        core = HttpServerCore(app)

        status, body = asyncio.run(core.handle_request("GET", "/jobs", b""))
        assert status == 200
        assert len(body["jobs"]) == 2
        assert body["jobs"][0]["name"] == "deploy"
        assert body["jobs"][0]["group"] == "ops"
        assert body["jobs"][0]["docstring"] == "Deploy stuff"
        assert body["jobs"][1]["name"] == "test"
        assert body["jobs"][1]["group"] is None

    def test_execute_job_success(self):
        """POST /jobs/{name}/execute with valid job returns 200."""
        jobs = [FakeJobDescriptor(name="deploy")]
        result = FakeJobResult(
            status=FakeRunStatus("success"),
            duration_ms=123.4,
            return_value={"deployed": True},
            job_name="deploy",
        )
        app = make_mock_app(jobs=jobs, execute_result=result)
        core = HttpServerCore(app)

        body = json.dumps({"env": "prod"}).encode()
        status, response = asyncio.run(
            core.handle_request("POST", "/jobs/deploy/execute", body)
        )

        assert status == 200
        assert response["status"] == "success"
        assert response["duration_ms"] == 123.4
        assert response["return_value"] == {"deployed": True}
        app.execute.assert_called_once_with("deploy", env="prod")

    def test_execute_job_with_empty_body(self):
        """POST /jobs/{name}/execute with empty body passes no kwargs."""
        jobs = [FakeJobDescriptor(name="test")]
        app = make_mock_app(jobs=jobs)
        core = HttpServerCore(app)

        status, response = asyncio.run(
            core.handle_request("POST", "/jobs/test/execute", b"")
        )

        assert status == 200
        app.execute.assert_called_once_with("test")

    def test_execute_job_not_found(self):
        """POST /jobs/{name}/execute for unknown job returns 404."""
        app = make_mock_app(jobs=[])
        core = HttpServerCore(app)

        body = json.dumps({}).encode()
        status, response = asyncio.run(
            core.handle_request("POST", "/jobs/unknown/execute", body)
        )

        assert status == 404
        assert "not found" in response["error"].lower()

    def test_execute_job_invalid_json(self):
        """POST with invalid JSON body returns 400."""
        jobs = [FakeJobDescriptor(name="deploy")]
        app = make_mock_app(jobs=jobs)
        core = HttpServerCore(app)

        status, response = asyncio.run(
            core.handle_request("POST", "/jobs/deploy/execute", b"not json{")
        )

        assert status == 400
        assert "Invalid JSON" in response["error"]

    def test_execute_job_non_object_body(self):
        """POST with JSON array body (not object) returns 400."""
        jobs = [FakeJobDescriptor(name="deploy")]
        app = make_mock_app(jobs=jobs)
        core = HttpServerCore(app)

        body = json.dumps([1, 2, 3]).encode()
        status, response = asyncio.run(
            core.handle_request("POST", "/jobs/deploy/execute", body)
        )

        assert status == 400
        assert "must be a JSON object" in response["error"]

    def test_execute_job_raises_exception(self):
        """Execution error returns 500 with error message."""
        jobs = [FakeJobDescriptor(name="fail")]
        app = make_mock_app(
            jobs=jobs,
            execute_side_effect=RuntimeError("Boom!"),
        )
        core = HttpServerCore(app)

        body = json.dumps({}).encode()
        status, response = asyncio.run(
            core.handle_request("POST", "/jobs/fail/execute", body)
        )

        assert status == 500
        assert "Boom!" in response["error"]

    def test_unknown_path_returns_404(self):
        """Request to unknown path returns 404."""
        app = make_mock_app()
        core = HttpServerCore(app)

        status, response = asyncio.run(core.handle_request("GET", "/unknown", b""))

        assert status == 404
        assert response["path"] == "/unknown"

    def test_post_to_health_returns_404(self):
        """POST to /health (wrong method) returns 404."""
        app = make_mock_app()
        core = HttpServerCore(app)

        status, response = asyncio.run(core.handle_request("POST", "/health", b""))

        assert status == 404


# =============================================================================
# Unit Tests: HttpServerCore Serialization
# =============================================================================


class TestHttpServerCoreSerialization:
    """Test return value serialization in HttpServerCore."""

    def test_serialize_none(self):
        """None values serialize to None."""
        assert HttpServerCore._serialize_return_value(None) is None

    def test_serialize_primitives(self):
        """Primitive values pass through unchanged."""
        assert HttpServerCore._serialize_return_value("hello") == "hello"
        assert HttpServerCore._serialize_return_value(42) == 42
        assert HttpServerCore._serialize_return_value(3.14) == 3.14
        assert HttpServerCore._serialize_return_value(True) is True

    def test_serialize_list(self):
        """Lists are recursively serialized."""
        result = HttpServerCore._serialize_return_value([1, "two", None])
        assert result == [1, "two", None]

    def test_serialize_dict(self):
        """Dicts are recursively serialized with string keys."""
        result = HttpServerCore._serialize_return_value({"a": 1, "b": "two"})
        assert result == {"a": 1, "b": "two"}

    def test_serialize_nested_structure(self):
        """Nested structures are recursively serialized."""
        value = {"items": [1, 2], "meta": {"count": 2}}
        result = HttpServerCore._serialize_return_value(value)
        assert result == {"items": [1, 2], "meta": {"count": 2}}

    def test_serialize_non_serializable_falls_back_to_str(self):
        """Non-serializable values fall back to str()."""

        class Custom:
            def __str__(self):
                return "custom-repr"

        result = HttpServerCore._serialize_return_value(Custom())
        assert result == "custom-repr"


# =============================================================================
# Unit Tests: HttpServerPlugin
# =============================================================================


class TestHttpServerPlugin:
    """Test HttpServerPlugin registers serve command."""

    def test_plugin_registers_serve_command(self):
        """Plugin registers 'serve' command via register_plugin_command."""
        app = make_mock_app()
        plugin = HttpServerPlugin()
        plugin(app)

        app.register_plugin_command.assert_called_once()
        call_args = app.register_plugin_command.call_args
        assert call_args.kwargs.get("name") or call_args[0][0] == "serve"

    def test_plugin_stores_app_reference(self):
        """Plugin stores the app reference."""
        app = make_mock_app()
        plugin = HttpServerPlugin()
        plugin(app)
        assert plugin._app is app

    def test_plugin_creates_core(self):
        """Plugin creates an HttpServerCore instance."""
        app = make_mock_app()
        plugin = HttpServerPlugin()
        plugin(app)
        assert plugin._core is not None
        assert isinstance(plugin._core, HttpServerCore)

    def test_plugin_is_not_adapter(self):
        """HttpServerPlugin is NOT an AdapterPlugin (no run/shutdown/adapter_type)."""
        plugin = HttpServerPlugin()
        assert not isinstance(plugin, AdapterPlugin)

    def test_plugin_has_name_and_version(self):
        """Plugin has identifying metadata."""
        plugin = HttpServerPlugin()
        assert plugin.name == "functualize-http-server"
        assert plugin.version == "1.0.0"


# =============================================================================
# Unit Tests: Async-to-Sync Bridging
# =============================================================================


class TestAsyncToSyncBridging:
    """Test that kernel execution is properly bridged to async context."""

    def test_execute_calls_app_execute_via_thread(self):
        """Job execution goes through app.execute() (sync call in thread)."""
        jobs = [FakeJobDescriptor(name="sync-job")]
        result = FakeJobResult(
            status=FakeRunStatus("success"),
            duration_ms=10.0,
            return_value="done",
            job_name="sync-job",
        )
        app = make_mock_app(jobs=jobs, execute_result=result)
        core = HttpServerCore(app)

        body = json.dumps({"x": 1}).encode()
        status, response = asyncio.run(
            core.handle_request("POST", "/jobs/sync-job/execute", body)
        )

        assert status == 200
        assert response["return_value"] == "done"
        # Verify app.execute was called (proving async-to-sync bridge worked)
        app.execute.assert_called_once_with("sync-job", x=1)


# =============================================================================
# Unit Tests: HttpServerCore shared usage
# =============================================================================


class TestHttpServerCoreShared:
    """Verify that both HttpAdapter and HttpServerPlugin use HttpServerCore."""

    def test_adapter_and_plugin_use_same_core_class(self):
        """Both HttpAdapter and HttpServerPlugin create HttpServerCore instances."""
        app = make_mock_app()

        adapter = HttpAdapter()
        adapter(app)

        plugin = HttpServerPlugin()
        plugin(app)

        assert isinstance(adapter._core, HttpServerCore)
        assert isinstance(plugin._core, HttpServerCore)

    def test_core_accepts_functualize_app(self):
        """HttpServerCore accepts a FunctualizeApp-like object."""
        app = make_mock_app()
        core = HttpServerCore(app)
        assert core._app is app
