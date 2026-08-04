"""Plugin loading machinery package for functualize internal layers.

Contains plugin discovery, dependency sorting, loading, and config resolution:
- PluginLoader: Discovery + dependency sort + loading via entry points and files
- PluginConfigRegistry: Stores resolved plugin config model instances
- topological_sort: Kahn's algorithm with stable alphabetical ordering
- CircularDependencyError, MissingDependencyError: Dependency resolution errors
- DomainMetadata: Centralized dataclass for domain SDK self-description
- DomainRegistry: Reporting-only registry of discovered domains and their providers

This package imports ONLY from `_types/`, `_primitives/`, `_events/`, and Python stdlib.
No other internal package imports are allowed.
"""

from functualize._plugins.config import PluginConfigRegistry
from functualize._plugins.domain_metadata import DomainMetadata
from functualize._plugins.domain_registry import (
    DomainInfo,
    DomainRegistry,
    boot_domain_registry,
    discover_domains,
    scan_domain_providers,
)
from functualize._plugins.loader import (
    CircularDependencyError,
    MissingDependencyError,
    PluginLoader,
    topological_sort,
)

__all__ = [
    # Plugin loader
    "PluginLoader",
    # Config registry
    "PluginConfigRegistry",
    # Dependency resolution
    "CircularDependencyError",
    "MissingDependencyError",
    "topological_sort",
    # Domain SDK discovery
    "DomainMetadata",
    "DomainInfo",
    "DomainRegistry",
    "boot_domain_registry",
    "discover_domains",
    "scan_domain_providers",
]
