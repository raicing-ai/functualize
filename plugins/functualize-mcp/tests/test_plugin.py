"""Unit tests for functualize-mcp plugin.

Tests the MCP adapter plugin's core behavior: tool registration,
job discovery, schema export, and execution routing.
"""

from __future__ import annotations

import asyncio

from functualize_mcp._config import MCPConfig
from functualize_mcp._tools import MCPToolRegistry

from .conftest import FakeApp, FakeDescriptor


class TestMCPToolDiscovery:
    """Tests for job discovery via MCP tools."""

    def test_discover_returns_visible_jobs(self, fake_app):
        registry = MCPToolRegistry(fake_app, config=MCPConfig())
        result = asyncio.run(registry._discover_jobs())
        job_names = [j["name"] for j in result["jobs"]]
        assert "greet" in job_names
        assert "deploy" in job_names

    def test_discover_empty_app(self):
        app = FakeApp(descriptors=[])
        registry = MCPToolRegistry(app, config=MCPConfig())
        result = asyncio.run(registry._discover_jobs())
        assert result == {"jobs": []}


class TestMCPToolExecution:
    """Tests for job execution via MCP tools."""

    def test_run_job_success(self, fake_app):
        registry = MCPToolRegistry(fake_app, config=MCPConfig())
        result = asyncio.run(registry._run_job("greet", {"name": "Alice"}))
        assert result["status"] == "success"

    def test_run_nonexistent_job(self, fake_app):
        registry = MCPToolRegistry(fake_app, config=MCPConfig())
        result = asyncio.run(registry._run_job("nonexistent"))
        assert "error" in result
        assert result["error"]["code"] == "job_not_found"

    def test_run_job_with_execution_error(self):
        app = FakeApp(
            descriptors=[FakeDescriptor(name="broken", docstring="Broken job.")],
            execute_error=RuntimeError("kaboom"),
        )
        registry = MCPToolRegistry(app, config=MCPConfig())
        result = asyncio.run(registry._run_job("broken"))
        assert "error" in result
        assert "kaboom" in result["error"]["message"]


class TestGroupMetadataShape:
    """D2-a: the `group` annotation is a structured trie shape, not a string.

    An agent consuming MCP tool metadata should read the namespace hierarchy as
    data (an array of segments + a kind) rather than re-splitting a dotted
    string it has to know the grammar of. See contracts §9.
    """

    def test_grouped_job_exports_namespace_and_kind(self):
        from functualize_mcp._translator import JobToolTranslator

        tool = JobToolTranslator().translate(
            FakeDescriptor(name="infra.aws.deploy", group="infra.aws")
        )
        assert tool.annotations["group"] == {
            "namespace": ["infra", "aws"],
            "kind": "job",
        }

    def test_single_segment_group_is_a_one_element_array(self):
        from functualize_mcp._translator import JobToolTranslator

        tool = JobToolTranslator().translate(
            FakeDescriptor(name="deploy.web", group="deploy")
        )
        assert tool.annotations["group"] == {"namespace": ["deploy"], "kind": "job"}

    def test_ungrouped_job_has_no_group_annotation(self):
        from functualize_mcp._translator import JobToolTranslator

        tool = JobToolTranslator().translate(FakeDescriptor(name="solo", group=None))
        assert "group" not in tool.annotations

    def test_group_value_is_no_longer_a_bare_string(self):
        """The whole point: consumers must not receive the opaque dotted form."""
        from functualize_mcp._translator import JobToolTranslator

        tool = JobToolTranslator().translate(
            FakeDescriptor(name="infra.aws.deploy", group="infra.aws")
        )
        assert not isinstance(tool.annotations["group"], str)
