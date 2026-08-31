"""Integration tests for the unified config access refactoring.

Verifies wiring/integration of the refactored components:
- create_job_command() constructs JobConfigView (not Configurations)
- All JobConfigView instances within the same app share the same ResolutionChain
- End-to-end job execution with rc.config.get() works correctly

Requirements: 5.2, 5.3, 8.2, 11.1, 11.2
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from functualize._config.chain import ResolutionChain
from functualize._config.job_config import JobConfigView
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain
from functualize._events.hooks import HookRegistry

if TYPE_CHECKING:
    import pytest

    from functualize.job.context import RunContext


def _make_cli_wiring_factory() -> dict[str, Any]:
    """Build a cli_wiring_factory dict for test JobRegistry instances."""
    from functualize.app.adapters.click_params import create_job_command

    return {"create_job_command": create_job_command}


# --- Helpers ---


class FakeSource:
    """Minimal Source implementation for testing."""

    def __init__(
        self,
        source_type: str = "test",
        source_id: str = "test-source",
        data: dict[tuple[str | None, str], Any] | None = None,
    ) -> None:
        self._source_type = source_type
        self._source_id = source_id
        self._data: dict[tuple[str | None, str], Any] = data or {}

    @property
    def source_type(self) -> str:
        return self._source_type

    @property
    def source_id(self) -> str:
        return self._source_id

    def get(self, key: str, section: str | None = None) -> Any | None:
        return self._data.get((section, key))

    def has(self, key: str, section: str | None = None) -> bool:
        return (section, key) in self._data


# --- Integration Tests ---


class TestCreateJobCommandConstructsJobConfigView:
    """Verify create_job_command() constructs JobConfigView (not Configurations).

    Requirements: 5.2
    """

    def _make_mock_app(self, chain: ResolutionChain) -> MagicMock:
        """Create a mock app with a real execution engine and custom resolution chain."""
        mock_app = MagicMock()
        mock_app._resolution_chain = chain
        mock_app.plugin_config_registry.get_all.return_value = {}
        # Configure event_bus and middleware to take the zero-cost path
        mock_app.event_bus.has_subscribers = False
        mock_app.middleware.has_middleware.return_value = False

        # Build a config_view_factory that creates JobConfigView from the chain
        def _config_view_factory(*, section_prefix: str = "") -> JobConfigView:
            return JobConfigView(
                resolution_chain=chain, default_section_prefix=section_prefix
            )

        # Add a real execution engine so the registry dispatch passes isinstance check
        engine = JobExecutionEngine(
            di_registry=mock_app._di_registry,
            event_bus=MagicMock(),
            hook_registry=HookRegistry(),
            middleware_chain=ExecutionMiddlewareChain(),
            resolution_chain=chain,
            config_view_factory=_config_view_factory,
        )
        mock_app._execution_engine = engine
        mock_app.execution_engine = engine
        return mock_app

    def test_wrapper_creates_job_config_view(self, tmp_path: Path) -> None:
        """When a job command wrapper is invoked, it constructs a JobConfigView."""
        from functualize._app.state import AppState
        from functualize._discovery.registry import JobRegistry
        from functualize._events.hooks import HookRegistry

        # Set up minimal state
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.base.toml").write_text('[general]\napp_name = "test"\n')

        # Build a real resolution chain
        source = FakeSource(
            source_type="file",
            source_id="config.base.toml",
            data={("general", "app_name"): "test", ("myjob", "timeout"): "30"},
        )
        chain = ResolutionChain([source])

        mock_app = self._make_mock_app(chain)
        registry = JobRegistry(
            hook_registry=HookRegistry(),
            app=mock_app,
            cli_wiring_factory=_make_cli_wiring_factory(),
        )

        # Track what config type is injected into RunContext
        captured_config = []

        def my_job(rc: RunContext) -> str:
            captured_config.append(rc.config)
            return "done"

        # Create the wrapped command
        wrapped = registry.create_job_command("myjob", my_job)

        # Set AppState as the wrapper expects
        AppState.set("config_directory", str(config_dir))
        AppState.set("environment", "DEV")

        try:
            wrapped()
        finally:
            AppState.set("config_directory", None)
            AppState.set("environment", None)

        assert len(captured_config) == 1
        assert isinstance(captured_config[0], JobConfigView)

    def test_wrapper_uses_app_resolution_chain(self, tmp_path: Path) -> None:
        """The JobConfigView created in the wrapper uses the app's ResolutionChain."""
        from functualize._app.state import AppState
        from functualize._discovery.registry import JobRegistry
        from functualize._events.hooks import HookRegistry

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.base.toml").write_text('[general]\napp_name = "test"\n')

        source = FakeSource(
            source_type="file",
            source_id="config.base.toml",
            data={("myjob", "key1"): "value_from_chain"},
        )
        chain = ResolutionChain([source])

        mock_app = self._make_mock_app(chain)
        registry = JobRegistry(
            hook_registry=HookRegistry(),
            app=mock_app,
            cli_wiring_factory=_make_cli_wiring_factory(),
        )

        captured_values = []

        def my_job(rc: RunContext) -> str:
            captured_values.append(rc.config.get("key1"))
            return "done"

        wrapped = registry.create_job_command("myjob", my_job)

        AppState.set("config_directory", str(config_dir))
        AppState.set("environment", "DEV")

        try:
            wrapped()
        finally:
            AppState.set("config_directory", None)
            AppState.set("environment", None)

        assert captured_values == ["value_from_chain"]


class TestResolutionChainSharedInstance:
    """Verify same ResolutionChain instance shared across all JobConfigView instances.

    Requirements: 5.3
    """

    def _make_mock_app(self, chain: ResolutionChain) -> MagicMock:
        """Create a mock app with a real execution engine and custom resolution chain."""
        mock_app = MagicMock()
        mock_app._resolution_chain = chain
        mock_app.plugin_config_registry.get_all.return_value = {}
        mock_app.event_bus.has_subscribers = False
        mock_app.middleware.has_middleware.return_value = False

        def _config_view_factory(section_prefix: str = "") -> JobConfigView:
            return JobConfigView(
                resolution_chain=chain, default_section_prefix=section_prefix
            )

        engine = JobExecutionEngine(
            di_registry=mock_app._di_registry,
            event_bus=MagicMock(),
            hook_registry=HookRegistry(),
            middleware_chain=ExecutionMiddlewareChain(),
            resolution_chain=chain,
            config_view_factory=_config_view_factory,
        )
        mock_app._execution_engine = engine
        mock_app.execution_engine = engine
        return mock_app

    def test_multiple_job_commands_share_same_chain(self, tmp_path: Path) -> None:
        """All JobConfigView instances from the same app share the same chain instance."""
        from functualize._app.state import AppState
        from functualize._discovery.registry import JobRegistry
        from functualize._events.hooks import HookRegistry

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.base.toml").write_text("[general]\n")

        source = FakeSource(data={("general", "key"): "val"})
        chain = ResolutionChain([source])

        mock_app = self._make_mock_app(chain)
        registry = JobRegistry(
            hook_registry=HookRegistry(),
            app=mock_app,
            cli_wiring_factory=_make_cli_wiring_factory(),
        )

        captured_chains: list[ResolutionChain] = []

        def job_a(rc: RunContext) -> str:
            # Access the internal chain from JobConfigView
            captured_chains.append(rc.config._chain)
            return "a"

        def job_b(rc: RunContext) -> str:
            captured_chains.append(rc.config._chain)
            return "b"

        wrapped_a = registry.create_job_command("job_a", job_a)
        wrapped_b = registry.create_job_command("job_b", job_b)

        AppState.set("config_directory", str(config_dir))
        AppState.set("environment", "DEV")

        try:
            wrapped_a()
            wrapped_b()
        finally:
            AppState.set("config_directory", None)
            AppState.set("environment", None)

        assert len(captured_chains) == 2
        # Identity check — same object, not just equal
        assert captured_chains[0] is captured_chains[1]
        assert captured_chains[0] is chain


class TestEndToEndJobExecution:
    """Verify end-to-end job execution with rc.config.get() works correctly.

    Requirements: 5.2, 5.3, 11.1, 11.2
    """

    def _make_mock_app(self, chain: ResolutionChain) -> MagicMock:
        """Create a mock app with a real execution engine and custom resolution chain."""
        mock_app = MagicMock()
        mock_app._resolution_chain = chain
        mock_app.plugin_config_registry.get_all.return_value = {}
        mock_app.event_bus.has_subscribers = False
        mock_app.middleware.has_middleware.return_value = False

        def _config_view_factory(section_prefix: str = "") -> JobConfigView:
            return JobConfigView(
                resolution_chain=chain, default_section_prefix=section_prefix
            )

        engine = JobExecutionEngine(
            di_registry=mock_app._di_registry,
            event_bus=MagicMock(),
            hook_registry=HookRegistry(),
            middleware_chain=ExecutionMiddlewareChain(),
            resolution_chain=chain,
            config_view_factory=_config_view_factory,
        )
        mock_app._execution_engine = engine
        mock_app.execution_engine = engine
        return mock_app

    def test_job_reads_config_from_resolution_chain(self, tmp_path: Path) -> None:
        """A job invoked via the registry can read config values through rc.config.get()."""
        from functualize._app.state import AppState
        from functualize._discovery.registry import JobRegistry
        from functualize._events.hooks import HookRegistry

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.base.toml").write_text(
            '[general]\napp_name = "integration_test"\n\n'
            "[my_job]\ntimeout = 60\nretries = 3\n"
        )

        # Build chain with known test data
        source = FakeSource(
            data={
                ("my_job", "timeout"): "60",
                ("my_job", "retries"): "3",
                ("general", "app_name"): "integration_test",
            }
        )
        chain = ResolutionChain([source])

        mock_app = self._make_mock_app(chain)
        registry = JobRegistry(
            hook_registry=HookRegistry(),
            app=mock_app,
            cli_wiring_factory=_make_cli_wiring_factory(),
        )

        results: dict[str, Any] = {}

        def my_job(rc: RunContext) -> str:
            results["timeout"] = rc.config.get("timeout")
            results["retries"] = rc.config.get("retries")
            results["missing"] = rc.config.get("missing_key", default="fallback")
            return "completed"

        wrapped = registry.create_job_command("my_job", my_job)

        AppState.set("config_directory", str(config_dir))
        AppState.set("environment", "DEV")

        try:
            wrapped()
        finally:
            AppState.set("config_directory", None)
            AppState.set("environment", None)

        assert results["timeout"] == "60"
        assert results["retries"] == "3"
        assert results["missing"] == "fallback"

    def test_job_override_takes_precedence(self, tmp_path: Path) -> None:
        """rc.config.set() overrides take precedence over chain values."""
        from functualize._app.state import AppState
        from functualize._discovery.registry import JobRegistry
        from functualize._events.hooks import HookRegistry

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.base.toml").write_text("[general]\n")

        source = FakeSource(data={("my_job", "timeout"): "60"})
        chain = ResolutionChain([source])

        mock_app = self._make_mock_app(chain)
        registry = JobRegistry(
            hook_registry=HookRegistry(),
            app=mock_app,
            cli_wiring_factory=_make_cli_wiring_factory(),
        )

        results: dict[str, Any] = {}

        def my_job(rc: RunContext) -> str:
            # Override value
            rc.config.set("timeout", "120")
            results["timeout"] = rc.config.get("timeout")
            return "done"

        wrapped = registry.create_job_command("my_job", my_job)

        AppState.set("config_directory", str(config_dir))
        AppState.set("environment", "DEV")

        try:
            wrapped()
        finally:
            AppState.set("config_directory", None)
            AppState.set("environment", None)

        # Override should win over chain value
        assert results["timeout"] == "120"

    def test_job_config_scoped_to_job_name(self, tmp_path: Path) -> None:
        """JobConfigView default section is scoped to the job name via set_prefix."""
        from functualize._app.state import AppState
        from functualize._discovery.registry import JobRegistry
        from functualize._events.hooks import HookRegistry

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.base.toml").write_text("[general]\n")

        source = FakeSource(
            data={
                ("my_job", "db_host"): "localhost",
                ("general", "db_host"): "general_host",
            }
        )
        chain = ResolutionChain([source])

        mock_app = self._make_mock_app(chain)
        registry = JobRegistry(
            hook_registry=HookRegistry(),
            app=mock_app,
            cli_wiring_factory=_make_cli_wiring_factory(),
        )

        results: dict[str, Any] = {}

        def my_job(rc: RunContext) -> str:
            # With default section = "my_job" (set by RunContext's set_prefix)
            results["scoped"] = rc.config.get("db_host")
            # With explicit section override
            results["general"] = rc.config.get("db_host", section="general")
            return "done"

        wrapped = registry.create_job_command("my_job", my_job)

        AppState.set("config_directory", str(config_dir))
        AppState.set("environment", "DEV")

        try:
            wrapped()
        finally:
            AppState.set("config_directory", None)
            AppState.set("environment", None)

        assert results["scoped"] == "localhost"
        assert results["general"] == "general_host"

    def test_env_var_precedence_in_job(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Environment variables take precedence over file sources in chain."""
        from functualize._app.state import AppState
        from functualize._config.sources import EnvSource
        from functualize._discovery.registry import JobRegistry
        from functualize._events.hooks import HookRegistry

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.base.toml").write_text("[general]\n")

        # Set env var before building chain with EnvSource
        monkeypatch.setenv("MY_JOB_PORT", "9999")

        # Build chain with env source AND file source
        env_source = EnvSource()
        file_source = FakeSource(data={("my_job", "port"): "8080"})
        chain = ResolutionChain([env_source, file_source])

        mock_app = self._make_mock_app(chain)
        registry = JobRegistry(
            hook_registry=HookRegistry(),
            app=mock_app,
            cli_wiring_factory=_make_cli_wiring_factory(),
        )

        results: dict[str, Any] = {}

        def my_job(rc: RunContext) -> str:
            results["port"] = rc.config.get("port")
            return "done"

        wrapped = registry.create_job_command("my_job", my_job)

        AppState.set("config_directory", str(config_dir))
        AppState.set("environment", "DEV")

        try:
            wrapped()
        finally:
            AppState.set("config_directory", None)
            AppState.set("environment", None)

        # Env var wins over file source
        assert results["port"] == "9999"
