"""Frozen dataclass configuration objects for FunctualizeApp constructor.

These dataclasses group related constructor parameters into semantic units,
enabling a clean constructor API with sensible defaults:

    from functualize.app import FunctualizeApp, JobSources, ConfigSources

    app = FunctualizeApp(
        "myapp",
        job_sources=JobSources(directories=["./jobs"]),
        config_sources=ConfigSources(dotenv=False),
        plugin_sources=PluginSources(entry_point_group="myapp.plugins"),
        execution=ExecutionConfig(max_invoke_depth=5),
    )

All config objects are frozen (immutable after construction) to prevent
accidental mutation during the application lifecycle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from functualize._discovery import Job

if TYPE_CHECKING:
    from functualize._config import ResolutionChain

__all__ = [
    "ConfigSources",
    "DiscoveryConfig",
    "ExecutionConfig",
    "Job",
    "JobSources",
    "PluginSources",
]


@dataclass(frozen=True)
class JobSources:
    """All job source configuration.

    Controls where the application discovers job functions:
    - directories: filesystem paths to scan for job modules
    - functions: pre-imported callables or Job definitions (static wiring)
    - job_providers: custom JobProvider instances with optional transforms
    - children: named child project mappings (namespace → directory)
    - children_glob: glob pattern for discovering child projects
    - lazy: whether to use cache-first discovery (default True)
    """

    directories: list[str] | None = None
    functions: list[Callable[..., Any] | Job] | None = None
    job_providers: list[Any] | None = (
        None  # list[JobProvider | tuple[JobProvider, list[JobTransform]]]
    )
    children: dict[str, str] | None = None
    children_glob: str | None = None
    lazy: bool = True


@dataclass(frozen=True)
class ConfigSources:
    """Configuration resolution settings.

    Controls how the application discovers and resolves configuration:
    - file_pattern: regex for matching config files (default: config.<env>.<ext>)
    - config_resolution_chain: explicit resolution chain (skips file discovery)
    - dotenv: whether to load .env files (default True)
    - dotenv_path: explicit path to .env file (None = auto-discover)

    When ``config_resolution_chain`` is None (default), the boot path builds
    the classic chain [CliSource, EnvSource, FileSource, DefaultSource] using
    file discovery. When set to an explicit ResolutionChain (e.g., from
    ``twelve_factor()``), that chain is used directly without file discovery.

    **The default pattern requires a ``<slot>`` segment but does not pin the
    extension.** Which extensions count is decided by the registered format
    providers, so a plugin that registers ``.yaml`` makes ``config.prod.yaml``
    discoverable without anyone editing this regex. The pattern used to spell
    ``(ini|toml)`` inline, which meant it silently disagreed with the file
    reader in both directions: an extension some provider handled could not
    anchor a directory unless the regex happened to name it.

    Since ADR-007 the only extension registered by default is ``.toml``, so
    ``config.prod.ini`` neither anchors nor resolves unless a plugin registers
    ``IniFormatProvider``. That is a change in the provider set, not in this
    rule.
    """

    file_pattern: str = r"^config\.(\w+)\.(\w+)$"
    config_resolution_chain: ResolutionChain | None = None
    dotenv: bool = True
    dotenv_path: str | None = None


@dataclass(frozen=True)
class PluginSources:
    """Plugin discovery settings.

    Controls how plugins are found and loaded:
    - entry_point_group: entry point group name for plugin discovery
    - explicit_plugins: list of pre-instantiated plugin objects
    - disabled: list of plugin names to skip during discovery
    """

    entry_point_group: str = "functualize.plugins"
    explicit_plugins: list[Any] | None = None
    disabled: list[str] | None = None


@dataclass(frozen=True)
class ExecutionConfig:
    """Execution parameters.

    Controls runtime behavior:
    - max_invoke_depth: maximum nested job invocation depth (prevents infinite recursion)
    """

    max_invoke_depth: int = 10


@dataclass(frozen=True)
class DiscoveryConfig:
    """All discovery-related settings for job discovery filtering.

    When all ``require_*`` fields are None, baseline convention mode applies:
    all public functions in qualifying files become jobs.

    Fields are composable via AND logic — each set field adds a constraint.
    Uses tuples for immutability and hashability. None means "not configured"
    (no constraint); empty tuple/string has different semantics.
    """

    exclude_patterns: tuple[str, ...] = ()
    extra_directories: tuple[str, ...] = ()
    require_file_prefix: str | None = None
    require_file_postfix: str | None = None
    require_file_import: str | None = None
    require_file_marker: str | None = None
    require_job_decorators: tuple[str, ...] | None = None
    require_job_prefix: str | None = None
    require_job_postfix: str | None = None
