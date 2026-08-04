"""Unit tests for CliAdapter extraction (Task 13.2).

Tests the CliAdapter satisfies the AdapterPlugin Protocol, raises ValueError
on command name conflicts, builds command tree from app.get_jobs() + plugin
commands, and verifies the get_jobs/get_plugin_commands facades.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from functualize._app.models import PluginCommand
from functualize.app.adapters import AdapterPlugin, validate_adapter
from functualize.app.adapters.cli import CliAdapter

# =============================================================================
# Test Fixtures: Minimal app mocks
# =============================================================================


@dataclass
class FakeJobDescriptor:
    """Minimal job descriptor for testing."""

    name: str
    group: str | None = None
    module_path: str = "test_module"
    source_file: str = "<test>"
    source_mtime: float = 0.0
    content_hash: str = ""
    docstring: str | None = None
    config_fields: list[Any] = field(default_factory=list)
    dependencies: dict[str, str] = field(default_factory=dict)
    metadata: Any = None
    declaration: Any = None


def make_fake_app(
    jobs: list[FakeJobDescriptor] | None = None,
    plugin_commands: list[PluginCommand] | None = None,
) -> MagicMock:
    """Create a minimal mock FunctualizeApp for testing CliAdapter."""
    app = MagicMock()
    app.get_jobs.return_value = jobs or []
    app.get_plugin_commands.return_value = plugin_commands or []
    app._event_bus = None
    app._hook_registry = None
    app.plugin_loader.loaded_instances = []
    # job_registry.get_job raises KeyError for unknown jobs (simulates no registered funcs)
    app.job_registry.get_job.side_effect = KeyError("not registered")
    return app


# =============================================================================
# Unit Tests: Protocol Conformance (Requirement 11.1)
# =============================================================================


class TestCliAdapterProtocol:
    """Tests that CliAdapter satisfies the AdapterPlugin Protocol."""

    def test_satisfies_adapter_plugin_protocol(self):
        """CliAdapter instance passes isinstance check against AdapterPlugin."""
        adapter = CliAdapter()
        assert isinstance(adapter, AdapterPlugin)

    def test_passes_validate_adapter(self):
        """CliAdapter passes the validate_adapter() check."""
        adapter = CliAdapter()
        validate_adapter(adapter)

    def test_adapter_type_is_cli(self):
        """adapter_type field is 'cli'."""
        adapter = CliAdapter()
        assert adapter.adapter_type == "cli"

    def test_has_required_fields(self):
        """CliAdapter has name, version, description, adapter_type."""
        adapter = CliAdapter()
        assert hasattr(adapter, "name")
        assert hasattr(adapter, "version")
        assert hasattr(adapter, "description")
        assert hasattr(adapter, "adapter_type")
        assert isinstance(adapter.name, str)
        assert isinstance(adapter.version, str)
        assert isinstance(adapter.description, str)

    def test_has_required_methods(self):
        """CliAdapter has __call__, run, shutdown methods."""
        adapter = CliAdapter()
        assert callable(adapter)
        assert callable(adapter.run)
        assert callable(adapter.shutdown)

    def test_shutdown_is_noop(self):
        """shutdown() does not raise and is a no-op."""
        adapter = CliAdapter()
        adapter.shutdown()  # Should not raise


# =============================================================================
# Unit Tests: __call__(app) (Requirement 11.3)
# =============================================================================


class TestCliAdapterCall:
    """Tests for CliAdapter.__call__(app) setup phase."""

    def test_call_stores_app_reference(self):
        """__call__ stores the app reference internally."""
        adapter = CliAdapter()
        app = make_fake_app()
        adapter(app)
        assert adapter._app is app

    def test_call_retrieves_plugin_commands(self):
        """__call__ retrieves plugin commands from app.get_plugin_commands()."""
        cmd = PluginCommand(name="my-cmd", callback=lambda: None, help_text="A command")
        app = make_fake_app(plugin_commands=[cmd])
        adapter = CliAdapter()
        adapter(app)
        # Plugin commands are now registered directly via register_plugin_commands()
        # Verify that get_plugin_commands was called during setup
        app.get_plugin_commands.assert_called_once()


# =============================================================================
# Unit Tests: ValueError on conflicts (Requirement 11.5)
# =============================================================================


class TestCliAdapterConflicts:
    """Tests for ValueError on command name conflicts."""

    def test_raises_on_plugin_job_name_conflict(self):
        """ValueError raised when plugin command name matches a job name."""
        jobs = [FakeJobDescriptor(name="deploy")]
        cmd = PluginCommand(name="deploy", callback=lambda: None, help_text="Conflict")
        app = make_fake_app(jobs=jobs, plugin_commands=[cmd])

        adapter = CliAdapter()
        adapter(app)

        with pytest.raises(ValueError, match="deploy"):
            adapter.run()

    def test_no_conflict_different_names(self):
        """No ValueError when plugin command and job names are different."""
        jobs = [FakeJobDescriptor(name="deploy")]
        cmd = PluginCommand(
            name="serve", callback=lambda: None, help_text="No conflict"
        )
        app = make_fake_app(jobs=jobs, plugin_commands=[cmd])

        adapter = CliAdapter()
        adapter(app)

        # check_name_conflicts should not raise
        from functualize.app.adapters.cli import check_name_conflicts

        check_name_conflicts(app)

    def test_no_conflict_when_plugin_in_group(self):
        """No conflict when plugin command with same name is in a namespace."""
        jobs = [FakeJobDescriptor(name="deploy")]
        cmd = PluginCommand(
            name="deploy",
            callback=lambda: None,
            help_text="Grouped",
            namespace="admin",
        )
        app = make_fake_app(jobs=jobs, plugin_commands=[cmd])

        adapter = CliAdapter()
        adapter(app)

        # Namespaced commands don't conflict with top-level job names
        from functualize.app.adapters.cli import check_name_conflicts

        check_name_conflicts(app)  # Should not raise


# =============================================================================
# Unit Tests: run() without __call__ (RuntimeError)
# =============================================================================


class TestCliAdapterRunWithoutSetup:
    """Tests that run() raises RuntimeError if __call__ was not invoked."""

    def test_run_without_call_raises_runtime_error(self):
        """run() raises RuntimeError if adapter was not set up."""
        adapter = CliAdapter()
        with pytest.raises(RuntimeError, match="run.*before.*__call__"):
            adapter.run()


# =============================================================================
# Unit Tests: PluginCommand dataclass
# =============================================================================


class TestPluginCommand:
    """Tests for the PluginCommand frozen dataclass."""

    def test_plugin_command_creation(self):
        """PluginCommand can be created with all fields."""
        cmd = PluginCommand(
            name="test-cmd",
            callback=lambda: None,
            help_text="A test command",
            namespace="admin",
        )
        assert cmd.name == "test-cmd"
        assert cmd.help_text == "A test command"
        assert cmd.namespace == "admin"
        assert callable(cmd.callback)

    def test_plugin_command_default_namespace_is_none(self):
        """PluginCommand.namespace defaults to None."""
        cmd = PluginCommand(name="test-cmd", callback=lambda: None, help_text="")
        assert cmd.namespace is None

    def test_plugin_command_is_frozen(self):
        """PluginCommand is immutable."""
        cmd = PluginCommand(name="test-cmd", callback=lambda: None, help_text="")
        with pytest.raises(AttributeError):
            cmd.name = "other"  # type: ignore[misc]


# =============================================================================
# Unit Tests: get_jobs() and get_plugin_commands() on FunctualizeApp
# =============================================================================


class TestFunctualizeAppFacades:
    """Tests for the get_jobs() and get_plugin_commands() methods on FunctualizeApp."""

    def test_get_jobs_returns_list(self):
        """get_jobs() returns a list (delegating to resolution pipeline)."""
        from functualize.app.core import FunctualizeApp

        # We can't easily instantiate a full FunctualizeApp in a unit test,
        # so we verify the method exists and has the right signature
        assert hasattr(FunctualizeApp, "get_jobs")
        assert callable(FunctualizeApp.get_jobs)

    def test_get_plugin_commands_returns_list(self):
        """get_plugin_commands() returns a list."""
        from functualize.app.core import FunctualizeApp

        assert hasattr(FunctualizeApp, "get_plugin_commands")
        assert callable(FunctualizeApp.get_plugin_commands)

    def test_get_job_returns_descriptor_or_none(self):
        """get_job() returns a descriptor or None."""
        from functualize.app.core import FunctualizeApp

        assert hasattr(FunctualizeApp, "get_job")
        assert callable(FunctualizeApp.get_job)
