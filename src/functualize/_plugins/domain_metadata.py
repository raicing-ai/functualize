"""Centralized DomainMetadata dataclass for domain SDK self-description.

Each Domain SDK package provides a `domain_metadata` instance of this dataclass,
registered via the ``functualize.domains`` entry point group. The core discovery
system loads these at FunctualizeApp boot to build the internal domain registry.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainMetadata:
    """Self-describing metadata for a domain SDK.

    Attributes:
        name: Short identifier for the domain (e.g., "ai", "state").
        display_name: Human-friendly name (e.g., "AI / LLM").
        description: Brief description of the domain's capabilities.
        capability_class: Fully-qualified path to the domain's capability class.
        provider_protocol: Fully-qualified path to the provider protocol class.
        config_section: Config file section name for this domain.
        entry_point_group: Entry point group name for implementation plugins.
        events_prefix: Prefix for events emitted by this domain (e.g., "ai.").
        scaffold_template: Optional scaffold template name.
        documentation_url: Optional URL to domain documentation.
        mock_factory: Optional fully-qualified path to the testing double factory
            (e.g., "functualize_ai.testing:MockAI").
    """

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
