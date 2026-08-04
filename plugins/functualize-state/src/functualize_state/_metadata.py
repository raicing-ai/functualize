"""Domain metadata for the State SDK."""

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
    name="state",
    display_name="State / Persistence",
    description="State persistence and execution tracking",
    capability_class="functualize_state.StateBackend",
    provider_protocol="functualize_state.StateBackend",
    config_section="state",
    entry_point_group="functualize.state_providers",
    events_prefix="state.",
    scaffold_template=None,
    documentation_url=None,
    mock_factory="functualize_state.testing:InMemoryState",
)
