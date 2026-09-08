"""Probe 17: what a gate actually falls back to.

Q1: is `ai_inbound` "just a normal gate"?
Q2: does `ai_outbound` fall back to a regular gate when no AI provider exists?

Cases:
  A  strategy="ai_outbound"                      (no AI installed)
  B  strategy="ai_inbound"                       (no AI installed -> unregistered)
  C  strategy="ai_inbound", resolver registered but raising (no provider)
  D  strategy=None                               (the default)
  E  preset "ai" via the imperative resolve_gate path
"""

from pydantic import BaseModel

from functualize.app import FunctualizeApp, JobSources, PluginSources
from functualize._discovery.providers import StaticProvider, Job
from functualize.job import job
from functualize.workflow import workflow, Step, Gate, Edge, END


class Triage(BaseModel):
    severity: str
    owner: str


@job
def collect() -> None:
    """Deterministic."""


@job
def apply_label() -> None:
    """Deterministic."""


def make(strategy):
    @workflow(
        steps=[
            Step(collect),
            Gate(name="triage", awaits=Triage, strategy=strategy),
            Step(apply_label),
        ],
        edges=[
            Edge("collect", "triage"),
            Edge("triage", "apply-label"),
            Edge("apply-label", END),
        ],
    )
    def wf() -> None:
        """Epilogue."""

    return wf


def build(wf, name):
    class P:
        name_ = "p"
        version = "0"
        description = "p"
        name = "p"

        def __call__(self, app):
            app.add_job_provider(
                StaticProvider(
                    [
                        Job(function=collect, name="collect"),
                        Job(function=apply_label, name="apply-label"),
                        Job(function=wf, name=name),
                    ]
                )
            )

    return FunctualizeApp(
        "p",
        job_sources=JobSources(directories=[], lazy=False),
        plugin_sources=PluginSources(explicit_plugins=[P()]),
    )


def run(label, strategy):
    wf = make(strategy)
    app = build(wf, "wf")
    print(f"\n--- {label}: strategy={strategy!r} ---")
    try:
        res = app.execute("wf")
        print("   status:", res.status)
        md = res.metadata or {}
        for k in ("blocked_on", "workflow_status"):
            if k in md:
                print(f"   {k}: {md[k]}")
    except Exception as exc:
        print(f"   RAISED {type(exc).__name__}: {exc}")


run("A  ai_outbound, nothing installed", "ai_outbound")
run("B  ai_inbound, nothing installed", "ai_inbound")
run("D  default", None)

print("\n--- C: ai_inbound registered but failing (no provider) ---")


class NoProvider:
    def resolve(self, ctx):
        raise RuntimeError("No AI capability is available.")


wf = make("ai_inbound")
app = build(wf, "wf")
app.register_gate_strategy("ai_inbound", NoProvider())
res = app.execute("wf")
print("   status:", res.status)
print("   blocked_on:", (res.metadata or {}).get("blocked_on"))

print("\n--- E: the 'ai' preset through the imperative path ---")
app2 = build(make(None), "wf")
app2.register_gate_preset("ai", ["ai_outbound", "ai_inbound", "prompt", "resolve"])
try:
    print("   ->", app2.resolve_gate(Triage, gate_strategy="ai", gate_name="triage"))
except Exception as exc:
    print(f"   RAISED {type(exc).__name__}: {exc}")

print("\n--- F: is 'ai' even accepted as a Gate strategy? ---")
try:
    Gate(name="g", awaits=Triage, strategy="ai")
    print("   accepted")
except Exception as exc:
    print(f"   RAISED {type(exc).__name__}: {exc}")
