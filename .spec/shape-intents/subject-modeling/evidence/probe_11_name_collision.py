"""03 §3 — StaticProvider keys jobs by NAME ALONE, not group.name.

Two classes sharing a method name collide, and the failure is total: the
resolution pipeline raises and EVERY job from that boot is lost, not just the
colliding pair. The fix is to pass the fully-qualified name as Job(name=...).
"""

from click.testing import CliRunner

from functualize._discovery.providers import Job, StaticProvider
from functualize.app import FunctualizeApp, JobSources, PluginSources
from functualize.app.adapters.cli import CliAdapter
from functualize.job import Log


class Alpha:
    group = "apps.alpha"

    def install(self, log: Log) -> None:
        """Install alpha."""
        log("alpha")


class Beta:
    group = "apps.beta"

    def install(self, log: Log) -> None:
        """Install beta."""
        log("beta")


def build(qualified: bool):
    class P:
        name = "rise"
        version = "0.1.0"
        description = "rise"

        def __call__(self, app) -> None:
            jobs = []
            for cls in (Alpha, Beta):
                inst = cls()
                nm = f"{inst.group}.install" if qualified else "install"
                jobs.append(Job(function=inst.install, name=nm, group=inst.group))
            app.add_job_provider(StaticProvider(jobs))

    return FunctualizeApp(
        "rise",
        job_sources=JobSources(directories=[], lazy=False),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[P()]),
    )


for label, qualified in (("bare name  ", False), ("qualified  ", True)):
    app = build(qualified)
    a = CliAdapter()
    a(app)
    codes = [
        CliRunner().invoke(a.cli_command, p).exit_code
        for p in (["apps", "alpha", "install"], ["apps", "beta", "install"])
    ]
    print(f"{label} jobs={sorted(d.name for d in app.get_jobs())} exits={codes}")
