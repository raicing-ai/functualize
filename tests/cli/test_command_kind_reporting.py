"""Surfaces that *report* where a command came from report it correctly.

Two do: the TUI job browser prints a source column, and `builtin info schema`
publishes a `kind` an agent filters on. Both used to answer from a proxy rather
than from the node — the browser hardcoded "builtin" for any node without a job
descriptor, and the schema derived kind from `path[0] == "builtin"`. Both
proxies were correct only while jobs and the reserved subtree were the only
things in the tree.

Once plugin commands joined, the browser would have labelled `mcp` first-party
and the schema would have called `mcp serve` a job — telling an agent filtering
on `--kind job` to run something the job registry has never heard of.
"""

from __future__ import annotations

from types import SimpleNamespace

from functualize._cli.info import command_schemas
from functualize.app import FunctualizeApp
from functualize.app.commands import build_command_tree, command_kind
from functualize.app.config import JobSources


def _app():
    def alpha() -> None:
        """A job."""

    app = FunctualizeApp(name="t", job_sources=JobSources(functions=[alpha]))
    app.extensions.register_plugin_command(
        "serve", lambda port: None, help_text="Serve it", namespace="demo"
    )
    return app


def _node(app, name):
    return next(n for n in build_command_tree(app) if n.name == name)


class TestCommandKind:
    def test_job_node(self) -> None:
        assert command_kind(_node(_app(), "alpha")) == "job"

    def test_plugin_namespace_node(self) -> None:
        assert command_kind(_node(_app(), "demo")) == "plugin"

    def test_plugin_command_node(self) -> None:
        child = _node(_app(), "demo").children()[0]
        assert command_kind(child) == "plugin"

    def test_builtin_node(self) -> None:
        assert command_kind(_node(_app(), "builtin")) == "builtin"


class TestInfoSchemaKind:
    def test_plugin_command_is_published_as_plugin(self) -> None:
        entries = {e["name"]: e for e in command_schemas(_app())}
        assert entries["demo.serve"]["kind"] == "plugin"

    def test_plugin_command_is_not_published_as_a_job(self) -> None:
        """The regression: `--kind job` must not offer a plugin command."""
        jobs = command_schemas(_app(), kind="job")
        assert "demo.serve" not in {e["name"] for e in jobs}
        assert "alpha" in {e["name"] for e in jobs}

    def test_kind_filter_selects_plugins(self) -> None:
        """Subset, not equality — an app also loads whatever the environment
        has installed, and this checkout's dev env carries functualize-mcp."""
        plugins = command_schemas(_app(), kind="plugin")
        names = {e["name"] for e in plugins}

        assert "demo.serve" in names
        assert all(e["kind"] == "plugin" for e in plugins)
        assert "alpha" not in names

    def test_namespace_itself_is_not_runnable(self) -> None:
        """`demo` names a place; publishing it would offer an empty schema."""
        assert "demo" not in {e["name"] for e in command_schemas(_app())}

    def test_ordering_is_jobs_then_plugins_then_builtins(self) -> None:
        kinds = [e["kind"] for e in command_schemas(_app())]
        assert kinds == sorted(kinds, key={"job": 0, "plugin": 1, "builtin": 2}.get)


class TestJobBrowserSourceLabel:
    def test_plugin_namespace_is_not_labelled_builtin(self) -> None:
        """`builtin` names the reserved namespace, not "not a job"."""
        from functualize._cli.tui.job_listing import command_tree_rows

        rows = command_tree_rows(SimpleNamespace(_func_app=_app()))
        by_name = {r.name: r for r in rows}

        assert by_name["demo"].source_label == "plugin"
        assert by_name["builtin"].source_label == "builtin"

    def test_real_jobs_keep_their_descriptor(self) -> None:
        from functualize._cli.tui.job_listing import command_tree_rows

        rows = command_tree_rows(SimpleNamespace(_func_app=_app()))
        alpha = next(r for r in rows if r.name == "alpha")
        assert not hasattr(alpha, "source_label")
