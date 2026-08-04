"""Unit tests for MCPToolRegistry — core MCP tools.

Tests discover_jobs, get_job_schema, run_job, run_job_async, and
get_execution_status tools with visibility filtering and error handling.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from functualize_mcp._config import MCPConfig
from functualize_mcp._tools import MCPToolRegistry

# ---------------------------------------------------------------------------
# Test helpers — minimal app and descriptor fakes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeField:
    name: str
    type_annotation: str
    default: Any | None = None
    description: str = ""
    required: bool = True
    choices: list[str] | None = None


@dataclass
class FakeDescriptor:
    name: str
    group: str | None = None
    docstring: str | None = None
    config_fields: list[FakeField] = field(default_factory=list)
    parameters: list[FakeField] = field(default_factory=list)
    declaration: Any = field(default_factory=dict)


class FakeJobResult:
    """Fake job result returned by app.execute()."""

    def __init__(
        self,
        status: str = "success",
        return_value: Any = None,
        duration_ms: float = 42.0,
    ):
        self.status = status
        self.return_value = return_value
        self.duration_ms = duration_ms


class FakeApp:
    """Minimal fake FunctualizeApp for testing MCPToolRegistry."""

    def __init__(
        self,
        descriptors: list[FakeDescriptor] | None = None,
        execute_results: dict[str, FakeJobResult] | None = None,
        execute_error: Exception | None = None,
        execute_delay: float = 0.0,
    ):
        self._descriptors = descriptors or []
        self._execute_results = execute_results or {}
        self._execute_error = execute_error
        self._execute_delay = execute_delay

    def get_jobs(self) -> list[FakeDescriptor]:
        return self._descriptors

    def get_job(self, name: str) -> FakeDescriptor | None:
        for d in self._descriptors:
            if d.name == name:
                return d
        return None

    def execute(self, job_name: str, **kwargs: Any) -> FakeJobResult:
        if self._execute_delay > 0:
            time.sleep(self._execute_delay)
        if self._execute_error:
            raise self._execute_error
        if job_name in self._execute_results:
            return self._execute_results[job_name]
        return FakeJobResult(status="success", return_value=f"executed {job_name}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def basic_descriptors() -> list[FakeDescriptor]:
    """Create a set of basic descriptors for testing."""
    return [
        FakeDescriptor(
            name="greet",
            docstring="Greet someone by name.\n\nThis is the extended doc.",
            config_fields=[
                FakeField(
                    name="name",
                    type_annotation="str",
                    required=True,
                    description="Person name",
                ),
            ],
            declaration=SimpleNamespace(
                tags=["util", "demo"],
                visibility=None,
                extra_description=None,
                examples=["greet --name Alice"],
                category="utility",
            ),
        ),
        FakeDescriptor(
            name="deploy",
            docstring="Deploy to production.",
            config_fields=[
                FakeField(
                    name="env",
                    type_annotation="str",
                    required=True,
                    description="Environment",
                ),
                FakeField(
                    name="dry_run",
                    type_annotation="bool",
                    default=False,
                    required=False,
                    description="Dry run",
                ),
            ],
            declaration=SimpleNamespace(
                tags=["ops"],
                visibility=None,
                extra_description=None,
                examples=None,
                category="operations",
            ),
        ),
        FakeDescriptor(
            name="internal_job",
            docstring="Internal maintenance job.",
            declaration=SimpleNamespace(
                tags=["internal"],
                visibility="internal",
                extra_description=None,
                examples=None,
                category=None,
            ),
        ),
    ]


@pytest.fixture
def basic_app(basic_descriptors: list[FakeDescriptor]) -> FakeApp:
    """Create a FakeApp with basic descriptors."""
    return FakeApp(descriptors=basic_descriptors)


# ---------------------------------------------------------------------------
# Tests for discover_jobs
# ---------------------------------------------------------------------------


class TestDiscoverJobs:
    """Tests for the discover_jobs tool."""

    def test_returns_visible_jobs(self, basic_app: FakeApp):
        """discover_jobs returns only visible (non-internal) jobs."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._discover_jobs())

        assert "jobs" in result
        job_names = [j["name"] for j in result["jobs"]]
        assert "greet" in job_names
        assert "deploy" in job_names
        assert "internal_job" not in job_names

    def test_includes_description_and_tags(self, basic_app: FakeApp):
        """discover_jobs includes description and tags for each job."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._discover_jobs())

        greet = next(j for j in result["jobs"] if j["name"] == "greet")
        assert greet["description"] == "Greet someone by name."
        assert greet["tags"] == ["util", "demo"]

    def test_respects_include_tags_filter(self, basic_app: FakeApp):
        """discover_jobs filters by include_tags when set."""
        config = MCPConfig(include_tags=["ops"])
        registry = MCPToolRegistry(basic_app, config=config)
        result = asyncio.run(registry._discover_jobs())

        job_names = [j["name"] for j in result["jobs"]]
        assert "deploy" in job_names
        assert "greet" not in job_names

    def test_respects_exclude_jobs_filter(self, basic_app: FakeApp):
        """discover_jobs excludes jobs listed in exclude_jobs."""
        config = MCPConfig(exclude_jobs=["greet"])
        registry = MCPToolRegistry(basic_app, config=config)
        result = asyncio.run(registry._discover_jobs())

        job_names = [j["name"] for j in result["jobs"]]
        assert "greet" not in job_names
        assert "deploy" in job_names

    def test_empty_app_returns_empty_list(self):
        """discover_jobs returns empty list when no jobs exist."""
        app = FakeApp(descriptors=[])
        registry = MCPToolRegistry(app, config=MCPConfig())
        result = asyncio.run(registry._discover_jobs())

        assert result == {"jobs": []}


# ---------------------------------------------------------------------------
# Tests for get_job_schema
# ---------------------------------------------------------------------------


class TestGetJobSchema:
    """Tests for the get_job_schema tool."""

    def test_returns_schema_for_visible_job(self, basic_app: FakeApp):
        """get_job_schema returns the full schema for a visible job."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._get_job_schema("greet"))

        assert result["name"] == "greet"
        assert "input_schema" in result
        assert "properties" in result["input_schema"]
        assert "name" in result["input_schema"]["properties"]
        assert result["examples"] == ["greet --name Alice"]

    def test_returns_error_for_nonexistent_job(self, basic_app: FakeApp):
        """get_job_schema returns error for a job that doesn't exist."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._get_job_schema("nonexistent"))

        assert "error" in result
        assert result["error"]["code"] == "job_not_found"

    def test_returns_error_for_internal_job(self, basic_app: FakeApp):
        """get_job_schema returns error for an internal job."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._get_job_schema("internal_job"))

        assert "error" in result
        assert result["error"]["code"] == "job_not_accessible"

    def test_returns_error_for_excluded_job(self, basic_app: FakeApp):
        """get_job_schema returns error for a job excluded by config."""
        config = MCPConfig(exclude_jobs=["greet"])
        registry = MCPToolRegistry(basic_app, config=config)
        result = asyncio.run(registry._get_job_schema("greet"))

        assert "error" in result
        assert result["error"]["code"] == "job_not_accessible"

    def test_returns_description(self, basic_app: FakeApp):
        """get_job_schema includes the job description."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._get_job_schema("greet"))

        assert "description" in result
        assert "Greet someone by name" in result["description"]


# ---------------------------------------------------------------------------
# Tests for run_job
# ---------------------------------------------------------------------------


class TestRunJob:
    """Tests for the run_job tool."""

    def test_executes_visible_job(self, basic_app: FakeApp):
        """run_job executes a visible job and returns result."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._run_job("greet", {"name": "Alice"}))

        assert result["status"] == "success"
        assert result["return_value"] == "executed greet"
        assert "duration_ms" in result

    def test_returns_error_for_nonexistent_job(self, basic_app: FakeApp):
        """run_job returns error for a job that doesn't exist."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._run_job("nonexistent"))

        assert "error" in result
        assert result["error"]["code"] == "job_not_found"

    def test_returns_error_for_internal_job(self, basic_app: FakeApp):
        """run_job returns error for an internal job."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._run_job("internal_job"))

        assert "error" in result
        assert result["error"]["code"] == "job_not_accessible"

    def test_returns_error_for_excluded_job(self, basic_app: FakeApp):
        """run_job returns error for an excluded job."""
        config = MCPConfig(exclude_jobs=["deploy"])
        registry = MCPToolRegistry(basic_app, config=config)
        result = asyncio.run(registry._run_job("deploy"))

        assert "error" in result
        assert result["error"]["code"] == "job_not_accessible"

    def test_returns_error_on_execution_failure(self):
        """run_job returns error response when execution raises."""
        app = FakeApp(
            descriptors=[FakeDescriptor(name="failing_job", docstring="Fails.")],
            execute_error=RuntimeError("Something went wrong"),
        )
        registry = MCPToolRegistry(app, config=MCPConfig())
        result = asyncio.run(registry._run_job("failing_job"))

        assert "error" in result
        assert result["error"]["code"] == "execution_error"
        assert "Something went wrong" in result["error"]["message"]

    def test_passes_config_as_kwargs(self, basic_descriptors: list[FakeDescriptor]):
        """run_job passes config dict as kwargs to app.execute()."""
        called_with: dict[str, Any] = {}

        class TrackingApp(FakeApp):
            def execute(self, job_name: str, **kwargs: Any) -> FakeJobResult:
                called_with.update(kwargs)
                return FakeJobResult()

        app = TrackingApp(descriptors=basic_descriptors)
        registry = MCPToolRegistry(app, config=MCPConfig())
        asyncio.run(registry._run_job("greet", {"name": "Bob"}))

        assert called_with == {"name": "Bob"}

    def test_works_with_no_config(self, basic_app: FakeApp):
        """run_job works when config is None (no kwargs)."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._run_job("greet"))

        assert result["status"] == "success"


# ---------------------------------------------------------------------------
# Tests for run_job_async
# ---------------------------------------------------------------------------


class TestRunJobAsync:
    """Tests for the run_job_async tool."""

    def test_returns_execution_id(self, basic_app: FakeApp):
        """run_job_async returns an execution_id immediately."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._run_job_async("greet", {"name": "Alice"}))

        assert "execution_id" in result
        assert len(result["execution_id"]) == 16

    def test_returns_error_for_nonexistent_job(self, basic_app: FakeApp):
        """run_job_async returns error for a job that doesn't exist."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._run_job_async("nonexistent"))

        assert "error" in result
        assert result["error"]["code"] == "job_not_found"

    def test_returns_error_for_internal_job(self, basic_app: FakeApp):
        """run_job_async returns error for an internal job."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._run_job_async("internal_job"))

        assert "error" in result
        assert result["error"]["code"] == "job_not_accessible"

    def test_execution_completes_successfully(self):
        """Async execution transitions to success status."""
        app = FakeApp(
            descriptors=[FakeDescriptor(name="fast_job", docstring="Fast.")],
            execute_delay=0.05,
        )
        registry = MCPToolRegistry(app, config=MCPConfig())
        result = asyncio.run(registry._run_job_async("fast_job"))

        execution_id = result["execution_id"]
        # Wait for completion
        time.sleep(0.2)

        status = asyncio.run(registry._get_execution_status(execution_id))
        assert status["status"] == "success"
        assert status["duration_ms"] is not None

    def test_execution_captures_failure(self):
        """Async execution transitions to failure status on error."""
        app = FakeApp(
            descriptors=[FakeDescriptor(name="broken_job", docstring="Broken.")],
            execute_error=ValueError("kaboom"),
            execute_delay=0.05,
        )
        registry = MCPToolRegistry(app, config=MCPConfig())
        result = asyncio.run(registry._run_job_async("broken_job"))

        execution_id = result["execution_id"]
        # Wait for completion
        time.sleep(0.2)

        status = asyncio.run(registry._get_execution_status(execution_id))
        assert status["status"] == "failure"
        assert "kaboom" in status["error"]


# ---------------------------------------------------------------------------
# Tests for get_execution_status
# ---------------------------------------------------------------------------


class TestGetExecutionStatus:
    """Tests for the get_execution_status tool."""

    def test_returns_running_status(self):
        """get_execution_status returns 'running' for in-progress execution."""
        app = FakeApp(
            descriptors=[FakeDescriptor(name="slow_job", docstring="Slow.")],
            execute_delay=1.0,
        )
        registry = MCPToolRegistry(app, config=MCPConfig())
        result = asyncio.run(registry._run_job_async("slow_job"))

        execution_id = result["execution_id"]
        status = asyncio.run(registry._get_execution_status(execution_id))

        assert status["execution_id"] == execution_id
        assert status["job_name"] == "slow_job"
        assert status["status"] == "running"

    def test_returns_error_for_nonexistent_execution(self, basic_app: FakeApp):
        """get_execution_status returns error for unknown execution_id."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._get_execution_status("nonexistent_id"))

        assert "error" in result
        assert result["error"]["code"] == "execution_not_found"

    def test_returns_completed_info(self):
        """get_execution_status includes return_value and duration on completion."""
        app = FakeApp(
            descriptors=[FakeDescriptor(name="quick_job", docstring="Quick.")],
            execute_results={
                "quick_job": FakeJobResult(
                    status="success", return_value={"answer": 42}, duration_ms=15.0
                )
            },
        )
        registry = MCPToolRegistry(app, config=MCPConfig())
        result = asyncio.run(registry._run_job_async("quick_job"))

        execution_id = result["execution_id"]
        # Wait for completion
        time.sleep(0.1)

        status = asyncio.run(registry._get_execution_status(execution_id))
        assert status["status"] == "success"
        assert status["return_value"] == {"answer": 42}
        assert status["duration_ms"] is not None
        assert "started_at" in status


# ---------------------------------------------------------------------------
# Tests for error response structure
# ---------------------------------------------------------------------------


class TestErrorResponses:
    """Tests verifying structured error responses."""

    def test_error_has_code_and_message(self, basic_app: FakeApp):
        """Error responses contain code and message fields."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())
        result = asyncio.run(registry._get_job_schema("no_such_job"))

        assert "error" in result
        assert "code" in result["error"]
        assert "message" in result["error"]
        assert isinstance(result["error"]["code"], str)
        assert isinstance(result["error"]["message"], str)

    def test_non_visible_jobs_get_not_accessible_error(self, basic_app: FakeApp):
        """Non-visible jobs (internal, excluded) get 'not_accessible' errors."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())

        # Internal job
        result = asyncio.run(registry._run_job("internal_job"))
        assert result["error"]["code"] == "job_not_accessible"

    def test_nonexistent_jobs_get_not_found_error(self, basic_app: FakeApp):
        """Nonexistent jobs get 'not_found' errors."""
        registry = MCPToolRegistry(basic_app, config=MCPConfig())

        result = asyncio.run(registry._run_job("totally_fake_job"))
        assert result["error"]["code"] == "job_not_found"
