"""Job finding pipeline package for functualize internal layers.

Contains the complete job discovery subsystem:
- Providers: DirectoryScanProvider, StaticProvider, EntryPointProvider
- Cached provider: CachedDirectoryScanProvider — the single persisted
  discovery cache (format shared via `_primitives/cache_format.py`)
- Transforms: NamespaceTransform, GroupByModuleTransform
- PreFilter: ModulePreFilter integration for fast pre-import decisions
- Hierarchy: Child project composition for multi-project setups
- Pipeline: ResolutionPipeline orchestrating providers + transforms

This package imports ONLY from `_types/`, `_primitives/`, `_events/`, and
Python stdlib. Never from peer layers (_config, _engine, _plugins, _app, _cli).
"""

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._discovery.hierarchy import ChildProject
from functualize._discovery.naming import qualified_name
from functualize._discovery.pipeline import ProviderEntry, ResolutionPipeline
from functualize._discovery.pre_filter import get_default_pre_filter
from functualize._discovery.providers import (
    DirectoryScanProvider,
    EntryPointProvider,
    Job,
    StaticProvider,
    extract_capability_markers,
    extract_parameters_from_signature,
)
from functualize._discovery.transforms import (
    GroupByModuleTransform,
    NamespaceTransform,
)
from functualize._primitives.cache_format import PreFilterDecision

__all__ = [
    # Naming
    "qualified_name",
    # Providers
    "CachedDirectoryScanProvider",
    "DirectoryScanProvider",
    "EntryPointProvider",
    "Job",
    "StaticProvider",
    # Introspection
    "extract_parameters_from_signature",
    "extract_capability_markers",
    # Transforms
    "GroupByModuleTransform",
    "NamespaceTransform",
    # Cache
    "PreFilterDecision",
    # Pre-filter
    "get_default_pre_filter",
    # Hierarchy
    "ChildProject",
    # Pipeline
    "ProviderEntry",
    "ResolutionPipeline",
]
