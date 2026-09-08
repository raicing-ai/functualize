"""Core binding claim + F1 correction.

Establishes:
  0. the abstract-method gate fires at instantiation (registration time);
  1. bound methods register as jobs, with `self` skipped and capabilities excluded;
  2. `@job(guards=Guards(status=...))` on a METHOD is honoured by the executor;
  3. a second `install` is SKIPPED (exit 0), NOT refused (exit 3).
"""
from abc import ABC, abstractmethod

from functualize.app import FunctualizeApp, JobSources
from functualize._discovery.providers import Job, StaticProvider
from functualize.job import Guards, Log, job

STATE = {"installed": False}


class Resource(ABC):
    group = ""

    def diagnose(self) -> dict:
        return {"kind": type(self).__mro__[1].__name__, "group": self.group}


class Program(Resource):
    @abstractmethod
    def install(self) -> None: ...


class Broken(Program):
    group = "apps.broken"


try:
    Broken()
    print("0. abstract gate: NOT enforced (unexpected)")
except TypeError as e:
    print("0. abstract gate enforced:", e)


class Tool(Program):
    group = "apps.tool"

    @job(guards=Guards(status=[lambda cfg=None: STATE["installed"]]))
    def install(self, log: Log, variant: str = "pip", force: bool = False) -> None:
        """Install the tool."""
        STATE["installed"] = True
        log(f"installed via {variant}")

    def status(self) -> str:
        """Report status."""
        return "installed" if STATE["installed"] else "absent"


inst = Tool()

# 1. descriptor shape straight off a bound method
d = StaticProvider([Job(function=inst.install, name="install", group=inst.group)]).list_jobs()[0]
print("1. StaticProvider params:", [(p.name, p.type_annotation, p.required, p.default) for p in d.parameters])

app = FunctualizeApp("probe3", job_sources=JobSources(directories=[], lazy=False))
for m in ("install", "status", "diagnose"):
    app.register_dynamic_job(name=f"{inst.group}.{m}", function=getattr(inst, m), group=inst.group)

print("2. status  ->", app.execute("apps.tool.status").status)
print("3. install#1 ->", app.execute("apps.tool.install").status)
print("4. install#2 ->", app.execute("apps.tool.install").status, "  (SKIPPED == exit 0)")
print("5. why:")
for line in app.explain("apps.tool.install").splitlines()[:3]:
    print("     ", line)
