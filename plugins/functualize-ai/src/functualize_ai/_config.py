"""AI configuration model for the AI Domain SDK."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AIConfig(BaseModel):
    """Configuration for the AI domain, read from [ai] config section."""

    provider: str = "pydantic"
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = Field(default=4096, gt=0)
    budget_usd: float | None = Field(default=None, gt=0)
    timeout_seconds: int | None = Field(default=120, gt=0)
