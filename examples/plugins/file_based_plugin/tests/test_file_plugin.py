"""Tests for the file-based plugin example."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

_EXAMPLE_ROOT = Path(__file__).parent.parent
_PLUGIN_FILE = _EXAMPLE_ROOT / ".functualize" / "plugins" / "run_notifier.py"


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location("run_notifier", _PLUGIN_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_exposes_plugin_object():
    """The loader looks for a module-level `plugin` satisfying the protocol."""
    mod = _load_plugin_module()
    plugin = mod.plugin
    assert isinstance(plugin.name, str)
    assert isinstance(plugin.version, str)
    assert isinstance(plugin.description, str)
    assert callable(plugin)


def test_plugin_subscribes_to_lifecycle_events():
    """Calling plugin(app) at boot subscribes to success/failure events."""
    mod = _load_plugin_module()
    app = MagicMock()
    mod.plugin(app)
    subscribed = [call.args[0] for call in app.event_bus.subscribe.call_args_list]
    assert "job.execute.success" in subscribed
    assert "job.execute.failure" in subscribed


def test_a_booted_app_loads_the_plugin_from_the_convention_directory(monkeypatch):
    """A real boot in this example directory finds and registers the plugin.

    This used to be three workarounds stacked on one bug: it reached into
    `functualize._plugins.loader` (an *example* importing an internal package),
    `chdir`-ed so the exact-CWD fallback would fire, and mocked
    `app._resolution_chain.resolve` to raise so the config branch would be
    stepped over. That branch could never have run anyway — the attribute does
    not exist when plugins load. The test passed and proved almost nothing.

    Now it boots the app the way a user does and asks what got loaded — and it
    boots from `jobs/`, one level *below* the example root, which the old
    exact-CWD fallback could not have handled at all. The convention directory
    is found by walking up to the project root, so where you stand no longer
    decides whether your plugins exist.
    """
    from functualize.app import FunctualizeApp

    monkeypatch.chdir(_EXAMPLE_ROOT / "jobs")
    app = FunctualizeApp(name="file-based-plugin-example")

    assert "run-notifier" in app.plugin_loader.loaded_plugins
