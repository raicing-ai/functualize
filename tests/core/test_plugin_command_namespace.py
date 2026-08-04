"""`PluginCommand.namespace` round-trip + its (non-)relationship to the cache.

`PluginCommand.group` was renamed to `namespace` (A1) so it stops colliding
with `JobDescriptor.group`, which is a *dotted job hierarchy* — a different
concept. These tests pin two things:

1. `namespace` survives the whole registration path (app → adapter → click),
   which is the only "round trip" a plugin command actually has.
2. Plugin commands are **runtime-only**: they are registered at APP_READY and
   never reach the discovery cache. The group trie (A3) therefore cannot source
   plugin namespaces from cached rows pre-boot — it must take them from
   ``app.get_plugin_commands()`` post-boot. Test 2 is the guard that keeps that
   assumption honest if the cache format ever grows a plugin section.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import click
import pytest

from functualize._app.models import PluginCommand
from functualize._app.state import AppState
from functualize._primitives.cache_format import CACHE_FILENAME
from functualize.app import FunctualizeApp
from functualize.app.adapters.cli import register_plugin_commands


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


def _only(app: FunctualizeApp, name: str) -> PluginCommand:
    """The single registered plugin command called `name`."""
    matches = [c for c in app.get_plugin_commands() if c.name == name]
    assert len(matches) == 1, f"expected exactly one '{name}', got {len(matches)}"
    return matches[0]


class TestNamespaceRegistrationRoundTrip:
    """`namespace=` survives registration and drives the click command tree.

    Names are prefixed ``ns-test`` because a real installed plugin (e.g.
    ``functualize-mcp``) may already have claimed the obvious ones on a booted
    app; these tests assert about their own commands, not the whole set.
    """

    def test_namespace_survives_register_to_get(self) -> None:
        app = FunctualizeApp(name="testapp")

        def serve() -> None:
            pass

        app.register_plugin_command("ns-test-serve", serve, "Start", namespace="nstest")

        cmd = _only(app, "ns-test-serve")
        assert isinstance(cmd, PluginCommand)
        assert cmd.namespace == "nstest"

    def test_namespace_becomes_a_click_sub_group(self) -> None:
        app = FunctualizeApp(name="testapp")

        def serve() -> None:
            pass

        def stop() -> None:
            pass

        app.register_plugin_command("ns-test-serve", serve, "Start", namespace="nstest")
        app.register_plugin_command("ns-test-stop", stop, "Stop", namespace="nstest")
        app.register_plugin_command("ns-test-top", serve, "Top level")

        root = click.Group(name="func")
        sub_groups = register_plugin_commands(root, app)

        assert "nstest" in sub_groups
        assert sorted(sub_groups["nstest"].commands) == [
            "ns-test-serve",
            "ns-test-stop",
        ]
        # The namespace is a sibling of un-namespaced commands, not a parent.
        assert "nstest" in root.commands
        assert "ns-test-top" in root.commands
        assert "ns-test-serve" not in root.commands

    def test_none_namespace_stays_top_level(self) -> None:
        app = FunctualizeApp(name="testapp")

        def solo() -> None:
            pass

        app.register_plugin_command("ns-test-solo", solo, "Solo")

        assert _only(app, "ns-test-solo").namespace is None

        root = click.Group(name="func")
        sub_groups = register_plugin_commands(root, app)

        assert "ns-test-solo" in root.commands
        assert not any("ns-test-solo" in g.commands for g in sub_groups.values())


class TestPluginCommandsAreNotCached:
    """The discovery cache carries jobs and displays — never plugin commands."""

    def test_cache_file_has_no_plugin_section(
        self, cli_run, project_tree, xdg_dirs
    ) -> None:
        root = project_tree(jobs={"hello.py": "def hello():\n    print('world')\n"})
        result = cli_run(["hello"], cwd=root)
        assert result.exit_code == 0

        cache_files = [
            p
            for p in (
                *Path(root).rglob(CACHE_FILENAME),
                *Path(xdg_dirs.cache).rglob(CACHE_FILENAME),
            )
        ]
        assert cache_files, "expected the run to have written a discovery cache"

        for cache_file in cache_files:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            # Whatever the format version is, plugin commands are not in it.
            assert "plugin_commands" not in data
            assert "plugin_namespaces" not in data
            for entry in data.get("entries", {}).values():
                assert "namespace" not in entry
