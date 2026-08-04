"""Provider registry for discovering and managing format and remote providers.

Discovers providers from Python entry points and explicit programmatic
registration. Thread-safe via a threading lock. Last-registered provider
wins for duplicate extensions/identifiers, with a logged warning.
"""

from __future__ import annotations

import logging
import threading
from importlib.metadata import entry_points

from functualize._config.errors import (
    UnregisteredProviderError,
    UnsupportedFormatError,
)
from functualize._config.protocols import FormatProvider, RemoteProvider

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Discovers and manages Format_Providers and Remote_Providers.

    Loads providers from:
    1. Python entry points (groups: 'functualize.format_providers',
       'functualize.remote_providers')
    2. Explicit programmatic registration

    Thread-safe. Discovery happens on explicit call to discover_entry_points().
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._format_providers: dict[str, FormatProvider] = {}
        self._remote_providers: dict[str, RemoteProvider] = {}

    def register_format_provider(self, provider: FormatProvider) -> None:
        """Register a format provider for its declared extensions.

        If another provider is already registered for an extension,
        the new provider replaces it and a warning is logged.

        Args:
            provider: An object implementing the FormatProvider protocol.

        Raises:
            TypeError: If provider does not implement FormatProvider protocol.
        """
        if not isinstance(provider, FormatProvider):
            raise TypeError(f"Expected a FormatProvider, got {type(provider).__name__}")
        with self._lock:
            for ext in provider.extensions():
                if ext in self._format_providers:
                    existing = self._format_providers[ext]
                    if type(existing) is type(provider):
                        # Same class re-registered — skip silently
                        continue
                    logger.warning(
                        "Format provider for extension '%s' overridden: "
                        "'%s' replaced by '%s'",
                        ext,
                        type(existing).__name__,
                        type(provider).__name__,
                    )
                self._format_providers[ext] = provider

    def register_remote_provider(self, provider: RemoteProvider) -> None:
        """Register a remote provider for its declared identifier.

        If another provider is already registered for the same identifier,
        the new provider replaces it and a warning is logged.

        Args:
            provider: An object implementing the RemoteProvider protocol.

        Raises:
            TypeError: If provider does not implement RemoteProvider protocol.
        """
        if not isinstance(provider, RemoteProvider):
            raise TypeError(f"Expected a RemoteProvider, got {type(provider).__name__}")
        with self._lock:
            identifier = provider.identifier()
            if identifier in self._remote_providers:
                existing = self._remote_providers[identifier]
                if type(existing) is type(provider):
                    # Same class re-registered — skip silently
                    return
                logger.warning(
                    "Remote provider for identifier '%s' overridden: "
                    "'%s' replaced by '%s'",
                    identifier,
                    type(existing).__name__,
                    type(provider).__name__,
                )
            self._remote_providers[identifier] = provider

    def get_format_provider(self, extension: str) -> FormatProvider:
        """Get the format provider registered for a file extension.

        Args:
            extension: File extension including the leading dot (e.g., '.toml').

        Returns:
            The registered FormatProvider for the given extension.

        Raises:
            UnsupportedFormatError: If no provider is registered for the extension.
        """
        with self._lock:
            provider = self._format_providers.get(extension)
        if provider is None:
            raise UnsupportedFormatError(extension=extension, path="<lookup>")
        return provider

    def get_remote_provider(self, identifier: str) -> RemoteProvider:
        """Get the remote provider registered for an identifier.

        Args:
            identifier: The provider identifier (e.g., 'vault', 'aws-sm').

        Returns:
            The registered RemoteProvider for the given identifier.

        Raises:
            UnregisteredProviderError: If no provider is registered for the
                identifier.
        """
        with self._lock:
            provider = self._remote_providers.get(identifier)
        if provider is None:
            raise UnregisteredProviderError(
                provider_name=identifier, config_key="<lookup>"
            )
        return provider

    def list_format_providers(self) -> dict[str, FormatProvider]:
        """Return a copy of the current extension-to-provider mapping.

        Returns:
            Dictionary mapping file extensions to their FormatProvider instances.
        """
        with self._lock:
            return dict(self._format_providers)

    def list_remote_providers(self) -> dict[str, RemoteProvider]:
        """Return a copy of the current identifier-to-provider mapping.

        Returns:
            Dictionary mapping identifiers to their RemoteProvider instances.
        """
        with self._lock:
            return dict(self._remote_providers)

    def discover_entry_points(self) -> None:
        """Discover and load providers from Python entry points.

        Loads from the 'functualize.format_providers' and
        'functualize.remote_providers' entry point groups.

        Failed entry points are skipped with a warning log message.
        """
        self._discover_format_entry_points()
        self._discover_remote_entry_points()

    def _discover_format_entry_points(self) -> None:
        """Load format providers from the entry point group."""
        eps = entry_points(group="functualize.format_providers")
        for ep in eps:
            try:
                provider_obj = ep.load()
                # If the entry point returns a class, instantiate it
                if isinstance(provider_obj, type):
                    provider_obj = provider_obj()
                if not isinstance(provider_obj, FormatProvider):
                    logger.warning(
                        "Entry point '%s' in group 'functualize.format_providers' "
                        "does not implement FormatProvider protocol, skipping",
                        ep.name,
                    )
                    continue
                self.register_format_provider(provider_obj)
            except Exception as exc:
                logger.warning(
                    "Failed to load format provider entry point '%s': %s",
                    ep.name,
                    exc,
                )

    def _discover_remote_entry_points(self) -> None:
        """Load remote providers from the entry point group."""
        eps = entry_points(group="functualize.remote_providers")
        for ep in eps:
            try:
                provider_obj = ep.load()
                # If the entry point returns a class, instantiate it
                if isinstance(provider_obj, type):
                    provider_obj = provider_obj()
                if not isinstance(provider_obj, RemoteProvider):
                    logger.warning(
                        "Entry point '%s' in group 'functualize.remote_providers' "
                        "does not implement RemoteProvider protocol, skipping",
                        ep.name,
                    )
                    continue
                self.register_remote_provider(provider_obj)
            except Exception as exc:
                logger.warning(
                    "Failed to load remote provider entry point '%s': %s",
                    ep.name,
                    exc,
                )
