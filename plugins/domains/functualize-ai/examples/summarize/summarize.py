"""Provider-agnostic AI job: structured summary of a text.

Run with:
    func summarize.py run --text "Functualize is a CLI framework..."

Uses MockAI so it works without API keys; with a provider plugin
installed (e.g. functualize-ai-pydantic) declare `ai: AI` as a job
parameter instead and the framework injects the real provider.
"""

from functualize_ai.testing import MockAI
from pydantic import BaseModel, Field

from functualize.job import RunContext


class SummarizeConfig(BaseModel):
    """Configuration for the summarize job."""

    text: str = Field(description="Text to summarize")
    max_points: int = Field(default=3, ge=1, le=10, description="Bullet points")


class Summary(BaseModel):
    """Structured output the AI must produce."""

    title: str
    bullet_points: list[str]


def run(config: SummarizeConfig, rc: RunContext) -> Summary:
    """Summarize text into structured bullet points."""
    ai = MockAI(
        responses={
            "*Summarize*": Summary(
                title="Summary",
                bullet_points=[f"Point about: {config.text[:40]}"] * config.max_points,
            ),
        }
    )

    summary = ai.complete(
        f"Summarize in {config.max_points} bullet points: {config.text}",
        response_model=Summary,
    )
    for point in summary.bullet_points:
        rc.log(f"• {point}")
    return summary
