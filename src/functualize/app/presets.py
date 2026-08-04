"""Preset factory functions for common configuration strategies.

Each function returns a ConfigSources instance preconfigured for a specific
deployment model. Any callable with signature ``(**kwargs) -> ConfigSources``
is a valid preset — these built-in factories are conveniences, not special.

Usage:
    from functualize.app.presets import classic, twelve_factor

    app = FunctualizeApp("myapp", config_sources=twelve_factor(dotenv=True))
"""

from __future__ import annotations

from functualize._config.chain import ResolutionChain
from functualize._config.sources import CliSource, DefaultSource, EnvSource
from functualize.app.config import ConfigSources

#: Names of all built-in presets (used by PresetNotFoundError for diagnostics).
PRESET_NAMES: list[str] = [
    "classic",
    "twelve_factor",
    "env_only",
    "remote_first",
]


def classic(
    *,
    file_pattern: str = r"^config\.(\w+)\.(\w+)$",
    dotenv: bool = True,
) -> ConfigSources:
    """CLI → Env → Files (upward search) → Defaults.

    Leaves ``config_resolution_chain`` as None so that the boot path
    performs file discovery and builds the full chain at startup.

    Args:
        file_pattern: Regex for matching config files during discovery.
        dotenv: Whether to load .env files.

    Returns:
        A ConfigSources instance configured for classic file-based resolution.
    """
    return ConfigSources(
        file_pattern=file_pattern,
        dotenv=dotenv,
        config_resolution_chain=None,
    )


def twelve_factor(*, dotenv: bool = False) -> ConfigSources:
    """CLI → Env → Defaults. No file discovery.

    Sets an explicit resolution chain that skips FileSource entirely.
    Environment variables are the primary configuration source.

    Args:
        dotenv: Whether to load .env files (default False for pure 12-factor).

    Returns:
        A ConfigSources instance configured for twelve-factor apps.
    """
    chain = ResolutionChain([CliSource({}), EnvSource(), DefaultSource({})])
    return ConfigSources(
        dotenv=dotenv,
        config_resolution_chain=chain,
    )


def env_only(*, dotenv: bool = True, dotenv_path: str | None = None) -> ConfigSources:
    """CLI → Env → Defaults. Minimal configuration.

    Like twelve_factor but with dotenv enabled by default for local
    development convenience.

    Args:
        dotenv: Whether to load .env files (default True).
        dotenv_path: Explicit path to .env file (None = auto-discover).

    Returns:
        A ConfigSources instance configured for environment-only resolution.
    """
    chain = ResolutionChain([CliSource({}), EnvSource(), DefaultSource({})])
    return ConfigSources(
        dotenv=dotenv,
        dotenv_path=dotenv_path,
        config_resolution_chain=chain,
    )


def remote_first(
    *,
    file_pattern: str = "config.*",
    dotenv: bool = False,
) -> ConfigSources:
    """CLI → Remote → Env → Files → Defaults.

    Leaves ``config_resolution_chain`` as None so that the boot path
    can wire up RemoteSource and FileSource with the discovered
    ResourceLocator and ProviderRegistry.

    Args:
        file_pattern: Glob pattern for config file matching.
        dotenv: Whether to load .env files.

    Returns:
        A ConfigSources instance configured for remote-first resolution.
    """
    return ConfigSources(
        file_pattern=file_pattern,
        dotenv=dotenv,
        config_resolution_chain=None,
    )
