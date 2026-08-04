"""AI in both directions — outbound (job calls an LLM) and inbound (LLM drives the job).

- ``ai_write``  — OUTBOUND: the job declares its own AI client and calls
  ``ai.complete()`` with structured output, ``ToolScope`` restrictions, and
  ``AILimits`` budgets.
- ``ai_review`` — INBOUND: the job's config is designed to be resolved by an
  external AI agent (the AI_INBOUND gate strategy); ``visibility="external"``
  exposes it over MCP.

Both use ``MockAI`` from ``functualize_ai.testing`` so they run without API
keys. Tool helper functions are underscore-prefixed so baseline convention
discovery doesn't register them as jobs.

Run: func ai-write --topic "Python async patterns" --style concise
     func ai-review --repo my-org/my-repo --focus security
Dependencies: pip install functualize functualize-ai

Note: no `from __future__ import annotations` here — the CLI's config-class
expansion needs the real annotation objects; string annotations would hide
that a parameter is a BaseModel.
"""

from enum import StrEnum
from typing import Literal

from functualize_ai import AILimits, ToolScope
from functualize_ai.testing import MockAI
from pydantic import BaseModel, Field

from functualize.job.context import RunContext
from functualize.job.decorators import job

# ---------------------------------------------------------------------------
# OUTBOUND: ai_write — the job actively calls an LLM
# ---------------------------------------------------------------------------


class WritingStyle(StrEnum):
    """Supported writing styles."""

    concise = "concise"
    detailed = "detailed"
    tutorial = "tutorial"


class WriteConfig(BaseModel):
    """Configuration for content generation."""

    topic: str = Field(description="Topic to write about")
    style: WritingStyle = Field(
        default=WritingStyle.concise, description="Writing style"
    )
    max_tokens: int = Field(
        default=1000, ge=100, le=4096, description="Max output tokens"
    )


class GeneratedContent(BaseModel):
    """Structured output from the content generator."""

    title: str = Field(description="Generated title")
    content: str = Field(description="Main content body")
    word_count: int = Field(description="Approximate word count")
    tags: list[str] = Field(default_factory=list, description="Suggested tags")


def _search_references(query: str) -> str:
    """Search for reference material on a topic (exposed to the AI as a tool)."""
    return f"Found 3 references for '{query}': [ref1, ref2, ref3]"


def _check_existing_content(topic: str) -> str:
    """Check if similar content already exists (exposed to the AI as a tool)."""
    return f"No existing content found for '{topic}'"


@job(
    extra_description="Generate structured content on a given topic using AI",
    category="content",
    tags=["ai", "writing", "creative"],
    visibility="external",
)
def ai_write(config: WriteConfig, rc: RunContext) -> GeneratedContent:
    """Generate content using the AI capability with tool access and budget limits.

    Demonstrates outbound AI usage: the job actively calls the LLM to produce
    structured content, with ToolScope restrictions and budget controls.
    """
    rc.log(f"Generating {config.style.value} content on: {config.topic}")

    # Set up AI with mock responses (production uses a real provider)
    ai = MockAI(
        responses={
            "*concise*": GeneratedContent(
                title=f"{config.topic} — Quick Guide",
                content=f"A concise overview of {config.topic}...",
                word_count=150,
                tags=["guide", "quick-reference"],
            ),
            "*detailed*": GeneratedContent(
                title=f"Deep Dive: {config.topic}",
                content=f"An in-depth exploration of {config.topic}...",
                word_count=800,
                tags=["deep-dive", "comprehensive"],
            ),
            "*tutorial*": GeneratedContent(
                title=f"Tutorial: {config.topic}",
                content=f"Step-by-step tutorial on {config.topic}...",
                word_count=500,
                tags=["tutorial", "hands-on"],
            ),
            "*": GeneratedContent(
                title=config.topic,
                content=f"Content about {config.topic}...",
                word_count=200,
                tags=["general"],
            ),
        }
    )

    # Define tools the AI can use during generation
    ToolScope.functions([_search_references, _check_existing_content])

    # Run AI with budget limits
    AILimits(
        max_tokens=config.max_tokens,
        max_tool_calls=5,
        timeout_seconds=30,
    )

    # Generate structured content
    result = ai.complete(
        f"Write {config.style.value} content about: {config.topic}",
        response_model=GeneratedContent,
    )

    rc.log(f"Generated: '{result.title}' ({result.word_count} words)")
    rc.log(f"Tags: {', '.join(result.tags)}")
    rc.log(f"AI calls used: {ai.call_count}")

    return result


# ---------------------------------------------------------------------------
# INBOUND: ai_review — an external LLM resolves the config and drives the job
# ---------------------------------------------------------------------------


class ReviewFocus(StrEnum):
    """Areas of focus for a code review."""

    security = "security"
    performance = "performance"
    readability = "readability"
    all = "all"


class ReviewConfig(BaseModel):
    """Configuration for the AI-driven code review job.

    When run via the AI_INBOUND gate strategy, the LLM uses context
    (branch name, recent commits, PR description) to resolve these fields.
    """

    repo: str = Field(description="Repository in org/repo format")
    focus: ReviewFocus = Field(default=ReviewFocus.all, description="Review focus area")
    max_files: int = Field(
        default=20, ge=1, le=100, description="Maximum files to review"
    )
    severity_threshold: Literal["low", "medium", "high"] = Field(
        default="medium", description="Minimum severity to report"
    )


class ReviewResult(BaseModel):
    """Structured review output."""

    repo: str
    files_reviewed: int
    issues_found: int
    critical_issues: list[str]
    summary: str


@job(
    extra_description="Perform an AI-assisted code review on a repository",
    category="code-quality",
    tags=["ai", "review", "safe", "read-only"],
    examples=[
        "ai_review --repo my-org/api --focus security",
        "ai_review --repo my-org/frontend --focus performance --max-files 50",
    ],
    visibility="external",
)
def ai_review(config: ReviewConfig, rc: RunContext) -> ReviewResult:
    """Review a repository using AI analysis.

    This job demonstrates being invoked by an external AI agent via MCP.
    The AI_INBOUND gate strategy can resolve `repo` and `focus` from the
    conversation context without explicit user input.
    """
    rc.log(f"Reviewing {config.repo} (focus: {config.focus.value})")

    # In production, this would use a real AI provider.
    # For standalone execution, we use MockAI for deterministic results.
    ai = MockAI(
        responses={
            "*security*": ReviewResult(
                repo=config.repo,
                files_reviewed=config.max_files,
                issues_found=3,
                critical_issues=["SQL injection in user_handler.py"],
                summary="Found 3 security issues, 1 critical",
            ),
            "*performance*": ReviewResult(
                repo=config.repo,
                files_reviewed=config.max_files,
                issues_found=5,
                critical_issues=[],
                summary="Found 5 performance opportunities, none critical",
            ),
            "*": ReviewResult(
                repo=config.repo,
                files_reviewed=config.max_files,
                issues_found=2,
                critical_issues=[],
                summary="Code looks good overall, 2 minor suggestions",
            ),
        }
    )

    # Use ToolScope to restrict what the AI can do during review
    ToolScope.only(["read-file", "list-directory"])

    result = ai.complete(
        f"Review {config.repo} focusing on {config.focus.value} "
        f"(max {config.max_files} files, threshold: {config.severity_threshold})",
        response_model=ReviewResult,
    )

    rc.log(f"Review complete: {result.issues_found} issues found")
    if result.critical_issues:
        for issue in result.critical_issues:
            rc.log(f"  CRITICAL: {issue}")

    return result
