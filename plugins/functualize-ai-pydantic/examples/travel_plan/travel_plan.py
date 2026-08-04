"""AI job against the real PydanticAI provider (requires an API key).

With functualize-ai-pydantic installed, the framework injects the `AI`
capability into any job that declares an `ai: AI` parameter — the sole
installed provider is auto-selected, no config needed.

Run with:
    export OPENAI_API_KEY=sk-...          # or ANTHROPIC_API_KEY
    func travel_plan.py run --city Tokyo
"""

from functualize_ai import AI
from pydantic import BaseModel, Field

from functualize.job import RunContext


class PlanConfig(BaseModel):
    """Configuration for the travel plan job."""

    city: str = Field(description="Destination city")
    days: int = Field(default=3, ge=1, le=14, description="Trip length in days")


class TravelPlan(BaseModel):
    """Structured output the LLM must produce."""

    destination: str
    best_days: list[str]
    packing_tips: list[str]


def run(config: PlanConfig, ai: AI, rc: RunContext) -> TravelPlan:
    """Generate a structured travel plan with a real LLM."""
    rc.log(f"Planning {config.days} days in {config.city}...")
    plan = ai.complete(
        f"Create a {config.days}-day travel plan for {config.city}.",
        response_model=TravelPlan,
    )
    rc.log(f"Best days: {', '.join(plan.best_days)}")
    rc.log(f"Pack: {', '.join(plan.packing_tips)}")
    return plan
