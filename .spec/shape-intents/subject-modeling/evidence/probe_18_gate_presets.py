"""Probe 18: the two reachable paths for ai_outbound, and the preset ladder."""
from pydantic import BaseModel
from functualize.app import FunctualizeApp, JobSources

class Triage(BaseModel):
    severity: str
    owner: str

app = FunctualizeApp("p", job_sources=JobSources(directories=[], lazy=False))

print("registered strategies at boot:", sorted(app._gate_registry._strategies))
print("registered presets at boot:   ", sorted(app._gate_registry._presets))

# What functualize-mcp registers
class AIOutboundLike:
    def resolve(self, ctx):
        raise ValueError(
            f"ai_outbound: Gate '{ctx.model_class.__name__}' awaits external "
            "AI input via MCP. Use the resume_workflow tool to provide input.")
app.register_gate_strategy("ai_outbound", AIOutboundLike())
app.register_gate_preset("ai_outbound", ["ai_outbound", "prompt", "resolve"])

# What functualize-ai registers
class AIInboundLike:
    def resolve(self, ctx):
        return ctx.model_class(severity="high", owner="platform")
app.register_gate_strategy("ai_inbound", AIInboundLike())
app.register_gate_preset("ai_inbound", ["ai_inbound", "prompt", "resolve"])
app.register_gate_preset("ai", ["ai_outbound", "ai_inbound", "prompt", "resolve"])

print("\npreset 'ai'      ->", app.resolve_gate(Triage, gate_strategy="ai", gate_name="g"))
print("preset 'ai_inbound' ->", app.resolve_gate(Triage, gate_strategy="ai_inbound", gate_name="g"))
try:
    app.resolve_gate(Triage, gate_strategy="ai_outbound", gate_name="g")
except Exception as e:
    print("preset 'ai_outbound' ->", type(e).__name__+":", str(e)[:110])
