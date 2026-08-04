"""Protocol definitions for the pluggable configuration system.

Defines the abstract interfaces that all format providers, remote providers,
and configuration sources must implement. All protocols are runtime-checkable
to support isinstance() verification during provider registration.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class FormatProvider(Protocol):
    """Protocol for configuration file format plugins.

    Implementations parse configuration files into normalized dictionaries
    and serialize dictionaries back to formatted strings. Each provider
    declares which file extensions it handles.

    Examples of format providers: TOML, YAML, INI, JSON.
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
            Normalized dict where values are primitives (str, int, float,
            bool, None), lists, or nested dicts of the same.

        Raises:
            FormatParseError: If the file is malformed or unreadable.
        """
        ...

    def serialize(self, data: dict[str, Any]) -> str:
        """Serialize a configuration dictionary to the provider's format.

        Args:
            data: Configuration dictionary to serialize.

        Returns:
            Formatted string representation using the format's conventional
            indentation and key ordering.
        """
        ...


@runtime_checkable
class RemoteProvider(Protocol):
    """Protocol for remote secret/configuration providers.

    Implementations fetch configuration values from external systems
    such as HashiCorp Vault, AWS Secrets Manager, or Infisical.
    Credentials MUST be resolved from environment variables only,
    following 12-Factor App principles.
    """

    def identifier(self) -> str:
        """Return the provider identifier used in 'provider://reference' syntax.

        E.g., 'vault', 'aws-sm', 'infisical'.
        """
        ...

    def is_ready(self) -> bool:
        """Check if the provider is properly configured with credentials.

        Credentials MUST be resolved from environment variables only.
        """
        ...

    def fetch(self, reference: str) -> str:
        """Fetch a value from the remote system.

        Args:
            reference: The key/path in the remote system
                (the part after 'provider://' in annotations).

        Returns:
            The resolved value as a string.

        Raises:
            RemoteKeyNotFoundError: If the key does not exist.
            RemoteConnectionError: If network/auth fails.
            RemoteTimeoutError: If fetch exceeds 30 seconds.
        """
        ...


@runtime_checkable
class Source(Protocol):
    """Protocol for configuration value sources in the Resolution_Chain.

    Each source represents one origin of configuration values (CLI args,
    environment variables, remote providers, file-based config, defaults).
    Sources are consulted in precedence order during resolution.
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
