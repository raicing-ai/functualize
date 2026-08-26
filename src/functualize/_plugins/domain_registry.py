"""Domain SDK discovery and registry system.

Discovers installed Domain SDKs via the ``functualize.domains`` entry point group
at FunctualizeApp boot time. For each domain, loads the DomainMetadata instance,
scans the domain's ``entry_point_group`` for available implementation plugins,
and supports auto-selection of a single installed implementation.

Boot-time integration:
    1. ``discover_domains()`` scans the ``functualize.domains`` entry point group.
    2. Each entry point loads to a ``DomainMetadata`` instance.
    3. ``DomainRegistry`` stores all discovered domains and their available providers.
    4. ``boot_domain_registry()`` records the active provider (config or auto-select)
       as reporting-only state consumed by ``func domains list``.

The registry is deliberately reporting-only: it observes what is installed and which
provider boot selected, but does not itself activate or load providers.
"""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass, field
from typing import Any

from functualize._plugins.domain_metadata import DomainMetadata
from functualize._primitives.entry_points import entry_points

logger = logging.getLogger(__name__)

DOMAINS_ENTRY_POINT_GROUP = "functualize.domains"


@dataclass
class DomainInfo:
    """Information about a discovered domain and its available providers.

    Attributes:
        metadata: The DomainMetadata instance for this domain.
        available_providers: Mapping of provider name → entry point.
        active_provider_name: The name of the selected/active provider, or None.
    """

    metadata: DomainMetadata
    available_providers: dict[str, importlib.metadata.EntryPoint] = field(
        default_factory=dict
    )
    active_provider_name: str | None = None


class DomainRegistry:
    """Registry of discovered domain SDKs and their available providers.

    This is populated at boot time by scanning entry points. It provides
    read access to domain metadata, provider discovery results, and
    provider selection logic.
    """

    def __init__(self) -> None:
        self._domains: dict[str, DomainInfo] = {}

    @property
    def domains(self) -> dict[str, DomainInfo]:
        """Return all registered domains."""
        return dict(self._domains)

    def register(self, metadata: DomainMetadata) -> None:
        """Register a domain in the registry.

        Args:
            metadata: The DomainMetadata instance describing the domain.
        """
        if metadata.name in self._domains:
            logger.warning(
                f"Domain '{metadata.name}' already registered, skipping duplicate."
            )
            return
        self._domains[metadata.name] = DomainInfo(metadata=metadata)

    def get(self, name: str) -> DomainInfo | None:
        """Get domain info by name.

        Args:
            name: The domain name (e.g., "ai", "state").

        Returns:
            DomainInfo if found, None otherwise.
        """
        return self._domains.get(name)

    def get_metadata(self, name: str) -> DomainMetadata | None:
        """Get domain metadata by name.

        Args:
            name: The domain name.

        Returns:
            DomainMetadata if found, None otherwise.
        """
        info = self._domains.get(name)
        return info.metadata if info else None

    def set_available_providers(
        self, domain_name: str, providers: dict[str, importlib.metadata.EntryPoint]
    ) -> None:
        """Set the available providers for a domain.

        Args:
            domain_name: The domain name.
            providers: Mapping of provider name → entry point.
        """
        info = self._domains.get(domain_name)
        if info is None:
            logger.warning(f"Cannot set providers for unknown domain '{domain_name}'.")
            return
        info.available_providers = providers

    def set_active_provider(self, domain_name: str, provider_name: str) -> None:
        """Set the active provider for a domain.

        Args:
            domain_name: The domain name.
            provider_name: The name of the provider to set as active.
        """
        info = self._domains.get(domain_name)
        if info is None:
            return
        info.active_provider_name = provider_name

    def list_domains(self) -> list[DomainMetadata]:
        """Return all registered domain metadata instances.

        Returns:
            List of DomainMetadata in registration order.
        """
        return [info.metadata for info in self._domains.values()]

    def __len__(self) -> int:
        return len(self._domains)

    def __contains__(self, name: str) -> bool:
        return name in self._domains


def discover_domains() -> list[DomainMetadata]:
    """Discover all installed domain SDKs by scanning entry points.

    Scans the ``functualize.domains`` entry point group and loads each
    entry point, expecting a ``DomainMetadata``-compatible instance
    (any frozen dataclass with the required fields).

    Returns:
        List of successfully loaded DomainMetadata instances.
    """
    discovered: list[DomainMetadata] = []
    eps = entry_points(group=DOMAINS_ENTRY_POINT_GROUP)

    for ep in eps:
        try:
            metadata = ep.load()
        except Exception as exc:
            logger.warning(f"Failed to load domain entry point '{ep.name}': {exc}")
            continue

        # Validate structurally — the loaded object may be from a domain SDK's
        # local DomainMetadata copy. Convert to our canonical DomainMetadata.
        canonical = _to_canonical_metadata(metadata, ep.name)
        if canonical is None:
            continue

        discovered.append(canonical)
        logger.debug(f"Discovered domain '{canonical.name}' ({canonical.display_name})")

    return discovered


def _to_canonical_metadata(obj: Any, ep_name: str) -> DomainMetadata | None:
    """Convert a domain metadata object to the canonical DomainMetadata.

    Accepts either an instance of our DomainMetadata or any object with
    compatible fields (duck typing for cross-package compatibility).

    Args:
        obj: The loaded entry point object.
        ep_name: Entry point name (for error messages).

    Returns:
        Canonical DomainMetadata instance, or None if conversion fails.
    """
    # Already our canonical type
    if isinstance(obj, DomainMetadata):
        return obj

    # Duck-type check: must have the required fields
    required_fields = (
        "name",
        "display_name",
        "description",
        "capability_class",
        "provider_protocol",
        "config_section",
        "entry_point_group",
        "events_prefix",
    )
    for field_name in required_fields:
        if not hasattr(obj, field_name):
            logger.warning(
                f"Domain entry point '{ep_name}' is missing required field "
                f"'{field_name}'. Skipping."
            )
            return None

    try:
        return DomainMetadata(
            name=obj.name,
            display_name=obj.display_name,
            description=obj.description,
            capability_class=obj.capability_class,
            provider_protocol=obj.provider_protocol,
            config_section=obj.config_section,
            entry_point_group=obj.entry_point_group,
            events_prefix=obj.events_prefix,
            scaffold_template=getattr(obj, "scaffold_template", None),
            documentation_url=getattr(obj, "documentation_url", None),
            mock_factory=getattr(obj, "mock_factory", None),
        )
    except Exception as exc:
        logger.warning(
            f"Domain entry point '{ep_name}' could not be converted to "
            f"DomainMetadata: {exc}. Skipping."
        )
        return None


def scan_domain_providers(
    metadata: DomainMetadata,
) -> dict[str, importlib.metadata.EntryPoint]:
    """Scan a domain's entry point group for available implementation plugins.

    Args:
        metadata: The DomainMetadata instance whose entry_point_group to scan.

    Returns:
        Dictionary mapping provider names to their entry points.
    """
    eps = entry_points(group=metadata.entry_point_group)
    return {ep.name: ep for ep in eps}


def boot_domain_registry(app: Any) -> DomainRegistry:
    """Discover domains and build the domain registry at boot time.

    This is the main integration point called during FunctualizeApp boot.
    It performs the full discovery sequence:
    1. Scan ``functualize.domains`` entry points
    2. Register each domain in the registry
    3. Scan each domain's entry_point_group for available providers
    4. Read config for each domain to determine active provider
    5. Auto-select single implementations when no provider configured

    Args:
        app: The FunctualizeApp instance being booted.

    Returns:
        Populated DomainRegistry instance.
    """
    registry = DomainRegistry()

    # Step 1: Discover all installed domain SDKs
    domains = discover_domains()

    for metadata in domains:
        # Step 2: Register domain in the registry
        registry.register(metadata)

        # Step 3: Scan for available providers
        providers = scan_domain_providers(metadata)
        registry.set_available_providers(metadata.name, providers)

        # Step 4: Determine configured provider from app config
        configured_provider = _read_configured_provider(app, metadata)

        # Step 5: Determine active provider (auto-select or configured)
        if providers:
            try:
                if configured_provider:
                    # Explicit config
                    if configured_provider in providers:
                        registry.set_active_provider(metadata.name, configured_provider)
                elif len(providers) == 1:
                    # Auto-select single implementation
                    provider_name = next(iter(providers.keys()))
                    registry.set_active_provider(metadata.name, provider_name)
                    logger.debug(
                        f"Auto-selected provider '{provider_name}' for "
                        f"domain '{metadata.name}'"
                    )
                else:
                    logger.debug(
                        f"Multiple providers available for domain "
                        f"'{metadata.name}' with no explicit config: "
                        f"{list(providers.keys())}"
                    )
            except Exception as exc:
                logger.warning(
                    f"Error selecting provider for domain '{metadata.name}': {exc}"
                )
        else:
            logger.debug(f"No providers installed for domain '{metadata.name}'")

    return registry


def _read_configured_provider(app: Any, metadata: DomainMetadata) -> str | None:
    """Read the configured provider for a domain from the app's config.

    Looks up the ``provider`` key in the domain's config_section.

    Args:
        app: The FunctualizeApp instance.
        metadata: The DomainMetadata for the domain.

    Returns:
        The configured provider name, or None if not configured.
    """
    if not hasattr(app, "_resolution_chain") or app._resolution_chain is None:
        return None

    try:
        resolved = app._resolution_chain.resolve("provider", metadata.config_section)
        value = resolved.value
        if isinstance(value, str) and value.strip():
            return value.strip()
    except Exception:
        # Config section or key may not exist — that's fine
        pass

    return None
