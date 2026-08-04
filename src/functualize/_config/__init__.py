"""Configuration resolution package for functualize internal layers.

Contains the pluggable configuration resolution system:
- ResolutionChain: Ordered source consultation with provenance tracking
- Source implementations: CliSource, EnvSource, FileSource, RemoteSource, DefaultSource
- JobConfigView: Scoped read-write config access for job execution
- Format providers: TOML and INI file parsing/serialization

This package imports ONLY from `_types/`, `_primitives/`, `_events/`, and Python stdlib.
No other internal package imports are allowed.
"""

from functualize._config.chain import ResolutionChain, ResolvedValue
from functualize._config.errors import (
    ConfigurationError,
    FormatParseError,
    MissingKeyError,
)
from functualize._config.job_config import JobConfigView
from functualize._config.sources import (
    CliSource,
    DefaultSource,
    EnvSource,
    FileSource,
    RemoteSource,
)

__all__ = [
    # Core resolution
    "ResolutionChain",
    "ResolvedValue",
    # Source implementations
    "CliSource",
    "DefaultSource",
    "EnvSource",
    "FileSource",
    "RemoteSource",
    # Job config access
    "JobConfigView",
    # Errors
    "ConfigurationError",
    "FormatParseError",
    "MissingKeyError",
]
