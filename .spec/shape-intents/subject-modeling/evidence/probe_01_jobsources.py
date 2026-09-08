"""F3/F4 — JobSources(functions=…) and add_job_provider on the standard boot path.

Expected: zero jobs registered, JobNotFoundError on execute, in BOTH cases.
"""
from abc import ABC, abstractmethod

from functualize.app import FunctualizeApp, JobSources
from functualize._discovery.providers import Job, StaticProvider


class Resource(ABC):
    group = ""

    def diagnose(self) -> dict:
        return {"group": self.group}


class Service(Resource):
    @abstractmethod
    def start(self) -> None: ...


class Bifrost(Service):
    group = "apps.bifrost"

    def start(self) -> None:
        """Start."""

    def status(self) -> str:
        """Status."""
        return "ok"


inst = Bifrost()
jobs = [
    Job(function=inst.start, name="start", group=inst.group),
    Job(function=inst.status, name="status", group=inst.group),
]

# --- A: JobSources(functions=...) with anything else non-explicit
app = FunctualizeApp("probe1", job_sources=JobSources(functions=jobs, lazy=False))
print("A. static_wiring fast path taken:", app._static_wiring)
print("A. registered jobs:", [d.name for d in app.get_jobs()])
try:
    app.execute("apps.bifrost.status")
    print("A. execute: SUCCEEDED (unexpected)")
except Exception as e:
    print("A. execute:", type(e).__name__, e)

# --- B: add_job_provider after boot
app2 = FunctualizeApp("probe1b", job_sources=JobSources(directories=[], lazy=False))
app2.add_job_provider(StaticProvider(jobs))
print("B. registered jobs after add_job_provider:", [d.name for d in app2.get_jobs()])
try:
    app2.execute("apps.bifrost.status")
    print("B. execute: SUCCEEDED (unexpected)")
except Exception as e:
    print("B. execute:", type(e).__name__, e)

# --- C: the field that is never read
import functualize
import subprocess, pathlib
root = pathlib.Path(functualize.__file__).parent
hits = subprocess.run(["grep", "-rn", "job_providers", str(root)],
                      capture_output=True, text=True).stdout.strip().splitlines()
print("C. job_providers references in the package:", len(hits))
for h in hits:
    print("   ", h.split("/")[-1])
