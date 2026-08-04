"""Shared vocabulary package for functualize internal layers.

Contains ONLY frozen dataclass definitions, Enum classes, and Protocol
definitions. Zero business logic. Zero imports from any other _-prefixed
internal package. Every internal layer may import from here.

This package establishes the type contracts between layers without
creating coupling to implementations.
"""

from functualize._types.descriptors import (
    CacheInfo,
    ConfigFileInfo,
    FieldDescriptor,
    GroupOptionsSpec,
    JobDescriptor,
    JobResult,
    PluginCommand,
    RegisteredJob,
)
from functualize._types.enums import (
    ConfigFileRole,
    EnvironmentSource,
    JobPhase,
    RunStatus,
    RunType,
)
from functualize._types.errors import (
    AmbiguousJobError,
    GateResolutionError,
    GroupOptionsConflictError,
    JobDependencyError,
    JobNotFoundError,
    OrphanedPluginMetadataError,
    RecursionLimitError,
    WorkflowDeclarationError,
)
from functualize._types.interactivity import (
    InputNotAvailable,
    PromptChoice,
    PromptCollector,
    PromptIntent,
    PromptRequest,
    PromptResponse,
    PromptSeverity,
    Surface,
)
from functualize._types.job_declaration import (
    Call,
    Deps,
    Exec,
    Fingerprint,
    Guards,
    JobDeclaration,
    Precondition,
    Retry,
    call,
)
from functualize._types.protocols import (
    AdapterPlugin,
    FormatProvider,
    JobProvider,
    JobTransform,
    PluginWithShutdown,
    Source,
)
from functualize._types.redaction import Secret
from functualize._types.shell import (
    FailingResponder,
    Responder,
    Shell,
    ShellError,
    ShellResult,
)
from functualize._types.stdout import Stdout

__all__ = [
    # Frozen dataclasses
    "CacheInfo",
    "ConfigFileInfo",
    "FieldDescriptor",
    "GroupOptionsSpec",
    "JobDescriptor",
    "JobResult",
    "PluginCommand",
    "RegisteredJob",
    # Job declaration value objects
    "Call",
    "Deps",
    "Exec",
    "Fingerprint",
    "Guards",
    "JobDeclaration",
    "Precondition",
    "Retry",
    "call",
    # Enums
    "ConfigFileRole",
    "EnvironmentSource",
    "RunStatus",
    "RunType",
    "JobPhase",
    # Errors
    "AmbiguousJobError",
    "GateResolutionError",
    "GroupOptionsConflictError",
    "JobDependencyError",
    "WorkflowDeclarationError",
    "JobNotFoundError",
    "OrphanedPluginMetadataError",
    "RecursionLimitError",
    # Interactivity types
    "InputNotAvailable",
    "PromptChoice",
    "PromptIntent",
    "PromptRequest",
    "PromptResponse",
    "PromptSeverity",
    # Protocols
    "AdapterPlugin",
    "FormatProvider",
    "JobProvider",
    "JobTransform",
    "FailingResponder",
    "PluginWithShutdown",
    "PromptCollector",
    "Responder",
    "Secret",
    "Shell",
    "ShellError",
    "ShellResult",
    "Stdout",
    "Source",
    "Surface",
]
