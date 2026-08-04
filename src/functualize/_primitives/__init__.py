"""Foundation utilities package for functualize internal layers.

Contains foundational utilities that other layers build upon:
- DIRegistry: type-based dependency injection container
- ResourceLocator: fluent builder for ordered resource location
- MiddlewareChain: composable yield-based middleware executor
- ModulePreFilter: fast pre-import check protocol and combinators (file level)
- JobFilter: per-descriptor registration check protocol (job level)
- lazy_cached: descriptor for deferred attribute computation
- resilient: error-tolerant iteration wrapper
- iter_module_files: module file discovery utility

This package imports ONLY from `_types/` and Python stdlib.
Zero third-party runtime dependencies.
"""

from functualize._primitives.di import (
    AmbiguousProviderError,
    DIRegistry,
    DIValidationError,
    MissingProviderError,
    Provide,
    RegistryFrozenError,
    ResolutionError,
)
from functualize._primitives.job_filter import (
    AllJobFilters,
    JobDecoratorFilter,
    JobFilter,
    JobPostfixFilter,
    JobPrefixFilter,
)
from functualize._primitives.lazy import lazy_cached
from functualize._primitives.locator import (
    Candidate,
    LocateResult,
    ResourceLocator,
    ResourceLocatorError,
    compute_project_id,
)
from functualize._primitives.middleware import MiddlewareChain
from functualize._primitives.modules import iter_module_files
from functualize._primitives.pre_filter import (
    AllOf,
    AnyOf,
    ASTModulePreFilter,
    DefaultModulePreFilter,
    DisplayClassPreFilter,
    GlobExcludePreFilter,
    GroupOptionsPreFilter,
    MarkerModulePreFilter,
    ModulePreFilter,
    NoneOf,
)
from functualize._primitives.resilient import resilient

# Re-export from local module
from functualize._primitives.resolution import first_non_none

__all__ = [
    "AllJobFilters",
    "AllOf",
    "ASTModulePreFilter",
    "AmbiguousProviderError",
    "AnyOf",
    "Candidate",
    "DIRegistry",
    "DIValidationError",
    "DefaultModulePreFilter",
    "DisplayClassPreFilter",
    "GroupOptionsPreFilter",
    "GlobExcludePreFilter",
    "JobDecoratorFilter",
    "JobFilter",
    "JobPostfixFilter",
    "JobPrefixFilter",
    "LocateResult",
    "MarkerModulePreFilter",
    "MiddlewareChain",
    "MissingProviderError",
    "ModulePreFilter",
    "NoneOf",
    "Provide",
    "RegistryFrozenError",
    "ResolutionError",
    "ResourceLocator",
    "ResourceLocatorError",
    "compute_project_id",
    "first_non_none",
    "iter_module_files",
    "lazy_cached",
    "resilient",
]
