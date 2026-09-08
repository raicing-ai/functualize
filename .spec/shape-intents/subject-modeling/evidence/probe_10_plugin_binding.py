"""03 §2 — the PLUGIN path: a plugin's add_job_provider reaches the registry,
and descriptor parameters survive (which register_dynamic_job loses).

Plugins load at boot step 4, *before* job resolution (_app/boot.py:535 vs :988),
so a provider added from inside plugin.__call__(app) is picked up. The same call
made after the constructor returns is too late — see probe_01.
"""

import json

from click.testing import CliRunner

from functualize._discovery.providers import Job, StaticProvider
from functualize.app import FunctualizeApp, JobSources, PluginSources
from functualize.app.adapters.cli import CliAdapter
from functualize.job import Log


class Tool:
    group = "apps.tool"

    def install(self, log: Log, variant: str = "pip", force: bool = False) -> None:
        """Install the tool."""
        log(f"{variant} {force}")

    def status(self) -> str:
        """Status."""
        return "ok"


class RisePlugin:
    name = "rise"
    version = "0.1.0"
    description = "rise module binding"

    def __call__(self, app) -> None:
        inst = Tool()
        app.add_job_provider(
            StaticProvider(
                [
                    Job(function=getattr(inst, m), name=f"{inst.group}.{m}", group=inst.group)
                    for m in ("install", "status")
                ]
            )
        )


app = FunctualizeApp(
    "rise",
    job_sources=JobSources(directories=[], lazy=False),
    plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[RisePlugin()]),
)
print("registered:", [(d.name, [p.name for p in d.parameters]) for d in app.get_jobs()])

a = CliAdapter()
a(app)
r = CliRunner()
print("run:", r.invoke(a.cli_command, ["apps", "tool", "install", "--variant", "brew"]).exit_code)
out = r.invoke(a.cli_command, ["builtin", "info", "schema", "apps.tool.install"]).output
props = sorted(json.loads(out).get("inputSchema", {}).get("properties", {}))
print("info schema properties:", props, "  <- non-empty WITHOUT the P1 patch")
