"""ModulePreFilter integration for the discovery pipeline.

Provides a convenience factory for constructing the default pre-filter
stack used during job discovery. Re-exports key types from _primitives
for ergonomic use within the discovery layer.

Only imports from `_types/`, `_primitives/`, `_events/`, and Python stdlib.
"""

from __future__ import annotations

from functualize._primitives import (
    AllOf,
    AnyOf,
    ASTModulePreFilter,
    DefaultModulePreFilter,
    MarkerModulePreFilter,
    ModulePreFilter,
    NoneOf,
)

# Re-export for convenience within _discovery/
__all__ = [
    "AllOf",
    "AnyOf",
    "ASTModulePreFilter",
    "DefaultModulePreFilter",
    "MarkerModulePreFilter",
    "ModulePreFilter",
    "NoneOf",
    "get_default_pre_filter",
]


def get_default_pre_filter() -> ModulePreFilter:
    """Create the default pre-filter stack for job module discovery.

    Default stack:
    1. DefaultModulePreFilter — skip underscore-prefixed files
    2. ASTModulePreFilter — require at least one public function definition

    Both filters must pass for a module to be imported (AllOf combinator).

    Returns:
        A ModulePreFilter instance combining the default checks.
    """
    return AllOf(
        DefaultModulePreFilter(),
        ASTModulePreFilter(),
    )
