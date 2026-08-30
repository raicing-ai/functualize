"""Tests for the static wiring fast path.

Verifies that fully-explicit configuration results in zero filesystem I/O
during boot, correct job descriptor creation, and sub-5ms cold start time.

Validates: Requirements 17.1, 17.2, 17.3, 17.4, 17.5
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from functualize._config.chain import ResolutionChain
from functualize._discovery.providers import Job
from functualize.app.config import (
    ConfigSources,
    ExecutionConfig,
    JobSources,
    PluginSources,
)
from functualize.app.core import FunctualizeApp

# --- Sample job functions for testing ---


def deploy() -> None:
    """Deploy the application."""
    pass


def build() -> None:
    """Build the application."""
    pass


def test_job() -> None:
    """Run tests."""
    pass


# --- Test fixtures ---


def _make_noop_resolution_chain() -> ResolutionChain:
    """Create a minimal ResolutionChain that performs no filesystem I/O."""
    from functualize._config.sources import DefaultSource

    return ResolutionChain([DefaultSource({})])


class TestStaticWiringDetection:
    """Tests for _is_fully_explicit() detection logic."""

    def test_fully_explicit_detected(self) -> None:
        """All sources explicitly provided → static wiring enabled."""
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy, build]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
            execution=ExecutionConfig(max_invoke_depth=5),
        )
        assert app._static_wiring is True

    def test_directories_disables_static(self) -> None:
        """Providing directories forces standard boot path."""
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(
                functions=[deploy],
                directories=["/nonexistent/path"],
            ),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        assert app._static_wiring is False

    def test_no_explicit_config_disables_static(self) -> None:
        """Missing config_resolution_chain forces standard boot path."""
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy]),
            config_sources=ConfigSources(),  # No explicit chain
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        assert app._static_wiring is False

    def test_entry_point_group_disables_static(self) -> None:
        """Non-empty entry_point_group forces standard boot path."""
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(
                entry_point_group="functualize.plugins", explicit_plugins=[]
            ),
        )
        assert app._static_wiring is False

    def test_children_disables_static(self) -> None:
        """Providing children forces standard boot path."""
        # We test detection by constructing the config objects and calling
        # the detection method on a minimally-bootstrapped app
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        # Verify it was static (baseline)
        assert app._static_wiring is True

        # Now test that children would disable it by checking detection logic
        # directly with a modified job_sources
        app._job_sources = JobSources(functions=[deploy], children={"child": "./child"})
        app._jobs_directories = []
        assert app._is_fully_explicit() is False

    def test_empty_functions_list_is_static(self) -> None:
        """Empty functions list (non-None) still enables static wiring."""
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        assert app._static_wiring is True


class TestStaticWiringJobDiscovery:
    """Tests that static wiring correctly produces job descriptors."""

    def test_plain_callables_produce_descriptors(self) -> None:
        """Plain functions produce descriptors named by __name__."""
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy, build, test_job]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        jobs = app.get_jobs()
        job_names = {j.name for j in jobs}
        assert job_names == {"deploy", "build", "test-job"}

    def test_job_dataclass_overrides(self) -> None:
        """Job dataclass allows name, group, config_model overrides."""
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(
                functions=[
                    Job(function=deploy, name="deploy-prod", group="infra"),
                    build,
                ]
            ),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        jobs = app.get_jobs()
        job_names = {j.name for j in jobs}
        assert "deploy-prod" in job_names
        assert "build" in job_names

        # Verify group override
        deploy_desc = next(j for j in jobs if j.name == "deploy-prod")
        assert deploy_desc.group == "infra"

    def test_get_job_by_name(self) -> None:
        """get_job() works for statically-wired jobs."""
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy, build]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        desc = app.get_job("deploy")
        assert desc is not None
        assert desc.name == "deploy"

    def test_get_job_returns_none_for_missing(self) -> None:
        """get_job() returns None for non-existent job name."""
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        assert app.get_job("nonexistent") is None

    def test_empty_functions_list_produces_no_jobs(self) -> None:
        """Empty functions list produces zero descriptors."""
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        assert app.get_jobs() == []


class TestStaticWiringZeroFilesystemIO:
    """Tests that static wiring performs zero filesystem I/O."""

    def test_no_open_calls_during_boot(self) -> None:
        """Fully-explicit config produces zero open() calls during boot."""
        import builtins

        original_open = builtins.open
        open_calls: list[str] = []

        def tracking_open(*args, **kwargs):
            if args:
                open_calls.append(str(args[0]))
            return original_open(*args, **kwargs)

        with patch.object(builtins, "open", tracking_open):
            FunctualizeApp(
                "test-app",
                job_sources=JobSources(functions=[deploy, build]),
                config_sources=ConfigSources(
                    config_resolution_chain=_make_noop_resolution_chain(),
                    dotenv=False,
                ),
                plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
            )

        assert open_calls == [], f"Unexpected open() calls: {open_calls}"

    def test_no_stat_calls_during_boot(self) -> None:
        """Fully-explicit config produces zero os.stat() calls during boot."""
        import os as os_module

        stat_calls: list[str] = []
        original_stat = os_module.stat

        def tracking_stat(path, *args, **kwargs):
            stat_calls.append(str(path))
            return original_stat(path, *args, **kwargs)

        with patch.object(os_module, "stat", tracking_stat):
            FunctualizeApp(
                "test-app",
                job_sources=JobSources(functions=[deploy, build]),
                config_sources=ConfigSources(
                    config_resolution_chain=_make_noop_resolution_chain(),
                    dotenv=False,
                ),
                plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
            )

        assert stat_calls == [], f"Unexpected stat() calls: {stat_calls}"

    def test_no_listdir_calls_during_boot(self) -> None:
        """Fully-explicit config produces zero directory listing calls."""
        import os as os_module

        listdir_calls: list[str] = []
        original_listdir = os_module.listdir

        def tracking_listdir(path="."):
            listdir_calls.append(str(path))
            return original_listdir(path)

        with patch.object(os_module, "listdir", tracking_listdir):
            FunctualizeApp(
                "test-app",
                job_sources=JobSources(functions=[deploy, build]),
                config_sources=ConfigSources(
                    config_resolution_chain=_make_noop_resolution_chain(),
                    dotenv=False,
                ),
                plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
            )

        assert listdir_calls == [], f"Unexpected listdir() calls: {listdir_calls}"


class TestStaticWiringBootPerformance:
    """Tests that static wiring boot completes in <5ms."""

    @pytest.mark.perf_budget
    def test_cold_start_under_5ms(self) -> None:
        """Fully-explicit config boots in under 5ms wall clock time.

        A mean over five runs against a 10ms threshold, so one slow iteration
        decides it — and the first is routinely slow on a loaded runner
        (`156.41ms` average from `['773.42ms', '2.24ms', '2.02ms', '2.11ms',
        '2.25ms']`). Marked `perf_budget` so the `test-full` tier skips it;
        `test-fast` still enforces it on every PR, serially and without
        coverage, which is the only place the number means anything.
        """
        chain = _make_noop_resolution_chain()

        # Warm up imports (first import may be slow)
        FunctualizeApp(
            "warmup",
            job_sources=JobSources(functions=[deploy]),
            config_sources=ConfigSources(config_resolution_chain=chain),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )

        # Measure actual boot time (average of 5 runs)
        durations: list[float] = []
        for _ in range(5):
            start = time.perf_counter()
            FunctualizeApp(
                "bench",
                job_sources=JobSources(functions=[deploy, build, test_job]),
                config_sources=ConfigSources(config_resolution_chain=chain),
                plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
            )
            duration_ms = (time.perf_counter() - start) * 1000
            durations.append(duration_ms)

        avg_ms = sum(durations) / len(durations)
        # Allow generous margin (5ms target, 10ms test threshold for CI variance)
        assert avg_ms < 10.0, (
            f"Static wiring boot averaged {avg_ms:.2f}ms "
            f"(target <5ms, test threshold 10ms). "
            f"Individual runs: {[f'{d:.2f}ms' for d in durations]}"
        )


class TestStaticWiringPlugins:
    """Tests that explicit plugins work correctly in static wiring mode."""

    def test_explicit_plugins_invoked(self) -> None:
        """Explicit plugins are called with app during boot."""
        invocations: list[FunctualizeApp] = []

        class FakePlugin:
            name = "test-plugin"
            version = "1.0.0"
            description = "Test plugin"

            def __call__(self, app: FunctualizeApp) -> None:
                invocations.append(app)

        plugin = FakePlugin()
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(
                entry_point_group="", explicit_plugins=[plugin]
            ),
        )
        assert len(invocations) == 1
        assert invocations[0] is app

    def test_disabled_plugins_skipped(self) -> None:
        """Plugins in the disabled list are not invoked."""
        invocations: list[str] = []

        class PluginA:
            name = "plugin-a"
            version = "1.0.0"
            description = "Plugin A"

            def __call__(self, app: FunctualizeApp) -> None:
                invocations.append("a")

        class PluginB:
            name = "plugin-b"
            version = "1.0.0"
            description = "Plugin B"

            def __call__(self, app: FunctualizeApp) -> None:
                invocations.append("b")

        FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(
                entry_point_group="",
                explicit_plugins=[PluginA(), PluginB()],
                disabled=["plugin-b"],
            ),
        )
        assert invocations == ["a"]

    def test_plugin_registration_error_is_logged_not_raised(self) -> None:
        """Plugin errors during registration are logged, not raised."""

        class FailingPlugin:
            name = "failing"
            version = "1.0.0"
            description = "Fails"

            def __call__(self, app: FunctualizeApp) -> None:
                raise RuntimeError("Plugin failed!")

        # Should not raise
        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(
                entry_point_group="", explicit_plugins=[FailingPlugin()]
            ),
        )
        assert app._static_wiring is True


class TestStaticWiringDIRegistry:
    """Tests that DI registry is properly frozen in static wiring mode."""

    def test_registry_frozen_after_boot(self) -> None:
        """DI registry is frozen after static wiring boot."""
        from functualize._primitives.di import RegistryFrozenError

        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        with pytest.raises(RegistryFrozenError):
            app.provide(str, "value")

    def test_plugin_can_register_di_before_freeze(self) -> None:
        """Plugins can register DI entries during boot (before freeze)."""

        class DIPlugin:
            name = "di-plugin"
            version = "1.0.0"
            description = "Registers DI"

            def __call__(self, app: FunctualizeApp) -> None:
                app.provide(int, 42)

        app = FunctualizeApp(
            "test-app",
            job_sources=JobSources(functions=[deploy]),
            config_sources=ConfigSources(
                config_resolution_chain=_make_noop_resolution_chain(),
                dotenv=False,
            ),
            plugin_sources=PluginSources(
                entry_point_group="", explicit_plugins=[DIPlugin()]
            ),
        )
        # Verify the DI entry is accessible
        assert app._di_registry.resolve(int) == 42
