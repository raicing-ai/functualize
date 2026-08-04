"""Protocol definitions for the functualize shared vocabulary.

Contains all protocol (interface) definitions that establish contracts
between layers. Zero imports from any _-prefixed internal package
(except _types itself for type references). Only stdlib imports.

Protocols defined here:
- JobProvider: Sources of job descriptors
- AdapterPlugin: Delivery surface adapters
- PluginWithShutdown: Plugins requiring cleanup on shutdown
- Source: Configuration value sources
- FormatProvider: Configuration file format plugins
- JobTransform: Job descriptor interceptors/modifiers

Re-exported from functualize._types.interactivity:
- Surface: renders a job's events
- PromptCollector: answers a job's prompts
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

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

if TYPE_CHECKING:
    from functualize._types.descriptors import JobDescriptor


@runtime_checkable
class JobProvider(Protocol):
    """Protocol for job descriptor sources.

    Implementations provide job descriptors from various sources
    (filesystem scan, entry points, static definitions, etc.).

    Note on workflows: the cached ``JobDescriptor.workflow`` shape is populated
    only by directory discovery, which projects it via the internal
    ``workflow_shape_of``. A provider building descriptors by hand leaves it
    ``None`` and has no public way to set it — deliberately, to keep the cache
    projection one-sided. Consumers that need a provider-declared workflow's
    topology read it live from ``descriptor.function.__functualize_workflow__``
    when the cached shape is absent (e.g. the MCP ``WorkflowToolProvider``);
    providers do not populate the field.
    """

    def list_jobs(self) -> Sequence[JobDescriptor]:
        """Return all job descriptors from this source."""
        ...

    def get_job(self, name: str) -> JobDescriptor | None:
        """Retrieve a specific job by name. None if not found."""
        ...


@runtime_checkable
class AdapterPlugin(Protocol):
    """Protocol for delivery surface adapters.

    Adapters decouple delivery surfaces (CLI, HTTP, Lambda, MCP) from
    the application kernel. Each adapter implements a setup/run/shutdown
    lifecycle.
    """

    name: str
    version: str
    description: str
    adapter_type: str  # "cli", "http", "lambda", "mcp"

    def __call__(self, app: Any) -> None:
        """Setup phase — called during boot to wire the adapter."""
        ...

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Universal entrypoint with platform-specific signatures."""
        ...

    def shutdown(self) -> None:
        """Graceful shutdown. No-op if not needed."""
        ...


@runtime_checkable
class PluginWithShutdown(Protocol):
    """Protocol for plugins requiring cleanup on application shutdown.

    Plugins satisfying this protocol will have on_shutdown called in
    reverse loading order when the application completes execution.
    """

    def on_shutdown(self, app: Any) -> None:
        """Called during application shutdown for resource cleanup.

        Args:
            app: The application instance being shut down.
        """
        ...


@runtime_checkable
class Source(Protocol):
    """Protocol for configuration value sources in the Resolution Chain.

    Each source represents one origin of configuration values (CLI args,
    environment variables, remote providers, file-based config, defaults).
    """

    @property
    def source_type(self) -> str:
        """Source type identifier (e.g., 'cli', 'env', 'remote', 'file', 'default')."""
        ...

    @property
    def source_id(self) -> str:
        """Source identifier (e.g., file path, provider name, 'environ')."""
        ...

    def get(self, key: str, section: str | None = None) -> Any | None:
        """Retrieve a value for the given key.

        Args:
            key: The configuration key name.
            section: Optional section/namespace.

        Returns:
            The value if found, None if not present in this source.
        """
        ...

    def has(self, key: str, section: str | None = None) -> bool:
        """Check if this source can provide a value for the key."""
        ...

    def keys(self, section: str) -> set[str]:
        """Return all keys available for the given section.

        Args:
            section: The section/namespace to query.

        Returns:
            Set of key names this source can provide for the section.
        """
        ...


@runtime_checkable
class FormatProvider(Protocol):
    """Protocol for configuration file format plugins.

    Implementations parse configuration files into normalized dictionaries
    and serialize dictionaries back to formatted strings.
    """

    def extensions(self) -> list[str]:
        """Return file extensions this provider handles (e.g., ['.toml']).

        Each extension MUST include the leading dot.
        """
        ...

    def parse(self, path: str) -> dict[str, Any]:
        """Parse a configuration file and return a normalized dictionary.

        Args:
            path: Absolute path to the configuration file.

        Returns:
            Normalized dict with primitive values, lists, or nested dicts.
        """
        ...

    def serialize(self, data: dict[str, Any]) -> str:
        """Serialize a configuration dictionary to the provider's format.

        Args:
            data: Configuration dictionary to serialize.

        Returns:
            Formatted string representation.
        """
        ...


@runtime_checkable
class JobTransform(Protocol):
    """Protocol for intercepting and modifying job descriptors.

    Implementations transform job descriptors as they flow from providers
    to the registry.
    """

    def transform_list(self, jobs: Sequence[JobDescriptor]) -> Sequence[JobDescriptor]:
        """Transform a list of job descriptors."""
        ...

    def transform_get(
        self, name: str, descriptor: JobDescriptor | None
    ) -> JobDescriptor | None:
        """Transform a single job descriptor lookup."""
        ...


__all__ = [
    # Protocols
    "AdapterPlugin",
    "FormatProvider",
    "JobProvider",
    "JobTransform",
    "PluginWithShutdown",
    "Source",
    # Re-exports from functualize._types.interactivity
    "InputNotAvailable",
    "PromptChoice",
    "PromptCollector",
    "PromptIntent",
    "PromptRequest",
    "PromptResponse",
    "PromptSeverity",
    "Surface",
]
