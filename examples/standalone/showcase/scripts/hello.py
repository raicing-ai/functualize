#!/usr/bin/env python3
"""Minimal standalone job — run with: func hello.py greet --name World"""

from pydantic import BaseModel, Field

from functualize.job.context import RunContext
from functualize.job.decorators import job


class GreetConfig(BaseModel):
    """Configuration for the greet job."""

    name: str = Field(description="Name of the person to greet")
    enthusiasm: int = Field(default=1, ge=1, le=5, description="Enthusiasm level (1-5)")


@job(
    extra_description="Greet a person with configurable enthusiasm",
    tags=["demo", "safe"],
    visibility="external",
)
def greet(config: GreetConfig, rc: RunContext) -> str:
    """Greet someone — the simplest functualize job."""
    exclamation = "!" * config.enthusiasm
    message = f"Hello, {config.name}{exclamation}"
    rc.log(message)
    return message
