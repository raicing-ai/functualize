"""One collision, one answer, on every path that can reach the app.

Before this, a job and a top-level plugin command sharing a name resolved three
different ways:

  * `func collide`        -> the job won, the plugin command dropped silently
  * `app.cli_command`     -> the *plugin* won, silently, because __call__
                             registers jobs before plugins and click's
                             add_command overwrites by name
  * `CliAdapter.run()`    -> ValueError

`app.cli_command` is a documented public access path, so the middle one was not
an edge case; it was the ordinary way an embedded app reached its own CLI, and
it did the opposite of what the CLI did.
"""

from __future__ import annotations

import pytest

from functualize.app import FunctualizeApp
from functualize.app.adapters.cli import (
    CliAdapter,
    check_name_conflicts,
    shadowed_plugin_commands,
)
from functualize.app.commands import build_command_tree, unshadowed_plugin_commands
from functualize.app.config import JobSources, PluginSources


def _app(*, jobs=(), commands=()):
    app = FunctualizeApp(
        name="t",
        job_sources=JobSources(functions=list(jobs) or None),
        plugin_sources=PluginSources(entry_point_group="functualize.plugins.__none__"),
    )
    for kwargs in commands:
        app.register_plugin_command(**kwargs)
    return app


def _collision_app():
    def collide() -> None:
        """The job."""

    return _app(
        jobs=[collide],
        commands=[dict(name="collide", callback=lambda: None, help_text="The plugin")],
    )


class TestTheJobWinsEverywhere:
    def test_on_the_cli_command_group(self) -> None:
        """The regression: click's add_command used to overwrite the job."""
        app = _collision_app()
        command = app.cli_command.commands["collide"]
        assert "The job." in (command.help or "")
        assert "The plugin" not in (command.help or "")

    def test_in_the_command_tree(self) -> None:
        app = _collision_app()
        node = next(n for n in build_command_tree(app) if n.name == "collide")
        assert node.help_text == "The job."

    def test_in_the_shadow_resolver(self) -> None:
        app = _collision_app()
        assert "collide" not in {c.name for c in unshadowed_plugin_commands(app)}


class TestNamespacedCollisions:
    def test_a_namespaced_command_is_checked(self) -> None:
        """`check_name_conflicts` used to inspect only `namespace is None`, so a
        job at `demo.serve` colliding with `func demo serve` went unchecked
        here while `_dispatch_group` checked exactly that case."""

        class _Job:
            name = "demo.serve"
            group = "demo"
            docstring = "The job."

        app = _app(
            commands=[dict(name="serve", callback=lambda: None, namespace="demo")]
        )
        app.get_jobs = lambda: [_Job()]  # type: ignore[method-assign]

        assert shadowed_plugin_commands(app) == [("demo.serve", "serve")]

    def test_a_namespaced_command_does_not_collide_with_a_bare_job(self) -> None:
        """Pre-existing behaviour: `func demo serve` and a job `serve` differ."""

        def serve() -> None:
            """A top-level job."""

        app = _app(
            jobs=[serve],
            commands=[dict(name="serve", callback=lambda: None, namespace="demo")],
        )
        assert shadowed_plugin_commands(app) == []


class TestHardStopStillAvailable:
    def test_run_raises_and_names_both_sides(self) -> None:
        """`CliAdapter.run()` keeps its hard stop for the caller who wants one.

        Stricter than the other paths on purpose: the others prefer the job and
        carry on, which is right for a listing. A caller invoking run() is
        starting a program and can reasonably refuse to start misconfigured.
        """
        app = _collision_app()
        adapter = CliAdapter()
        adapter(app)

        with pytest.raises(ValueError, match="collide"):
            adapter.run()

    def test_no_conflict_means_no_raise(self) -> None:
        def other() -> None:
            """A job."""

        app = _app(
            jobs=[other],
            commands=[dict(name="serve", callback=lambda: None, namespace="demo")],
        )
        check_name_conflicts(app)  # must not raise


class TestTheShadowIsVisible:
    def test_boot_warns_rather_than_staying_silent(self, caplog) -> None:
        """It was a logger.debug inside group dispatch — i.e. invisible, which
        is how three surfaces drifted without anyone noticing.

        Registered through a plugin rather than by calling
        ``register_plugin_command`` on a built app, because that is when it
        actually happens: a plugin's ``__call__`` runs during boot, before the
        validation step that emits this warning. A command registered
        afterwards is an embedding/test path and boot has already been and
        gone.
        """
        import logging

        class _CollidingPlugin:
            name = "colliding"
            version = "0.0.1"
            description = "Registers a command that collides with a job"

            def __call__(self, app) -> None:
                app.register_plugin_command(
                    "collide", lambda: None, help_text="The plugin"
                )

        def collide() -> None:
            """The job."""

        with caplog.at_level(logging.WARNING):
            app = FunctualizeApp(
                name="t",
                job_sources=JobSources(functions=[collide]),
                plugin_sources=PluginSources(
                    entry_point_group="functualize.plugins.__none__",
                    explicit_plugins=[_CollidingPlugin()],
                ),
            )
            app.get_jobs()

        messages = [r.getMessage() for r in caplog.records]
        assert any("unreachable" in m for m in messages), (
            f"no warning about the shadowed command; got {messages}"
        )
        assert any("collide" in m for m in messages)

    def test_no_warning_when_nothing_is_shadowed(self, caplog) -> None:
        import logging

        def other() -> None:
            """A job."""

        with caplog.at_level(logging.WARNING):
            app = _app(
                jobs=[other],
                commands=[dict(name="serve", callback=lambda: None, namespace="demo")],
            )
            app.get_jobs()

        assert not [r for r in caplog.records if "unreachable" in r.getMessage()]
