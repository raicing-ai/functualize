"""Integration tests for full plugin config flow.

Tests end-to-end: plugin declares config → resolved via Resolution_Chain →
stored in registry → delivered via RunContext → job accesses it.
Tests middleware chain with resource injection and state store usage.
Tests workflow scope shared across multiple job invocations.

Requirements: 2.1, 3.4, 5.5, 10.1, 10.2
"""

from __future__ import annotations

import textwrap
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from pydantic import BaseModel, Field

from functualize._app.state import AppState
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp
from functualize.job._workflow_scope import WorkflowScope
from functualize.job.context import inject_resource

runner = CliRunner()


def _resolve_model_from_defaults(section: str, model_cls: type[Any]) -> Any:
    """Resolve a model by instantiating it with all defaults (simulates Resolution_Chain).

    This is what the real Resolution_Chain does when no config files, env vars,
    or CLI args provide values for the section — it resolves using model defaults.
    """
    return model_cls()


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


# ---------------------------------------------------------------------------
# Helper: Plugin config model used in tests
# ---------------------------------------------------------------------------


class NotificationConfig(BaseModel):
    """Sample plugin config model for integration testing."""

    webhook_url: str = Field(default="https://default.hook")
    timeout: int = Field(default=30)
    enabled: bool = Field(default=True)


class DatabaseConfig(BaseModel):
    """Another sample plugin config model."""

    connection_string: str = Field(default="sqlite:///:memory:")
    pool_size: int = Field(default=5)


# ---------------------------------------------------------------------------
# Helper: Create a fake plugin object
# ---------------------------------------------------------------------------


def _make_plugin(
    name: str,
    version: str,
    description: str,
    config_model: type[BaseModel] | None = None,
    config_section: str | None = None,
    depends_on: list[str] | None = None,
    on_config_resolved_cb: Any = None,
) -> Any:
    """Create a mock plugin object satisfying PluginMetadata and optionally Config protocol."""
    plugin = MagicMock()
    plugin.name = name
    plugin.version = version
    plugin.description = description
    plugin.depends_on = depends_on or []

    if config_model and config_section:
        plugin.config_model = config_model
        plugin.config_section = config_section
    else:
        # Remove these attributes to simulate legacy plugins
        del plugin.config_model
        del plugin.config_section

    if on_config_resolved_cb is not None:
        plugin.on_config_resolved = on_config_resolved_cb
    else:
        del plugin.on_config_resolved

    return plugin


def _make_entry_point(name: str, plugin: Any) -> Any:
    """Create a mock entry point that returns the given plugin."""
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = plugin
    return ep


# ===========================================================================
# 1. Full Plugin Config Flow: declare → resolve → store → deliver → access
# ===========================================================================


class TestFullPluginConfigFlow:
    """End-to-end: plugin declares config → resolved → stored → delivered via RunContext."""

    @patch("functualize._plugins.loader.entry_points")
    @patch.object(
        FunctualizeApp, "resolve_model", side_effect=_resolve_model_from_defaults
    )
    def test_plugin_config_declared_resolved_and_accessible_in_job(
        self, _mock_resolve: Any, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """A plugin with config_model is resolved and accessible to jobs via RunContext."""
        # Setup: create a plugin that declares config
        resolved_configs: list[BaseModel] = []

        def on_resolved(config: BaseModel) -> None:
            resolved_configs.append(config)

        plugin = _make_plugin(
            name="notifier",
            version="1.0.0",
            description="Notification plugin",
            config_model=NotificationConfig,
            config_section="plugin.notifications",
            on_config_resolved_cb=on_resolved,
        )
        ep = _make_entry_point("notifier-ep", plugin)
        mock_entry_points.return_value = [ep]

        # Create a jobs directory with a job that reads plugin config
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "notify_job.py"
        job_file.write_text(
            textwrap.dedent("""\
            from functualize.job.context import RunContext

            def notify_job(rc: RunContext):
                '''A job that accesses plugin config.'''
                config = rc.get_plugin_config("plugin.notifications")
                print(f"webhook_url={config.webhook_url}")
                print(f"timeout={config.timeout}")
                print(f"enabled={config.enabled}")
            """)
        )

        # Create the app - this triggers plugin loading
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        # Verify the plugin was loaded and config resolved
        assert "notifier" in app.plugin_loader.loaded_plugins
        assert app.plugin_config_registry.has("plugin.notifications")
        assert len(resolved_configs) == 1
        assert isinstance(resolved_configs[0], NotificationConfig)

        # Run the job via CLI
        result = runner.invoke(app.cli_command, ["notify_job"])
        assert result.exit_code == 0
        assert "webhook_url=https://default.hook" in result.output
        assert "timeout=30" in result.output
        assert "enabled=True" in result.output

    @patch("functualize._plugins.loader.entry_points")
    def test_plugin_config_resolved_with_env_override(
        self, mock_entry_points: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Plugin config fields are overridden by environment variables via resolve_model.

        We simulate the Resolution_Chain incorporating env vars by patching
        resolve_model to read from os.environ (same precedence the real chain uses).
        """
        import os

        plugin = _make_plugin(
            name="notifier",
            version="1.0.0",
            description="Notification plugin",
            config_model=NotificationConfig,
            config_section="plugin.notifications",
        )
        ep = _make_entry_point("notifier-ep", plugin)
        mock_entry_points.return_value = [ep]

        # Set env var following convention: section name uppercased with _ separators
        monkeypatch.setenv("PLUGIN_NOTIFICATIONS_WEBHOOK_URL", "https://env.hook")
        monkeypatch.setenv("PLUGIN_NOTIFICATIONS_TIMEOUT", "60")

        def _resolve_with_env(section: str, model_cls: type[Any]) -> Any:
            """Simulate resolution chain reading env vars."""
            prefix = section.upper().replace(".", "_") + "_"
            overrides: dict[str, str] = {}
            for key, val in os.environ.items():
                if key.startswith(prefix):
                    field_name = key[len(prefix) :].lower()
                    overrides[field_name] = val
            return model_cls(**overrides)

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "check_env.py"
        job_file.write_text(
            textwrap.dedent("""\
            from functualize.job.context import RunContext

            def check_env(rc: RunContext):
                '''Check env-resolved plugin config.'''
                config = rc.get_plugin_config("plugin.notifications")
                print(f"webhook_url={config.webhook_url}")
                print(f"timeout={config.timeout}")
            """)
        )

        with patch.object(
            FunctualizeApp, "resolve_model", side_effect=_resolve_with_env
        ):
            app = FunctualizeApp(
                name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
            )

        result = runner.invoke(app.cli_command, ["check_env"])
        assert result.exit_code == 0
        # Env vars should override defaults
        assert "webhook_url=https://env.hook" in result.output
        assert "timeout=60" in result.output

    @patch("functualize._plugins.loader.entry_points")
    @patch.object(
        FunctualizeApp, "resolve_model", side_effect=_resolve_model_from_defaults
    )
    def test_multiple_plugins_configs_all_accessible(
        self, _mock_resolve: Any, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """Multiple plugins with different config sections are all accessible."""
        plugin_a = _make_plugin(
            name="notifier",
            version="1.0.0",
            description="Notifications",
            config_model=NotificationConfig,
            config_section="plugin.notifications",
        )
        plugin_b = _make_plugin(
            name="db",
            version="2.0.0",
            description="Database",
            config_model=DatabaseConfig,
            config_section="plugin.database",
        )
        ep_a = _make_entry_point("notifier-ep", plugin_a)
        ep_b = _make_entry_point("db-ep", plugin_b)
        mock_entry_points.return_value = [ep_a, ep_b]

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "multi_config.py"
        job_file.write_text(
            textwrap.dedent("""\
            from functualize.job.context import RunContext

            def multi_config(rc: RunContext):
                '''Access multiple plugin configs.'''
                notif = rc.get_plugin_config("plugin.notifications")
                db = rc.get_plugin_config("plugin.database")
                print(f"notif_url={notif.webhook_url}")
                print(f"db_pool={db.pool_size}")
                print(f"config_count={len(rc.plugin_configs)}")
            """)
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["multi_config"])

        assert result.exit_code == 0
        assert "notif_url=https://default.hook" in result.output
        assert "db_pool=5" in result.output
        assert "config_count=2" in result.output

    @patch("functualize._plugins.loader.entry_points")
    @patch.object(
        FunctualizeApp, "resolve_model", side_effect=_resolve_model_from_defaults
    )
    def test_plugin_config_immutable_from_job(
        self, _mock_resolve: Any, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """Jobs cannot mutate plugin_configs mapping."""
        plugin = _make_plugin(
            name="notifier",
            version="1.0.0",
            description="Notifications",
            config_model=NotificationConfig,
            config_section="plugin.notifications",
        )
        ep = _make_entry_point("notifier-ep", plugin)
        mock_entry_points.return_value = [ep]

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "immutable_check.py"
        job_file.write_text(
            textwrap.dedent("""\
            from functualize.job.context import RunContext

            def immutable_check(rc: RunContext):
                '''Verify plugin_configs is immutable.'''
                try:
                    rc.plugin_configs["plugin.notifications"] = None
                    print("MUTABLE")
                except TypeError:
                    print("IMMUTABLE")
            """)
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["immutable_check"])

        assert result.exit_code == 0
        assert "IMMUTABLE" in result.output


# ===========================================================================
# 2. Middleware Chain with Resource Injection and State Store Usage
# ===========================================================================


class TestMiddlewareChainIntegration:
    """Integration tests for middleware chain with resource injection and state."""

    @patch("functualize._plugins.loader.entry_points")
    def test_middleware_injects_resource_accessible_by_job(
        self, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """Middleware injects a resource and the job accesses it via RunContext."""
        mock_entry_points.return_value = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "resource_user.py"
        job_file.write_text(
            textwrap.dedent("""\
            from functualize.job.context import RunContext

            def resource_user(rc: RunContext):
                '''A job that uses an injected resource.'''
                db = rc.get_resource("db_client", str)
                print(f"db_client={db}")
            """)
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        # Register middleware that injects a resource
        def resource_middleware(rc: Any) -> Generator[None]:
            inject_resource(rc, "db_client", "postgres://injected")
            yield

        app.register_run_middleware(resource_middleware)

        result = runner.invoke(app.cli_command, ["resource_user"])
        assert result.exit_code == 0
        assert "db_client=postgres://injected" in result.output

    @patch("functualize._plugins.loader.entry_points")
    def test_middleware_uses_state_store(
        self, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """Middleware writes to state store and the job reads it."""
        mock_entry_points.return_value = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "state_reader.py"
        job_file.write_text(
            textwrap.dedent("""\
            from functualize.job.context import RunContext

            def state_reader(rc: RunContext):
                '''A job that reads state set by middleware.'''
                val = rc.state.get("middleware_key", str)
                print(f"state_val={val}")
            """)
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        # Register middleware that writes to state store
        def state_middleware(rc: Any) -> Generator[None]:
            rc.state.set("middleware_key", "from_middleware")
            yield

        app.register_run_middleware(state_middleware)

        result = runner.invoke(app.cli_command, ["state_reader"])
        assert result.exit_code == 0
        assert "state_val=from_middleware" in result.output

    @patch("functualize._plugins.loader.entry_points")
    def test_middleware_priority_ordering(
        self, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """Multiple middleware execute in priority order (lower first)."""
        mock_entry_points.return_value = []
        execution_order: list[str] = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "ordered_job.py"
        job_file.write_text(
            textwrap.dedent("""\
            def ordered_job():
                '''A simple job for middleware ordering test.'''
                pass
            """)
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        def mw_high(rc: Any) -> Generator[None]:
            execution_order.append("mw_high_pre")
            yield
            execution_order.append("mw_high_post")

        def mw_low(rc: Any) -> Generator[None]:
            execution_order.append("mw_low_pre")
            yield
            execution_order.append("mw_low_post")

        # Register in reverse priority order to confirm sorting
        app.register_run_middleware(mw_high, priority=10)
        app.register_run_middleware(mw_low, priority=1)

        result = runner.invoke(app.cli_command, ["ordered_job"])
        assert result.exit_code == 0
        # Pre-yield: lower priority first; Post-yield: reverse order
        assert execution_order == [
            "mw_low_pre",
            "mw_high_pre",
            "mw_high_post",
            "mw_low_post",
        ]

    @patch("functualize._plugins.loader.entry_points")
    def test_middleware_post_yield_executes_on_job_success(
        self, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """Middleware post-yield phase runs after successful job."""
        mock_entry_points.return_value = []
        post_yield_called: list[bool] = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "success_mw.py"
        job_file.write_text(
            textwrap.dedent("""\
            def success_mw():
                '''A job that succeeds.'''
                pass
            """)
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        def cleanup_middleware(rc: Any) -> Generator[None]:
            yield
            post_yield_called.append(True)

        app.register_run_middleware(cleanup_middleware)

        result = runner.invoke(app.cli_command, ["success_mw"])
        assert result.exit_code == 0
        assert post_yield_called == [True]

    @patch("functualize._plugins.loader.entry_points")
    @patch.object(
        FunctualizeApp, "resolve_model", side_effect=_resolve_model_from_defaults
    )
    def test_middleware_with_plugin_config_access(
        self, _mock_resolve: Any, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """Middleware can access plugin configs from RunContext."""
        plugin = _make_plugin(
            name="notifier",
            version="1.0.0",
            description="Notifications",
            config_model=NotificationConfig,
            config_section="plugin.notifications",
        )
        ep = _make_entry_point("notifier-ep", plugin)
        mock_entry_points.return_value = [ep]

        captured_urls: list[str] = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "mw_cfg_job.py"
        job_file.write_text(
            textwrap.dedent("""\
            def mw_cfg_job():
                '''A simple job.'''
                pass
            """)
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        def config_reading_middleware(rc: Any) -> Generator[None]:
            config = rc.get_plugin_config("plugin.notifications")
            captured_urls.append(config.webhook_url)
            yield

        app.register_run_middleware(config_reading_middleware)

        result = runner.invoke(app.cli_command, ["mw_cfg_job"])
        assert result.exit_code == 0
        assert captured_urls == ["https://default.hook"]


# ===========================================================================
# 3. Workflow Scope Shared Across Multiple Job Invocations
# ===========================================================================


class TestWorkflowScopeSharedState:
    """Integration tests for WorkflowScope sharing state across job invocations."""

    @patch("functualize._plugins.loader.entry_points")
    def test_workflow_scope_state_shared_between_jobs(
        self, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """State stored via WorkflowScope persists across separate job RunContexts."""
        mock_entry_points.return_value = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        # Job A writes to state
        job_a = jobs_dir / "job_a.py"
        job_a.write_text(
            textwrap.dedent("""\
            from functualize.job.context import RunContext

            def job_a(rc: RunContext):
                '''First job - writes state.'''
                rc.state.set("counter", 42)
                print(f"job_a_wrote=42")
            """)
        )

        # Job B reads state
        job_b = jobs_dir / "job_b.py"
        job_b.write_text(
            textwrap.dedent("""\
            from functualize.job.context import RunContext

            def job_b(rc: RunContext):
                '''Second job - reads state.'''
                val = rc.state.get("counter", int)
                print(f"job_b_read={val}")
            """)
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        # Create a workflow scope
        scope = app.create_workflow_scope("my-workflow", metadata={"run": "test"})

        # Register middleware that injects the workflow scope's state store
        def scope_middleware(rc: Any) -> Generator[None]:
            # Replace the RunContext's state store with the scope's shared one
            rc._state_store = scope.state_store
            yield

        app.register_run_middleware(scope_middleware)

        # Execute job_a - writes state
        result_a = runner.invoke(app.cli_command, ["job_a"])
        assert result_a.exit_code == 0
        assert "job_a_wrote=42" in result_a.output

        # Execute job_b - should read state from shared scope
        result_b = runner.invoke(app.cli_command, ["job_b"])
        assert result_b.exit_code == 0
        assert "job_b_read=42" in result_b.output

    @patch("functualize._plugins.loader.entry_points")
    def test_workflow_scope_close_prevents_mutation(
        self, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """After closing a WorkflowScope, state mutation raises error."""
        mock_entry_points.return_value = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "write_closed.py"
        job_file.write_text(
            textwrap.dedent("""\
            from functualize.job.context import RunContext

            def write_closed(rc: RunContext):
                '''Try to write to closed state.'''
                try:
                    rc.state.set("key", "value")
                    print("WRITE_SUCCESS")
                except Exception as e:
                    print(f"WRITE_BLOCKED:{type(e).__name__}")
            """)
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        # Create and close a workflow scope
        scope = app.create_workflow_scope("closed-workflow")
        scope.state_store.set("pre_close", "data")
        scope.close()

        # Register middleware that injects the closed scope's state store
        def closed_scope_middleware(rc: Any) -> Generator[None]:
            rc._state_store = scope.state_store
            yield

        app.register_run_middleware(closed_scope_middleware)

        result = runner.invoke(app.cli_command, ["write_closed"])
        assert result.exit_code == 0
        assert "WRITE_BLOCKED:InvalidStateTransitionError" in result.output

    @patch("functualize._plugins.loader.entry_points")
    def test_workflow_scope_metadata_accessible(
        self, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """Workflow scope metadata is accessible to middleware/plugins."""
        mock_entry_points.return_value = []

        app = FunctualizeApp(name="testapp")

        # Create scope with metadata
        scope = app.create_workflow_scope(
            "metadata-flow",
            metadata={"provider": "restate", "run_url": "https://restate.dev/run/1"},
        )

        assert scope.metadata["provider"] == "restate"
        assert scope.metadata["run_url"] == "https://restate.dev/run/1"
        assert scope.scope_id == "metadata-flow"

    def test_workflow_scope_state_accumulates_across_invocations(self) -> None:
        """WorkflowScope state accumulates correctly across multiple calls."""
        scope = WorkflowScope("accumulate-scope")
        store = scope.state_store

        # Simulate multiple job invocations writing different keys
        store.set("step_1_result", "ok")
        store.set("step_2_result", "processed")
        store.set("step_3_result", "done")

        # All state is visible
        assert store.get("step_1_result", str) == "ok"
        assert store.get("step_2_result", str) == "processed"
        assert store.get("step_3_result", str) == "done"
        assert set(store.keys()) == {"step_1_result", "step_2_result", "step_3_result"}


# ===========================================================================
# 4. Combined: Plugin Config + Middleware + Scope in Single Flow
# ===========================================================================


class TestCombinedPluginMiddlewareScopeFlow:
    """Tests combining plugin config, middleware, resource injection, and scope."""

    @patch("functualize._plugins.loader.entry_points")
    @patch.object(
        FunctualizeApp, "resolve_model", side_effect=_resolve_model_from_defaults
    )
    def test_full_orchestration_flow(
        self, _mock_resolve: Any, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """Full flow: plugin config + middleware resource injection + scope state."""
        plugin = _make_plugin(
            name="notifier",
            version="1.0.0",
            description="Notifications",
            config_model=NotificationConfig,
            config_section="plugin.notifications",
        )
        ep = _make_entry_point("notifier-ep", plugin)
        mock_entry_points.return_value = [ep]

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "full_flow.py"
        job_file.write_text(
            textwrap.dedent("""\
            from functualize.job.context import RunContext

            def full_flow(rc: RunContext):
                '''Job exercising config, resources, and state.'''
                # Access plugin config
                notif = rc.get_plugin_config("plugin.notifications")
                print(f"notif_url={notif.webhook_url}")

                # Access injected resource
                client = rc.get_resource("http_client", str)
                print(f"http_client={client}")

                # Read and write state
                prev = rc.state.get("invocation_count", int)
                new_count = (prev or 0) + 1
                rc.state.set("invocation_count", new_count)
                print(f"invocation={new_count}")
            """)
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        # Create a workflow scope for shared state
        scope = app.create_workflow_scope("orchestration-flow")

        # Register middleware: inject resource + attach scope state store
        def orchestration_middleware(rc: Any) -> Generator[None]:
            inject_resource(rc, "http_client", "httpx-session-mock")
            rc._state_store = scope.state_store
            yield

        app.register_run_middleware(orchestration_middleware)

        # First invocation
        result1 = runner.invoke(app.cli_command, ["full_flow"])
        assert result1.exit_code == 0
        assert "notif_url=https://default.hook" in result1.output
        assert "http_client=httpx-session-mock" in result1.output
        assert "invocation=1" in result1.output

        # Second invocation - state persists via scope
        result2 = runner.invoke(app.cli_command, ["full_flow"])
        assert result2.exit_code == 0
        assert "invocation=2" in result2.output

    @patch("functualize._plugins.loader.entry_points")
    def test_legacy_plugin_loads_without_config(
        self, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """A legacy plugin without config_model/config_section loads identically."""
        legacy_plugin = _make_plugin(
            name="legacy-hook",
            version="1.0.0",
            description="A legacy plugin",
        )
        ep = _make_entry_point("legacy-ep", legacy_plugin)
        mock_entry_points.return_value = [ep]

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        job_file = jobs_dir / "legacy_test.py"
        job_file.write_text(
            textwrap.dedent("""\
            from functualize.job.context import RunContext

            def legacy_test(rc: RunContext):
                '''Job with legacy plugin.'''
                # plugin_configs should be empty (no config plugins)
                print(f"config_count={len(rc.plugin_configs)}")
            """)
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        # Legacy plugin should be loaded
        assert "legacy-hook" in app.plugin_loader.loaded_plugins
        # No config registered
        assert not app.plugin_config_registry.has("anything")

        result = runner.invoke(app.cli_command, ["legacy_test"])
        assert result.exit_code == 0
        assert "config_count=0" in result.output

    @patch("functualize._plugins.loader.entry_points")
    @patch.object(
        FunctualizeApp, "resolve_model", side_effect=_resolve_model_from_defaults
    )
    def test_dependency_ordered_plugins_config_resolution(
        self, _mock_resolve: Any, mock_entry_points: Any, tmp_path: Path
    ) -> None:
        """Plugins with dependencies are loaded in correct order before config resolution."""
        load_order: list[str] = []

        def make_ordered_plugin(
            name: str,
            config_section: str,
            depends: list[str] | None = None,
        ) -> Any:
            plugin = _make_plugin(
                name=name,
                version="1.0.0",
                description=f"{name} plugin",
                config_model=NotificationConfig,
                config_section=config_section,
                depends_on=depends,
            )

            def call_side_effect(app: Any) -> None:
                load_order.append(name)

            plugin.side_effect = call_side_effect
            return plugin

        # Plugin B depends on Plugin A
        plugin_a = make_ordered_plugin("plugin-a", "plugin.a")
        plugin_b = make_ordered_plugin("plugin-b", "plugin.b", depends=["plugin-a"])

        ep_a = _make_entry_point("ep-a", plugin_a)
        ep_b = _make_entry_point("ep-b", plugin_b)
        # Provide in reverse order to test sorting
        mock_entry_points.return_value = [ep_b, ep_a]

        app = FunctualizeApp(name="testapp")

        # Both should be loaded
        assert "plugin-a" in app.plugin_loader.loaded_plugins
        assert "plugin-b" in app.plugin_loader.loaded_plugins
        # A should be loaded before B
        assert load_order.index("plugin-a") < load_order.index("plugin-b")
