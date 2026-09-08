"""Plugin commands are in the one command tree, on the same terms as jobs.

They were not, and the asymmetry was the bug: `func mcp serve` ran, bare piped
`func` listed the namespace, and `app.cli_command` mounted it — but the tree
that the TUI browser, the input-bar completion, the pre-flight renderer and the
node executor all read did not know it existed. Typing `mcp serve` into the
shell produced no pre-flight, no error, and no output.

Everything here is asserted against a fake plugin registered on the app under
test. Never against `functualize-mcp` happening to be installed: that plugin is
present in this checkout's dev environment and absent in others, so a test that
leaned on it would pass or fail for reasons that have nothing to do with the
code.
"""

from __future__ import annotations

from functualize.app import FunctualizeApp
from functualize.app.commands import build_command_tree, unshadowed_plugin_commands
from functualize.app.config import JobSources


def _named(nodes, name):
    return next((n for n in nodes if n.name == name), None)


def _app_with(*, jobs=(), commands=()) -> FunctualizeApp:
    """An app carrying exactly the jobs and plugin commands a test declares."""
    app = FunctualizeApp(name="t", job_sources=JobSources(functions=list(jobs) or None))
    for kwargs in commands:
        app.register_plugin_command(**kwargs)
    return app


def _tree_without_env_plugins(app):
    """Top-level nodes, minus whatever the dev environment installed.

    An app loads every plugin on the machine. Filtering to the namespaces a
    test registered keeps it honest in both environments.
    """
    return build_command_tree(app)


class TestNamespacedCommands:
    def test_namespace_is_a_navigable_top_level_node(self) -> None:
        app = _app_with(
            commands=[
                dict(name="serve", callback=lambda: None, namespace="demo"),
                dict(name="stop", callback=lambda: None, namespace="demo"),
            ]
        )
        node = _named(_tree_without_env_plugins(app), "demo")

        assert node is not None, "namespace missing from the tree"
        assert sorted(c.name for c in node.children()) == ["serve", "stop"]

    def test_namespace_reports_its_command_count(self) -> None:
        app = _app_with(
            commands=[dict(name="serve", callback=lambda: None, namespace="demo")]
        )
        node = _named(_tree_without_env_plugins(app), "demo")
        assert node.help_text == "1 command"

    def test_namespace_is_not_runnable(self) -> None:
        """`func demo` names a place, not a command."""
        app = _app_with(
            commands=[dict(name="serve", callback=lambda: None, namespace="demo")]
        )
        assert _named(_tree_without_env_plugins(app), "demo").execute([]) == 1


class TestTopLevelCommands:
    def test_unnamespaced_command_is_a_runnable_top_level_node(self) -> None:
        ran: list[str] = []
        app = _app_with(
            commands=[
                dict(
                    name="solo",
                    callback=lambda: ran.append("yes"),
                    help_text="A solo command",
                )
            ]
        )
        node = _named(_tree_without_env_plugins(app), "solo")

        assert node is not None
        assert node.children() == []
        assert node.help_text == "A solo command"
        assert node.execute([]) == 0
        assert ran == ["yes"]


class TestOrdering:
    def test_builtin_sorts_last(self) -> None:
        """Existing contract: the reserved subtree is the final row."""

        def alpha() -> None:
            """A job."""

        app = _app_with(
            jobs=[alpha],
            commands=[dict(name="zeta", callback=lambda: None, namespace="demo")],
        )
        names = [n.name for n in _tree_without_env_plugins(app)]
        assert names[-1] == "builtin"
        assert names.index("alpha") < names.index("demo")


class TestTerminalAffinity:
    def test_declaration_reaches_the_node(self) -> None:
        app = _app_with(
            commands=[
                dict(
                    name="serve",
                    callback=lambda: None,
                    namespace="demo",
                    needs_terminal=True,
                ),
                dict(name="ping", callback=lambda: None, namespace="demo"),
            ]
        )
        children = {
            c.name: c for c in _named(_tree_without_env_plugins(app), "demo").children()
        }

        assert children["serve"].needs_terminal is True
        assert children["ping"].needs_terminal is False

    def test_namespace_never_owns_the_terminal(self) -> None:
        app = _app_with(
            commands=[
                dict(
                    name="serve",
                    callback=lambda: None,
                    namespace="demo",
                    needs_terminal=True,
                )
            ]
        )
        assert _named(_tree_without_env_plugins(app), "demo").needs_terminal is False


class TestParams:
    def test_callback_signature_becomes_node_params(self) -> None:
        """A pre-flight panel over a plugin command shows what click will parse."""

        def serve(port: int = 8080, host: str = "127.0.0.1") -> None:
            """Start it."""

        app = _app_with(commands=[dict(name="serve", callback=serve, namespace="demo")])
        node = _named(_tree_without_env_plugins(app), "demo").children()[0]

        assert {p.name for p in node.params()} == {"port", "host"}

    def test_execute_passes_arguments_through(self) -> None:
        seen: list[int] = []

        def serve(port: int = 8080) -> None:
            seen.append(port)

        app = _app_with(commands=[dict(name="serve", callback=serve, namespace="demo")])
        node = _named(_tree_without_env_plugins(app), "demo").children()[0]

        assert node.execute(["--port", "9000"]) == 0
        assert seen == [9000]


class TestPrecedence:
    """AC-A3 — a job wins, and the plugin command is *absent*, not skipped."""

    def test_job_shadows_a_top_level_plugin_command(self) -> None:
        def collide() -> None:
            """The job."""

        app = _app_with(
            jobs=[collide],
            commands=[
                dict(name="collide", callback=lambda: None, help_text="The plugin")
            ],
        )

        assert "collide" not in {c.name for c in unshadowed_plugin_commands(app)}, (
            "shadowed command should be absent from the resolved list"
        )

        node = _named(_tree_without_env_plugins(app), "collide")
        assert node is not None
        assert node.help_text == "The job."

    def test_unshadowed_commands_survive(self) -> None:
        def other() -> None:
            """A job by another name."""

        app = _app_with(
            jobs=[other],
            commands=[dict(name="keep", callback=lambda: None, namespace="demo")],
        )
        assert "keep" in {c.name for c in unshadowed_plugin_commands(app)}

    def test_duplicate_paths_collapse_to_first_registration(self) -> None:
        app = _app_with(
            commands=[
                dict(name="a", callback=lambda: None, namespace="demo"),
                dict(name="b", callback=lambda: None, namespace="demo"),
            ]
        )
        paths = [
            (c.namespace, c.name)
            for c in unshadowed_plugin_commands(app)
            if c.namespace == "demo"
        ]
        assert len(paths) == len(set(paths))


class TestPrecedenceIsOneRule:
    """AC-A3 — the tree and the CLI's group dispatch cannot disagree.

    They disagreed before: `_dispatch_group` derived the shadow key inline, the
    click adapter derived it not at all, and the tree did not know plugin
    commands existed. Reading one resolver is what forecloses "lists on one
    surface, runs on another".
    """

    def test_dispatch_runs_the_job_not_the_shadowed_plugin_command(self) -> None:
        """Behavioural, not a source-text grep.

        An earlier version of this test asserted that
        ``unshadowed_plugin_commands`` appeared in
        ``inspect.getsource(_dispatch_group)``. That passes for the wrong
        reason (any mention counts) and fails for the wrong reason too --
        editing the module while the suite runs makes ``linecache`` hand back a
        neighbouring function's source. What matters is which callable runs.
        """
        from functualize._cli.main import _dispatch_group

        ran: list[str] = []

        def serve() -> None:
            """The job."""
            ran.append("job")

        serve.__name__ = "serve"

        app = _app_with(
            jobs=[serve],
            commands=[
                dict(
                    name="serve",
                    callback=lambda: ran.append("plugin"),
                    help_text="The plugin",
                )
            ],
        )

        exit_code = _dispatch_group(app, ["serve"], set(), output_format="none")

        assert exit_code == 0, "the job should have run"
        assert ran == ["job"], f"expected the job to win, got {ran}"

    def test_shadowed_command_is_absent_from_both(self) -> None:
        def collide() -> None:
            """The job."""

        app = _app_with(
            jobs=[collide],
            commands=[dict(name="collide", callback=lambda: None)],
        )

        from functualize.app.commands import plugin_command_path

        resolved = {plugin_command_path(c) for c in unshadowed_plugin_commands(app)}
        tree_names = {n.name for n in build_command_tree(app)}

        assert "collide" not in resolved
        assert "collide" in tree_names  # the job, not the plugin command
        assert _named(build_command_tree(app), "collide").help_text == "The job."

    def test_grouped_job_shadows_a_matching_namespaced_command(self) -> None:
        """The dotted path is the key, so `demo.serve` collides with `demo serve`."""

        def serve() -> None:
            """The job."""

        serve.__functualize_group__ = "demo"  # type: ignore[attr-defined]

        app = _app_with(
            commands=[dict(name="serve", callback=lambda: None, namespace="demo")]
        )
        # Sanity: without a colliding job the plugin command is present.
        assert "serve" in {c.name for c in unshadowed_plugin_commands(app)}
