"""Domain metadata for the Tasks SDK."""

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
    name="tasks",
    display_name="Tasks",
    description="Task management and planning scratchpad",
    capability_class="functualize_tasks.Tasks",
    provider_protocol="functualize_tasks.TaskProvider",
    config_section="tasks",
    entry_point_group="functualize.tasks_providers",
    events_prefix="tasks.",
    scaffold_template=None,
    documentation_url=None,
    mock_factory="functualize_tasks.testing:MockTasks",
)
