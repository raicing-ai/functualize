"""Probe 16: the workflow gate is the AI seam — both directions.

Part A: a Gate(strategy="ai_outbound") blocks the walk, publishes its
        awaits-model schema, and is resumable by depositing a payload.
Part B: a custom resolver registered under the reserved name "ai_inbound"
        resolves the same gate in-process, with no block.
"""

from pydantic import BaseModel

from functualize.app import FunctualizeApp, JobSources, PluginSources
from functualize._discovery.providers import StaticProvider, Job
from functualize.job import job
from functualize.workflow import workflow
from functualize._types.workflow import Step, Gate, Edge, END


class Triage(BaseModel):
    """What the intelligent step must decide."""

    severity: str
    owner: str
    rationale: str


@job
def collect(log=None) -> None:
    """Deterministic: gather the facts."""
    print("  [collect] ran")


@job
def apply_label() -> None:
    """Deterministic: act on the decision."""
    print("  [apply_label] ran")


@workflow(
    steps=[
        Step(collect),
        Gate(name="triage", awaits=Triage, tools=[collect], strategy="ai_outbound"),
        Step(apply_label),
    ],
    edges=[
        Edge("collect", "triage"),
        Edge("triage", "apply_label"),
        Edge("apply_label", END),
    ],
)
def triage_issue() -> None:
    """Epilogue: runs when the walk reaches END."""
    print("  [epilogue] ran")


class P:
    name = "p"
    version = "0"
    description = "probe"

    def __call__(self, app):
        app.add_job_provider(
            StaticProvider(
                [
                    Job(function=collect, name="collect"),
                    Job(function=apply_label, name="apply_label"),
                    Job(function=triage_issue, name="triage_issue"),
                ]
            )
        )


def build():
    return FunctualizeApp(
        "p",
        job_sources=JobSources(directories=[], lazy=False),
        plugin_sources=PluginSources(explicit_plugins=[P()]),
    )


print("=== declaration ===")
decl = triage_issue.__functualize_workflow__
for n in decl.nodes:
    kind = type(n).__name__
    extra = ""
    if kind == "Gate":
        extra = f" strategy={n.strategy!r} tools={[t.name for t in n.tool_specs()]}"
    print(f"  {kind:5} {n.name}{extra}")

print("\n=== the schema published at the gate (what an agent is handed) ===")
gate = decl.node("triage")
print(" ", gate.awaits.model_json_schema())

print("\n=== A: ai_outbound — run the workflow ===")
app = build()
res = app.execute("triage_issue")
print("  status:", res.status)
md = res.metadata or {}
for k in sorted(md):
    print(f"  {k}: {md[k]}")

print("\n=== B: ai_inbound — a registered resolver answers in-process ===")


class FakeLLM:
    """Whatever calls a model. The Protocol is one method."""

    def resolve(self, ctx):
        print("    [ai_inbound] asked for:", ctx.unresolved_fields)
        return ctx.model_class(
            severity="high", owner="platform", rationale="stack trace names the router"
        )


app2 = build()
app2.register_gate_strategy("ai_inbound", FakeLLM())
model = app2.resolve_gate(Triage, gate_strategy="ai_inbound", gate_name="triage")
print("  resolved:", model)
print("\n=== B2: the ladder — ai_inbound absent, falls through to resolve ===")
class Defaulted(BaseModel):
    severity: str = "low"
    owner: str = "unassigned"
    rationale: str = "no model configured"
app3 = build()
print("  resolved:", app3.resolve_gate(Defaulted, gate_name="triage"))
