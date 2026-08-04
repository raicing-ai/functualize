"""`PluginSources.explicit_plugins` on the standard (discovering) boot path.

`boot_static` has always honoured `explicit_plugins`, but it is only selected
when jobs, config AND plugins are all explicit *and* `entry_point_group` is
empty (`is_fully_explicit`). Every other app — including anything with a job
directory — took `boot_standard`, which delegated to `PluginLoader.load_all`
and never read `explicit_plugins`. The plugin was dropped with no warning: its
`__call__` simply never ran.

These pin that an explicitly-handed plugin loads wherever it is handed in.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from functualize._app.state import AppState
from functualize.app import FunctualizeApp
from functualize.app.config import JobSources, PluginSources


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


class RecordingPlugin:
    """Minimal plugin satisfying the metadata protocol."""

    name = "explicit-probe"
    version = "1.0.0"
    description = "Records that it was invoked."

    def __init__(self, name: str | None = None) -> None:
        if name is not None:
            self.name = name
        self.calls: list[Any] = []

    def __call__(self, app: Any) -> None:
        self.calls.append(app)
        app.register_plugin_command(
            f"{self.name}-cmd", lambda: None, "from the explicit plugin"
        )


def _app(tmp_path, plugin_sources: PluginSources) -> FunctualizeApp:
    jobs = tmp_path / "jobs"
    jobs.mkdir(exist_ok=True)
    (jobs / "hello.py").write_text("def hello():\n    print('hi')\n")
    return FunctualizeApp(
        name="testapp",
        job_sources=JobSources(directories=[str(jobs)]),
        plugin_sources=plugin_sources,
    )


class TestExplicitPluginRuns:
    def test_explicit_plugin_is_invoked_on_the_standard_path(self, tmp_path) -> None:
        """A job directory forces `boot_standard`; the plugin must still run."""
        plugin = RecordingPlugin()
        app = _app(tmp_path, PluginSources(explicit_plugins=[plugin]))

        assert len(plugin.calls) == 1
        assert plugin.calls[0] is app

    def test_its_registrations_reach_the_app(self, tmp_path) -> None:
        plugin = RecordingPlugin()
        app = _app(tmp_path, PluginSources(explicit_plugins=[plugin]))

        names = {c.name for c in app.get_plugin_commands()}
        assert "explicit-probe-cmd" in names

    def test_it_is_reachable_by_name(self, tmp_path) -> None:
        plugin = RecordingPlugin()
        app = _app(tmp_path, PluginSources(explicit_plugins=[plugin]))

        assert app._plugin_name_index.get("explicit-probe") is plugin
        assert plugin in app.plugin_loader.loaded_instances


class TestExplicitPluginFilters:
    def test_disabled_wins_over_explicit(self, tmp_path) -> None:
        """`disabled` is the user's other explicit instruction; it still wins."""
        plugin = RecordingPlugin()
        _app(
            tmp_path,
            PluginSources(explicit_plugins=[plugin], disabled=["explicit-probe"]),
        )

        assert plugin.calls == []

    def test_invalid_metadata_warns_and_skips(self, tmp_path, caplog) -> None:
        """A malformed explicit plugin is reported, not silently dropped."""

        class NoMetadata:
            def __call__(self, app: Any) -> None:  # pragma: no cover - never runs
                raise AssertionError("should not be invoked")

        _app(tmp_path, PluginSources(explicit_plugins=[NoMetadata()]))

        assert any(
            "does not satisfy the metadata protocol" in r.message
            for r in caplog.records
        )

    def test_registration_failure_is_reported(self, tmp_path, caplog) -> None:
        class Exploding:
            name = "exploding"
            version = "1.0.0"
            description = "Raises on registration."

            def __call__(self, app: Any) -> None:
                raise RuntimeError("boom")

        _app(tmp_path, PluginSources(explicit_plugins=[Exploding()]))

        assert any("boom" in r.message for r in caplog.records)


class TestPrecedence:
    def test_explicit_overrides_a_discovered_plugin_of_the_same_name(
        self, tmp_path, monkeypatch
    ) -> None:
        """The caller built this object by hand; discovery's claim is weaker.

        Without replacement the sort would see two plugins sharing a name and
        the duplicate check in phase 3 would drop whichever came second — an
        ordering coin-flip rather than a decision.
        """
        discovered = RecordingPlugin(name="collide")
        explicit = RecordingPlugin(name="collide")

        import functualize._plugins.loader as loader_mod

        monkeypatch.setattr(
            loader_mod.PluginLoader,
            "_discover_from_files",
            lambda self, app: [discovered],
        )

        _app(tmp_path, PluginSources(explicit_plugins=[explicit]))

        assert explicit.calls, "the explicit object should have been invoked"
        assert discovered.calls == [], "the discovered one should have been replaced"
