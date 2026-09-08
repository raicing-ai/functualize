"""Probe: does a @job declaration (tags/extra_description) survive a plugin-provided
StaticProvider job, and does it reach the agent-facing info surfaces?"""
from functualize.app import FunctualizeApp, JobSources, PluginSources
from functualize.job import job
from functualize._discovery.providers import StaticProvider, Job

@job(group="demo", tags=("scrill:pgops",), extra_description="see the pgops skill",
     examples=["func demo backup --to /tmp"])
def backup(to: str = "/tmp") -> None:
    """Back up the database."""

class P:
    name = "probe"; version = "0"; description = "probe plugin"
    def __call__(self, app):
        app.add_job_provider(StaticProvider([Job(function=backup, name="demo.backup", group="demo")]))

app = FunctualizeApp("p", job_sources=JobSources(directories=[], lazy=False),
                     plugin_sources=PluginSources(explicit_plugins=[P()]))

descs = list(app.get_jobs())
print("jobs:", [d.name for d in descs])
d = descs[0]
print("declaration present:", d.declaration is not None)
if d.declaration:
    print("  tags:", d.declaration.tags)
    print("  extra_description:", d.declaration.extra_description)
    print("  examples:", d.declaration.examples)
print("params:", [p.name for p in d.parameters])

from functualize._cli.info import job_detail, job_catalog
det = job_detail(app, d.name)
print("job_detail keys:", sorted(det.keys()) if det else None)
print("job_detail exposes tags?", "tags" in (det or {}))
print("inputSchema:", (det or {}).get("inputSchema"))
