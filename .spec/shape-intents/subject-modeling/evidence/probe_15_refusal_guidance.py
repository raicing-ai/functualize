"""Probe: does a Precondition msg reach the operator/agent on REFUSED?"""
from functualize.app import FunctualizeApp, JobSources, PluginSources
from functualize.job import job
from functualize._types.job_declaration import Guards, Precondition
from functualize._discovery.providers import StaticProvider, Job

@job(guards=Guards(preconditions=[Precondition("test -f /nonexistent-xyz",
     "Postgres is not initialised. Read the pgops skill, section 'first run', then run `func pg init`.")]))
def backup() -> None:
    """Back up the database."""

class P:
    name="p"; version="0"; description="p"
    def __call__(self, app): app.add_job_provider(StaticProvider([Job(function=backup, name="backup")]))

app = FunctualizeApp("p", job_sources=JobSources(directories=[], lazy=False),
                     plugin_sources=PluginSources(explicit_plugins=[P()]))
import sys
from functualize._cli.main import *
res = app.execute("backup")
print("status:", res.status if hasattr(res,'status') else res)
print(repr(res)[:600])
