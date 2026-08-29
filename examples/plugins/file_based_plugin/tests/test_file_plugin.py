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


def test_loader_discovers_plugin_from_directory():
    """The real PluginLoader finds the plugin via the convention directory."""
    from functualize._plugins.loader import PluginLoader

    loader = PluginLoader()
    app = MagicMock()
    app._resolution_chain.resolve.side_effect = Exception("no config")

    import os

    cwd = os.getcwd()
    os.chdir(_EXAMPLE_ROOT)
    try:
        plugins = loader._discover_from_files(app)
    finally:
        os.chdir(cwd)

    assert [p.name for p in plugins] == ["run-notifier"]
