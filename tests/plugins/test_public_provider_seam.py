"""A plugin can build a job provider from public imports alone.

The documented way to contribute jobs is to hand functualize a *job provider*.
`JobProvider` (the protocol), `JobDescriptor` (what its methods return) and
`Job` (the wrapper that names and groups a callable) were all public — but
`StaticProvider`, the only thing that turns `Job`s into a working provider,
was not. So the public `Job` had no public consumer, and the documented route
ran through `functualize._discovery`, which the docs for that very area tell
you not to import.

Hand-rolling the two methods was possible and quietly lossy: the author then
fills in each job's arguments, and the helper that does it correctly — skips
`self`, excludes injected capabilities, understands the argument markers — is
also private. Hand-roll without it and the jobs publish as taking no
arguments, which is the defect this project had just fixed on the
dynamic-registration door.

Every import below is public, deliberately: that is the property under test,
and it is why these assertions are not simply duplicating the provider's own
unit tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import functualize.plugin as plugin_module
from functualize import FunctualizeApp
from functualize.app.config import JobSources, PluginSources
from functualize.plugin import Job, JobProvider, StaticProvider

if TYPE_CHECKING:
    from functualize.job import Log


class Jsonschema:
    """A subject class of the shape the Subjects guide describes."""

    group = "tools.jsonschema"

    def install(self, force: bool = False) -> None:
        """Install the tool."""

    def run(self, args: str, log: Log) -> None:
        """Run the tool."""


class _ProviderPlugin:
    """The real seam: a plugin that adds a provider while it is being loaded.

    Not `app.extensions.add_job_provider(...)` after construction — plugins load at boot
    step 4 and job resolution happens at step 9, so a provider added after the
    constructor returns has already missed the registration it needs. The
    plugin call is the documented route, and it is the one a framework built
    on functualize actually uses.
    """

    name = "provider-plugin"
    version = "1.0.0"
    description = "Adds a job provider during plugin load."

    def __init__(self, provider: JobProvider) -> None:
        self._provider = provider

    def __call__(self, app: FunctualizeApp) -> None:
        app.extensions.add_job_provider(self._provider)


def _app_with(provider: JobProvider) -> FunctualizeApp:
    return FunctualizeApp(
        "host",
        job_sources=JobSources(directories=[], functions=[]),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[_ProviderPlugin(provider)]
        ),
    )


class TestTheExport:
    def test_it_is_importable_from_the_public_module(self) -> None:
        """A1."""
        assert StaticProvider is not None

    def test_it_is_declared_public(self) -> None:
        """A2. Importable but absent from `__all__` is a different promise —
        it reads as an accident a later cleanup may withdraw."""
        assert "StaticProvider" in plugin_module.__all__

    def test_it_satisfies_the_public_protocol(self) -> None:
        """The protocol was already public; this pins that the thing now
        exported beside it actually implements it."""
        assert isinstance(StaticProvider([]), JobProvider)


class TestBuildingAProviderFromPublicImportsOnly:
    def test_bound_methods_become_jobs_with_their_arguments(self) -> None:
        """A3, A4 — the property that made the private import load-bearing.

        `self` must not appear as a CLI argument, and an injected capability
        (`log: Log`) must not either, while a real parameter must survive. A
        hand-rolled provider gets this wrong by omission and publishes jobs
        that take nothing.
        """
        obj = Jsonschema()
        provider = StaticProvider(
            [
                Job(function=obj.install, name="install", group=obj.group),
                Job(function=obj.run, name="run", group=obj.group),
            ]
        )

        by_name = {d.name: d for d in provider.list_jobs()}

        assert [p.name for p in by_name["install"].parameters] == ["force"]
        assert [p.name for p in by_name["run"].parameters] == ["args"]

    def test_the_jobs_reach_an_app_through_the_documented_seam(self) -> None:
        """A3 end to end: `add_job_provider` is the documented route, and the
        parameters have to survive registration, not just extraction."""
        obj = Jsonschema()
        app = _app_with(
            StaticProvider(
                [
                    Job(function=obj.install, name="install", group=obj.group),
                    Job(function=obj.run, name="run", group=obj.group),
                ]
            )
        )

        registered = {d.name: d for d in app.get_jobs()}

        assert set(registered) == {"install", "run"}
        assert [p.name for p in registered["install"].parameters] == ["force"]

    def test_a_plain_callable_works_too(self) -> None:
        """`Job` is for naming and grouping; a bare function needs neither."""

        def standalone(rows: int = 3) -> None:
            """A job."""

        app = _app_with(StaticProvider([standalone]))

        (descriptor,) = app.get_jobs()
        assert descriptor.name == "standalone"
        assert [p.name for p in descriptor.parameters] == ["rows"]

    def test_the_group_is_carried(self) -> None:
        """One class binding as one group is the shape the guide teaches."""
        obj = Jsonschema()
        provider = StaticProvider(
            [Job(function=obj.install, name="install", group=obj.group)]
        )

        (descriptor,) = provider.list_jobs()

        assert descriptor.group == "tools.jsonschema"
