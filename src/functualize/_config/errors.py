"""Typed error hierarchy for the configuration resolution system.

All errors extend ConfigurationError and carry contextual fields
for diagnosing failures without a debugger.

Only imports from stdlib — no internal package dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass


class ConfigurationError(Exception):
    """Base for all configuration system errors."""


class FormatParseError(ConfigurationError):
    """Errors parsing a configuration file.

    Attributes:
        path: The file path that failed to parse.
        reason: Description of the parsing failure.
    """

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Failed to parse '{path}': {reason}")


class MissingKeyError(ConfigurationError):
    """Key not found in any source and no default exists.

    Attributes:
        key: The missing configuration key.
        consulted_sources: List of source identifiers that were checked.
    """

    def __init__(self, key: str, consulted_sources: list[str]) -> None:
        self.key = key
        self.consulted_sources = consulted_sources
        sources_str = ", ".join(consulted_sources)
        super().__init__(
            f"Key '{key}' not found in any source. Consulted: {sources_str}"
        )


class UnsupportedFormatError(ConfigurationError):
    """No provider registered for a file extension.

    Attributes:
        extension: The unsupported file extension.
        path: The file path with the unsupported extension.
    """

    def __init__(self, extension: str, path: str) -> None:
        self.extension = extension
        self.path = path
        super().__init__(
            f"No format provider registered for extension '{extension}' "
            f"(file: '{path}')"
        )


@dataclass(frozen=True)
class SourceAnnotation:
    """A parsed 'provider://reference' annotation."""

    provider: str
    reference: str


@dataclass(frozen=True)
class AnnotationResolutionFailure:
    """Records a failure when resolving a source annotation."""

    annotation: SourceAnnotation
    error_type: str  # 'not_found', 'connection', 'auth', 'timeout', 'not_registered'
    message: str


class AnnotationResolutionError(ConfigurationError):
    """All sources in a fallback chain failed.

    Attributes:
        key: The configuration key whose annotation could not be resolved.
        failures: List of resolution failures for each attempted source.
    """

    def __init__(self, key: str, failures: list[AnnotationResolutionFailure]) -> None:
        self.key = key
        self.failures = failures
        details = "; ".join(
            f"{f.annotation.provider}://{f.annotation.reference} "
            f"({f.error_type}: {f.message})"
            for f in failures
        )
        super().__init__(f"All sources failed for key '{key}': {details}")


class UnregisteredProviderError(ConfigurationError):
    """Referenced provider is not registered.

    Attributes:
        provider_name: The unregistered provider identifier.
        config_key: The configuration key that referenced it.
    """

    def __init__(self, provider_name: str, config_key: str = "") -> None:
        self.provider_name = provider_name
        self.config_key = config_key
        msg = f"Provider '{provider_name}' is not registered"
        if config_key:
            msg += f" (referenced by key '{config_key}')"
        super().__init__(msg)


class RemoteTimeoutError(ConfigurationError):
    """Remote fetch exceeded timeout.

    Attributes:
        provider: The remote provider identifier.
        reference: The key/path being fetched.
    """

    def __init__(self, provider: str, reference: str) -> None:
        self.provider = provider
        self.reference = reference
        super().__init__(
            f"Timeout fetching '{reference}' from provider '{provider}' (exceeded 30s)"
        )


class MigrationError(ConfigurationError):
    """Error during configuration file migration (e.g., INI → TOML).

    Attributes:
        file: The file path that failed migration.
        line: The line number where the issue was detected.
        construct: Description of the unsupported construct.
    """

    def __init__(self, file: str, line: int, construct: str) -> None:
        self.file = file
        self.line = line
        self.construct = construct
        super().__init__(
            f"Migration error in '{file}' at line {line}: unsupported {construct}"
        )


class PresetNotFoundError(ConfigurationError):
    """Referenced configuration preset does not exist.

    Attributes:
        name: The preset identifier that was not found.
        available: List of valid preset names.
    """

    def __init__(self, preset_name: str, available: list[str] | None = None) -> None:
        self.name = preset_name
        self.preset_name = preset_name
        self.available = available or []
        super().__init__(
            f"Preset '{preset_name}' not found. "
            f"Available presets: {', '.join(self.available)}"
        )
