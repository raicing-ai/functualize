"""Shell completion offers plugin commands.

It did not, and the reason was a defaulted argument. `extract_completion_data`
built the namespace trie with job rows only, leaving `build_group_trie`'s second
positional — `plugin_namespaces`, the very one `_dispatch_group` fills — empty.
So `func mcp serve` ran perfectly while `func mc<TAB>` completed nothing.

Nothing about this surface made it hard: its own docstring says it runs "from a
**booted** app", so `get_plugin_commands()` was available the whole time. It was
simply never asked.
"""

from __future__ import annotations

from functualize._cli.completions.data import extract_completion_data
from functualize.app import FunctualizeApp
from functualize.app.config import JobSources, PluginSources


def _app(*, jobs=(), commands=()):
    """An app whose plugin commands are exactly what a test declares.

    `PluginSources` points discovery at a group nobody publishes under, so a
    `functualize-mcp` that happens to be installed in the developer's
    environment cannot make an assertion pass or fail.
    """

    app = FunctualizeApp(
        name="t",
        job_sources=JobSources(functions=list(jobs) or None),
        plugin_sources=PluginSources(entry_point_group="functualize.plugins.__none__"),
    )
    for kwargs in commands:
        app.register_plugin_command(**kwargs)
    return app


class TestNamespaceCompletion:
    def test_namespace_is_offered_at_top_level(self) -> None:
        data = extract_completion_data(
            _app(commands=[dict(name="serve", callback=lambda: None, namespace="demo")])
        )
        assert "demo" in data.command_tree[""]

    def test_subcommands_are_offered_under_the_namespace(self) -> None:
        data = extract_completion_data(
            _app(
                commands=[
                    dict(name="serve", callback=lambda: None, namespace="demo"),
                    dict(name="stop", callback=lambda: None, namespace="demo"),
                ]
            )
        )
        assert sorted(data.command_tree["demo"]) == ["serve", "stop"]

    def test_top_level_command_is_offered(self) -> None:
        data = extract_completion_data(
            _app(commands=[dict(name="solo", callback=lambda: None)])
        )
        assert "solo" in data.command_tree[""]


class TestCoexistence:
    def test_jobs_and_builtin_are_still_offered(self) -> None:
        """The regression guard: adding plugin rows must not displace anything."""

        def alpha() -> None:
            """A job."""

        data = extract_completion_data(
            _app(
                jobs=[alpha],
                commands=[dict(name="serve", callback=lambda: None, namespace="demo")],
            )
        )
        top = data.command_tree[""]
        assert {"alpha", "demo", "builtin"} <= set(top)

    def test_builtin_subtree_survives(self) -> None:
        data = extract_completion_data(
            _app(commands=[dict(name="serve", callback=lambda: None, namespace="demo")])
        )
        assert data.command_tree["builtin"]


class TestPrecedence:
    def test_a_shadowed_command_is_not_offered(self) -> None:
        """Completion must not suggest something dispatch would refuse to run."""

        def collide() -> None:
            """The job."""

        data = extract_completion_data(
            _app(jobs=[collide], commands=[dict(name="collide", callback=lambda: None)])
        )
        # Present once, as the job — offering it is right; offering it twice or
        # as the plugin command would not be.
        assert data.command_tree[""].count("collide") == 1
        assert "collide" not in data.command_tree
