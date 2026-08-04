"""Tests for core/config_objects.py — frozen dataclass configs.

Verifies that all config objects are frozen (immutable) and have
correct default values as specified in the design.
"""

from __future__ import annotations

import dataclasses

import pytest

from functualize.app.config import (
    ConfigSources,
    ExecutionConfig,
    Job,
    JobSources,
    PluginSources,
)


class TestJobSources:
    """Tests for JobSources frozen dataclass."""

    def test_is_frozen(self) -> None:
        js = JobSources()
        with pytest.raises(dataclasses.FrozenInstanceError):
            js.lazy = False  # type: ignore[misc]

    def test_defaults(self) -> None:
        js = JobSources()
        assert js.directories is None
        assert js.functions is None
        assert js.job_providers is None
        assert js.children is None
        assert js.children_glob is None
        assert js.lazy is True

    def test_custom_values(self) -> None:
        js = JobSources(
            directories=["./jobs", "./tasks"],
            functions=[lambda: None],
            children={"analytics": "./analytics"},
            children_glob="plugins/*/",
            lazy=False,
        )
        assert js.directories == ["./jobs", "./tasks"]
        assert len(js.functions) == 1
        assert js.children == {"analytics": "./analytics"}
        assert js.children_glob == "plugins/*/"
        assert js.lazy is False

    def test_is_dataclass(self) -> None:
        assert dataclasses.is_dataclass(JobSources)


class TestConfigSources:
    """Tests for ConfigSources frozen dataclass."""

    def test_is_frozen(self) -> None:
        cs = ConfigSources()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cs.dotenv = False  # type: ignore[misc]

    def test_defaults(self) -> None:
        cs = ConfigSources()
        assert cs.file_pattern == r"^config\.(\w+)\.(\w+)$"
        assert cs.config_resolution_chain is None
        assert cs.dotenv is True
        assert cs.dotenv_path is None

    def test_custom_values(self) -> None:
        cs = ConfigSources(
            file_pattern=r"^settings\.\w+\.yaml$",
            dotenv=False,
            dotenv_path="/app/.env.production",
        )
        assert cs.file_pattern == r"^settings\.\w+\.yaml$"
        assert cs.dotenv is False
        assert cs.dotenv_path == "/app/.env.production"

    def test_is_dataclass(self) -> None:
        assert dataclasses.is_dataclass(ConfigSources)


class TestPluginSources:
    """Tests for PluginSources frozen dataclass."""

    def test_is_frozen(self) -> None:
        ps = PluginSources()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ps.entry_point_group = "other"  # type: ignore[misc]

    def test_defaults(self) -> None:
        ps = PluginSources()
        assert ps.entry_point_group == "functualize.plugins"
        assert ps.explicit_plugins is None
        assert ps.disabled is None

    def test_custom_values(self) -> None:
        class FakePlugin:
            pass

        ps = PluginSources(
            entry_point_group="myapp.plugins",
            explicit_plugins=[FakePlugin()],
            disabled=["slow-plugin", "debug-plugin"],
        )
        assert ps.entry_point_group == "myapp.plugins"
        assert len(ps.explicit_plugins) == 1
        assert ps.disabled == ["slow-plugin", "debug-plugin"]

    def test_is_dataclass(self) -> None:
        assert dataclasses.is_dataclass(PluginSources)


class TestExecutionConfig:
    """Tests for ExecutionConfig frozen dataclass."""

    def test_is_frozen(self) -> None:
        ec = ExecutionConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ec.max_invoke_depth = 20  # type: ignore[misc]

    def test_defaults(self) -> None:
        ec = ExecutionConfig()
        assert ec.max_invoke_depth == 10

    def test_custom_values(self) -> None:
        ec = ExecutionConfig(max_invoke_depth=5)
        assert ec.max_invoke_depth == 5

    def test_is_dataclass(self) -> None:
        assert dataclasses.is_dataclass(ExecutionConfig)


class TestJob:
    """Tests for Job frozen dataclass (re-exported from discovery.providers)."""

    def test_is_frozen(self) -> None:
        def my_func() -> None:
            pass

        job = Job(function=my_func)
        with pytest.raises(dataclasses.FrozenInstanceError):
            job.name = "override"  # type: ignore[misc]

    def test_defaults(self) -> None:
        def my_func() -> None:
            pass

        job = Job(function=my_func)
        assert job.function is my_func
        assert job.name is None
        assert job.group is None

    def test_custom_values(self) -> None:
        def deploy() -> None:
            pass

        job = Job(
            function=deploy,
            name="deploy-prod",
            group="infra",
        )
        assert job.function is deploy
        assert job.name == "deploy-prod"
        assert job.group == "infra"

    def test_is_dataclass(self) -> None:
        assert dataclasses.is_dataclass(Job)


class TestExports:
    """Verify that config_objects exports all required types."""

    def test_all_exports(self) -> None:
        from functualize.app import config as config_objects

        assert hasattr(config_objects, "JobSources")
        assert hasattr(config_objects, "ConfigSources")
        assert hasattr(config_objects, "PluginSources")
        assert hasattr(config_objects, "ExecutionConfig")
        assert hasattr(config_objects, "Job")

    def test_all_in_dunder_all(self) -> None:
        from functualize.app import config as config_objects

        expected = {
            "ConfigSources",
            "DiscoveryConfig",
            "ExecutionConfig",
            "Job",
            "JobSources",
            "PluginSources",
        }
        assert set(config_objects.__all__) == expected
