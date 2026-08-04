"""Domain metadata for the AI SDK."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainMetadata:
    """Self-describing metadata for a domain SDK."""

    name: str
    display_name: str
    description: str
    capability_class: str
    provider_protocol: str
    config_section: str
    entry_point_group: str
    events_prefix: str
    scaffold_template: str | None = None
    documentation_url: str | None = None
    mock_factory: str | None = None


domain_metadata = DomainMetadata(
    name="ai",
    display_name="AI / LLM",
    description="LLM interaction capabilities",
    capability_class="functualize_ai.AI",
    provider_protocol="functualize_ai.AIProvider",
    config_section="ai",
    entry_point_group="functualize.ai_providers",
    events_prefix="ai.",
    scaffold_template=None,
    documentation_url=None,
    mock_factory="functualize_ai.testing:MockAI",
)
