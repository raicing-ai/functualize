"""Source implementations for the pluggable configuration ResolutionChain.

Provides concrete implementations of the Source protocol:
- CliSource: Maps CLI option names to config keys, only exposes explicit values
- EnvSource: Reads from os.environ using SECTION_KEY convention
- RemoteSource: Resolves "provider://ref" annotations via registry with 30s timeout
- FileSource: Uses ResourceLocator + FormatProvider to discover, parse, and deep-merge files
- DefaultSource: Exposes default values as a fallback source

Only imports from `_types/`, `_primitives/`, `_events/`, and Python stdlib.
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from functualize._config.errors import (
    AnnotationResolutionError,
    AnnotationResolutionFailure,
    RemoteTimeoutError,
    SourceAnnotation,
    UnregisteredProviderError,
)
from functualize._config.merge import deep_merge
from functualize._config.roles import classify, parse_slot
from functualize._types.descriptors import ConfigFileInfo
from functualize._types.enums import ConfigFileRole

if TYPE_CHECKING:
    from functualize._events import EventBus
    from functualize._types import FormatProvider


@runtime_checkable
class FileResolver(Protocol):
    """Protocol for objects that can resolve file paths by pattern.

    Both ResourceLocator and any custom resolver satisfying this interface
    can be used with FileSource.
    """

    def resolve(self, pattern: str) -> list[str]: ...


@runtime_checkable
class RemoteProvider(Protocol):
    """Protocol for remote configuration providers.

    Implementations fetch configuration values from external systems
    (e.g., AWS SSM, HashiCorp Vault, etc.).
    """

    def identifier(self) -> str:
        """Return the provider identifier string."""
        ...

    def is_ready(self) -> bool:
        """Check if the provider is configured and ready to serve requests."""
        ...

    def fetch(self, reference: str) -> str:
        """Fetch a value by reference. Returns the value as string."""
        ...


@runtime_checkable
class ProviderRegistry(Protocol):
    """Protocol for a registry of format and remote providers."""

    def get_format_provider(self, extension: str) -> FormatProvider:
        """Get a format provider for the given file extension."""
        ...

    def get_remote_provider(self, name: str) -> RemoteProvider:
        """Get a remote provider by name.

        Raises:
            UnregisteredProviderError: If provider is not registered.
        """
        ...


@runtime_checkable
class SourceAnnotationLike(Protocol):
    """Protocol for source annotations (provider://reference pairs)."""

    @property
    def provider(self) -> str: ...

    @property
    def reference(self) -> str: ...


# Timeout for remote provider fetches (seconds)
_REMOTE_TIMEOUT: float = 30.0


class CliSource:
    """Adapts parsed CLI/TUI arguments into the Source protocol.

    Maps CLI option names to config key paths using the convention:
    - Hyphens in option names are converted to underscores
    - Dot-separated names map to section.key (e.g., ``--database.port`` →
      section="database", key="port")

    Only explicitly-provided values are exposed (not defaults).
    """

    @property
    def source_type(self) -> str:
        """Return 'cli' source type identifier."""
        return "cli"

    @property
    def source_id(self) -> str:
        """Return 'cli' source identifier."""
        return "cli"

    def __init__(self, values: dict[str, Any]) -> None:
        """Initialize with explicitly-provided CLI values.

        Args:
            values: Dict of CLI option names to values. Keys may use hyphens
                or dots. Only include values that were explicitly provided
                by the user (not defaults).
        """
        self._indexed: dict[tuple[str | None, str], Any] = {}
        for raw_key, value in values.items():
            section, key = self._parse_cli_key(raw_key)
            self._indexed[(section, key)] = value

    def get(self, key: str, section: str | None = None) -> Any | None:
        """Retrieve a value for the given key."""
        return self._indexed.get((section, key))

    def has(self, key: str, section: str | None = None) -> bool:
        """Check if this source can provide a value for the key."""
        return (section, key) in self._indexed

    def keys(self, section: str) -> set[str]:
        """Return all keys available for the given section."""
        return {key for (sec, key) in self._indexed if sec == section}

    @staticmethod
    def _parse_cli_key(raw_key: str) -> tuple[str | None, str]:
        """Parse a CLI option name into (section, key).

        Converts hyphens to underscores. If the key contains a dot,
        the part before the dot is the section.
        """
        cleaned = raw_key.lstrip("-")
        cleaned = cleaned.replace("-", "_")

        if "." in cleaned:
            parts = cleaned.split(".", maxsplit=1)
            return (parts[0], parts[1])

        return (None, cleaned)


class EnvSource:
    """Reads configuration from os.environ using SECTION_KEY convention.

    Key lookup convention:
    - ``get("port", "database")`` → reads ``DATABASE_PORT``
    - ``get("debug")`` → reads ``DEBUG`` (no section)

    All lookups are uppercased. Section and key are joined with underscore.
    """

    @property
    def source_type(self) -> str:
        """Return 'env' source type identifier."""
        return "env"

    @property
    def source_id(self) -> str:
        """Return 'environ' source identifier."""
        return "environ"

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        """Initialize the environment source.

        Args:
            environ: Optional dict to use instead of os.environ.
                Useful for testing.
        """
        self._environ = environ

    def _get_environ(self) -> dict[str, str]:
        """Get the environment dict (os.environ or injected override)."""
        if self._environ is not None:
            return self._environ
        return dict(os.environ)

    def get(self, key: str, section: str | None = None) -> Any | None:
        """Retrieve a value from environment variables."""
        env_key = self._build_env_key(key, section)
        environ = self._get_environ()
        return environ.get(env_key)

    def has(self, key: str, section: str | None = None) -> bool:
        """Check if the environment variable exists."""
        env_key = self._build_env_key(key, section)
        environ = self._get_environ()
        return env_key in environ

    def keys(self, section: str) -> set[str]:
        """Return all keys available for the given section."""
        environ = self._get_environ()
        prefix = f"{section.upper().replace('-', '_')}_"
        return {
            env_key[len(prefix) :].lower()
            for env_key in environ
            if env_key.startswith(prefix)
        }

    @staticmethod
    def _build_env_key(key: str, section: str | None) -> str:
        """Build the environment variable name from section and key.

        Hyphens **and dots** become underscores. Sections are job names, which
        are canonical (``env-cfg``) and may be group-qualified (``infra.deploy``),
        and an environment variable name can contain neither character — so
        without this the key would be ``ENV-CFG_API_URL`` or
        ``INFRA.DEPLOY_API_URL``, which no shell can export and nothing would
        ever match. The value would fall through to the default silently, which
        is the worst way for config to fail.

        The dot half was added with T45: that task promises an error naming the
        environment variable that sets a missing field, and a named variable
        this builder could never look up would be worse than no name at all.
        It matches what the group-options path already did by hand
        (``_resolve_group_options``'s ``env_scope``).
        """
        if section:
            return f"{section}_{key}".upper().replace("-", "_").replace(".", "_")
        return key.upper().replace("-", "_").replace(".", "_")


class RemoteSource:
    """Resolves configuration values from remote providers via annotations.

    Takes a registry of remote providers and a dict mapping config keys
    to their source annotations. Resolves annotations by fetching from
    the appropriate remote provider with a 30-second timeout.
    """

    @property
    def source_type(self) -> str:
        """Return 'remote' source type identifier."""
        return "remote"

    @property
    def source_id(self) -> str:
        """Return the provider identifier string."""
        return self._source_id

    def __init__(
        self,
        registry: ProviderRegistry,
        annotations: dict[str, list[SourceAnnotationLike]],
        *,
        source_id: str = "remote",
        event_bus: EventBus | None = None,
    ) -> None:
        """Initialize the remote source.

        Args:
            registry: Provider registry for looking up remote providers.
            annotations: Dict mapping config keys (in "section.key" or "key"
                format) to their list of SourceAnnotation fallback chains.
            source_id: Identifier for this source (default: "remote").
            event_bus: Optional EventBus for emitting resolution events.
        """
        self._registry = registry
        self._annotations = annotations
        self._source_id = source_id
        self._event_bus = event_bus
        self._cache: dict[str, str] = {}
        self._resolved: set[str] = set()

    def _emit(self, event_name: str, **payload: Any) -> None:
        """Emit a structured event if an event bus is configured."""
        if self._event_bus is not None:
            resource = payload.pop("resource", "")
            self._event_bus.emit(event_name, resource=resource, **payload)

    def get(self, key: str, section: str | None = None) -> Any | None:
        """Retrieve a value by resolving its remote annotation.

        Raises:
            AnnotationResolutionError: If all sources in the fallback chain fail.
            UnregisteredProviderError: If a referenced provider is not registered.
            RemoteTimeoutError: If a fetch exceeds 30 seconds.
        """
        lookup_key = self._build_lookup_key(key, section)

        if lookup_key not in self._annotations:
            return None

        if lookup_key in self._resolved:
            return self._cache.get(lookup_key)

        chain = self._annotations[lookup_key]
        value = self._resolve_chain(lookup_key, chain)
        self._cache[lookup_key] = value
        self._resolved.add(lookup_key)
        return value

    def has(self, key: str, section: str | None = None) -> bool:
        """Check if an annotation exists for this key."""
        lookup_key = self._build_lookup_key(key, section)
        return lookup_key in self._annotations

    def keys(self, section: str) -> set[str]:
        """Return all keys available for the given section."""
        prefix = f"{section}."
        return {k[len(prefix) :] for k in self._annotations if k.startswith(prefix)}

    def _resolve_chain(self, key: str, chain: list[SourceAnnotationLike]) -> str:
        """Resolve a fallback chain of annotations.

        Tries each annotation in order. Returns the first successfully
        resolved value.

        Raises:
            AnnotationResolutionError: If all sources fail.
        """
        self._emit(
            "config.annotation.resolve.start",
            resource=key,
            key=key,
            chain_length=len(chain),
        )
        annotation_start = time.perf_counter()
        failures: list[AnnotationResolutionFailure] = []
        attempts = 0

        for annotation in chain:
            attempts += 1
            error_annotation = SourceAnnotation(
                provider=annotation.provider,
                reference=annotation.reference,
            )
            try:
                provider = self._registry.get_remote_provider(annotation.provider)
            except (UnregisteredProviderError, Exception):
                failures.append(
                    AnnotationResolutionFailure(
                        annotation=error_annotation,
                        error_type="not_registered",
                        message=f"Provider '{annotation.provider}' is not registered",
                    )
                )
                continue

            if not provider.is_ready():
                failures.append(
                    AnnotationResolutionFailure(
                        annotation=error_annotation,
                        error_type="not_ready",
                        message=f"Provider '{annotation.provider}' is not ready",
                    )
                )
                continue

            try:
                value = self._fetch_with_timeout(provider, annotation)
                duration_ms = (time.perf_counter() - annotation_start) * 1000
                self._emit(
                    "config.annotation.resolve.end",
                    resource=key,
                    key=key,
                    winning_provider=annotation.provider,
                    attempts=attempts,
                    duration_ms=duration_ms,
                )
                return value
            except RemoteTimeoutError:
                failures.append(
                    AnnotationResolutionFailure(
                        annotation=error_annotation,
                        error_type="timeout",
                        message=f"Fetch timed out after {_REMOTE_TIMEOUT}s",
                    )
                )
            except Exception as exc:
                failures.append(
                    AnnotationResolutionFailure(
                        annotation=error_annotation,
                        error_type="connection",
                        message=str(exc),
                    )
                )

        raise AnnotationResolutionError(key=key, failures=failures)

    def _fetch_with_timeout(
        self, provider: RemoteProvider, annotation: SourceAnnotationLike
    ) -> str:
        """Fetch a value from a remote provider with a 30s timeout.

        Raises:
            RemoteTimeoutError: If fetch exceeds 30 seconds.
        """
        provider_name = provider.identifier()
        self._emit(
            "config.remote.fetch.start",
            resource=provider_name,
            provider=provider_name,
            reference=annotation.reference,
        )
        fetch_start = time.perf_counter()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(provider.fetch, annotation.reference)
            try:
                result = future.result(timeout=_REMOTE_TIMEOUT)
                duration_ms = (time.perf_counter() - fetch_start) * 1000
                self._emit(
                    "config.remote.fetch.end",
                    resource=provider_name,
                    provider=provider_name,
                    reference=annotation.reference,
                    duration_ms=duration_ms,
                    success=True,
                )
                return result
            except concurrent.futures.TimeoutError:
                future.cancel()
                self._emit(
                    "config.remote.fetch.error",
                    resource=provider_name,
                    provider=provider_name,
                    reference=annotation.reference,
                    error_type="RemoteTimeoutError",
                    message=f"Fetch timed out after {_REMOTE_TIMEOUT}s",
                )
                raise RemoteTimeoutError(
                    provider=provider_name,
                    reference=annotation.reference,
                ) from None
            except Exception as exc:
                self._emit(
                    "config.remote.fetch.error",
                    resource=provider_name,
                    provider=provider_name,
                    reference=annotation.reference,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
                raise

    @staticmethod
    def _build_lookup_key(key: str, section: str | None) -> str:
        """Build a lookup key from section and key."""
        if section:
            return f"{section}.{key}"
        return key


class FileSource:
    """Discovers, parses, and deep-merges configuration files.

    Uses a FileResolver (e.g., ResourceLocator) to discover files, a
    FormatProvider registry to select the appropriate parser for each file,
    and deep_merge to combine results in priority order.
    """

    @property
    def source_type(self) -> str:
        """Return 'file' source type identifier."""
        return "file"

    @property
    def source_id(self) -> str:
        """Return comma-separated discovered file paths."""
        return ", ".join(self._discovered_paths)

    @property
    def per_file_values(self) -> list[tuple[str, dict[str, Any]]]:
        """Return each parsed file's own config, in discovery order.

        Discovery order is priority order: earlier entries win the merge.
        Only files that had a matching FormatProvider appear here, so this
        list is not index-aligned with ``_discovered_paths`` — the path
        travels in the tuple.

        Delivery layers use this to attribute a resolved value to the
        specific file that contributed it; ``get``/``has``/``keys`` still
        answer from the merged view.
        """
        return [(path, config) for path, config in self._per_file_configs]

    @property
    def file_infos(self) -> list[ConfigFileInfo]:
        """Return every discovered file with its role and merge rank.

        Includes INERT files (present, but belonging to another
        environment) and unparsed ones, so a delivery layer can explain why
        a file that plainly exists is not affecting anything.
        """
        return list(self._file_infos)

    def __init__(
        self,
        path_resolver: FileResolver,
        format_providers: dict[str, FormatProvider] | Any = None,
        pattern: str = "config.*",
        *,
        filename_regex: str | None = None,
        registry: Any = None,
        event_bus: EventBus | None = None,
        environment: str | None = None,
        require_slot: bool = False,
    ) -> None:
        """Initialize the file source.

        Discovers files using the path resolver and parses them immediately.
        Files are deep-merged in priority order (earlier-discovered files
        have higher priority).

        Args:
            path_resolver: Object with resolve(pattern) -> list[str] method.
            format_providers: Dict mapping extension (e.g., ".toml") to FormatProvider,
                or a ProviderRegistry instance (will call list_format_providers()).
            pattern: Glob pattern for filename matching (default: "config.*").
            filename_regex: Optional regex matched against basenames. When
                set, discovery uses a broad glob and this regex filters the
                candidates, so custom ``ConfigSources.file_pattern`` values
                (e.g. ``^settings\\.(\\w+)\\.toml$``) are honored.
            registry: Alias for format_providers when passing a ProviderRegistry.
            event_bus: Optional EventBus for emitting parse events.
            environment: The active environment name, selecting which
                ``config.<slot>.<ext>`` overlay is merged on top of
                ``config.base.<ext>``. ``None`` (the default) disables
                banding entirely: every file merges in discovery order,
                which is the correct behavior for a generic file-merging
                source that has no notion of a "base".
            require_slot: Drop candidates with no ``<slot>`` segment, so an
                unslotted ``config.toml`` is not read. Off by default because
                this source is a generic file merger; the kernel turns it on
                because kernel *discovery* anchors only on
                ``config.<slot>.<ext>``, and a reader that accepts more than
                the anchor does makes the same file count or not depending on
                whether a slotted sibling happens to sit beside it. Only the
                slot is checked here; which extensions count is decided by the
                registered format providers, on both this side and the anchor's.
        """
        self._path_resolver = path_resolver
        self._pattern = pattern
        self._require_slot = require_slot
        self._filename_regex = (
            re.compile(filename_regex) if filename_regex is not None else None
        )
        self._event_bus = event_bus
        self._environment = environment
        self._discovered_paths: list[str] = []
        self._merged_config: dict[str, Any] = {}
        self._per_file_configs: list[tuple[str, dict[str, Any]]] = []
        self._file_infos: list[ConfigFileInfo] = []

        # Resolve format_providers from either positional arg or registry kwarg
        providers = format_providers if format_providers is not None else registry
        if providers is None:
            self._format_providers: dict[str, FormatProvider] = {}
        elif isinstance(providers, dict):
            self._format_providers = providers
        elif hasattr(providers, "list_format_providers"):
            self._format_providers = providers.list_format_providers()
        else:
            self._format_providers = {}

        self._load()

    def _emit(self, event_name: str, **payload: Any) -> None:
        """Emit a structured event if an event bus is configured."""
        if self._event_bus is not None:
            resource = payload.pop("resource", "")
            self._event_bus.emit(event_name, resource=resource, **payload)

    def _section_data(self, section: str) -> dict[str, Any] | None:
        """The table for ``section``, accepting the Python spelling too.

        Sections are job names, which are canonical (``env-cfg``), but a config
        file may reasonably spell the section the way the function is spelled
        (``[env_cfg]``). Both denote the same job, so both are read — the same
        total-function rule the CLI and the job graph apply to names.

        The canonical spelling is preferred when a file somehow carries both.
        """
        data = self._merged_config.get(section)
        if isinstance(data, dict):
            return data

        for candidate in (section.replace("-", "_"), section.replace("_", "-")):
            if candidate == section:
                continue
            data = self._merged_config.get(candidate)
            if isinstance(data, dict):
                return data

        # A dotted section is a *nested* table: TOML parses `[deploy.web]` into
        # `{"deploy": {"web": {...}}}`, which no flat lookup above can reach.
        # Group option paths are dotted (`deploy.web`), and `[deploy.web]` is
        # how anyone would write that section — silently resolving nothing is
        # exactly the failure this file warns about a few lines up. A flat key
        # spelled with a literal dot still wins, so this is purely additive.
        if "." in section:
            walked: Any = self._merged_config
            for part in section.split("."):
                if not isinstance(walked, dict):
                    return None
                walked = walked.get(part)
            if isinstance(walked, dict):
                return walked
        return None

    def get(self, key: str, section: str | None = None) -> Any | None:
        """Retrieve a value from the merged file configuration."""
        if section:
            section_data = self._section_data(section)
            return section_data.get(key) if section_data is not None else None
        return self._merged_config.get(key)

    def has(self, key: str, section: str | None = None) -> bool:
        """Check if the merged config contains the key."""
        if section:
            section_data = self._section_data(section)
            return section_data is not None and key in section_data
        return key in self._merged_config

    def keys(self, section: str) -> set[str]:
        """Return all keys available for the given section.

        Goes through ``_section_data`` like ``get``/``has`` do, so a section
        this source can *read* is never one it reports as empty — an
        inconsistency that would make ``resolve_section`` skip keys ``resolve``
        would happily return.
        """
        section_data = self._section_data(section)
        return set(section_data.keys()) if section_data is not None else set()

    def _load(self) -> None:
        """Discover and parse all configuration files, then deep-merge."""
        if self._filename_regex is not None:
            candidates = self._path_resolver.resolve("*")
            paths = [
                p
                for p in candidates
                if self._filename_regex.match(Path(p).name) and Path(p).is_file()
            ]
        else:
            paths = self._path_resolver.resolve(self._pattern)
            if self._require_slot:
                paths = [p for p in paths if parse_slot(p) is not None]
        self._discovered_paths = paths
        self._per_file_configs = []
        self._file_infos = []

        if not paths:
            return

        parsed_configs: list[tuple[str, dict[str, Any]]] = []
        unparsed: set[str] = set()
        for path in paths:
            extension = Path(path).suffix
            provider = self._format_providers.get(extension)
            if provider is None:
                unparsed.add(path)
                continue

            provider_name = type(provider).__name__
            self._emit(
                "config.file.parse.start",
                resource=path,
                path=path,
                extension=extension,
                provider=provider_name,
            )
            parse_start = time.perf_counter()

            config = provider.parse(path)

            duration_ms = (time.perf_counter() - parse_start) * 1000
            key_count = sum(
                len(v) if isinstance(v, dict) else 1 for v in config.values()
            )
            self._emit(
                "config.file.parse.end",
                resource=path,
                path=path,
                provider=provider_name,
                duration_ms=duration_ms,
                key_count=key_count,
            )
            parsed_configs.append((path, config))

        self._per_file_configs = parsed_configs
        self._merged_config = self._merge(parsed_configs, unparsed)

    def _merge(
        self,
        parsed_configs: list[tuple[str, dict[str, Any]]],
        unparsed: set[str],
    ) -> dict[str, Any]:
        """Deep-merge parsed files and record each file's role and rank.

        Precedence is **directory-major, band-minor**: the nearest directory
        wins overall, and within a single directory an environment overlay
        beats that directory's base. This preserves the documented
        project > parents > global ladder — a project's ``config.base`` must
        still outrank a global ``config.prod``, because the ladder is about
        *whose* config it is, not which environment it names.

        With ``environment=None`` every file classifies as BASE and the
        directory grouping alone reproduces the original discovery-order
        merge — the same code path, not a second implementation.
        """
        values_by_path = dict(parsed_configs)

        # resolve() returns paths grouped by directory in priority order;
        # dict preserves insertion order, so this keeps that grouping.
        by_directory: dict[str, list[str]] = {}
        for path in self._discovered_paths:
            by_directory.setdefault(str(Path(path).parent), []).append(path)

        roles = {
            path: classify(path, self._environment) for path in self._discovered_paths
        }

        merged: dict[str, Any] = {}
        merge_order: list[str] = []
        # Lowest-priority directory first, so higher-priority ones overwrite.
        for directory in reversed(list(by_directory)):
            for band in (ConfigFileRole.BASE, ConfigFileRole.OVERLAY):
                # Earlier-discovered files outrank later ones within a
                # directory, so merge them last.
                for path in reversed(by_directory[directory]):
                    if roles[path] is not band or path not in values_by_path:
                        continue
                    merged = deep_merge(merged, values_by_path[path])
                    merge_order.append(path)

        # Rank contributing files by how strongly they win: the last file
        # merged overwrites everything before it, so it ranks first.
        precedence = {path: rank for rank, path in enumerate(reversed(merge_order))}

        self._file_infos = [
            ConfigFileInfo(
                path=path,
                environment_slot=parse_slot(path),
                role=roles[path],
                precedence=precedence.get(path),
                values=values_by_path.get(path, {}),
                parsed=path not in unparsed,
            )
            for path in self._discovered_paths
        ]

        if self._environment is not None:
            inert = [
                p for p in self._discovered_paths if roles[p] is ConfigFileRole.INERT
            ]
            matched = [
                p for p in self._discovered_paths if roles[p] is ConfigFileRole.OVERLAY
            ]
            # A typo'd ENVIRONMENT (prd) is not an error — an environment
            # with no overlay file is legitimate — but it must be
            # diagnosable, so report rather than raise.
            self._emit(
                "config.environment.resolved",
                resource=self._environment,
                name=self._environment,
                matched_slots=[parse_slot(p) for p in matched],
                inert_slots=[parse_slot(p) for p in inert],
            )

        return merged


class DefaultSource:
    """Exposes default values as the lowest-priority configuration source.

    Provides fallback values from application defaults or Pydantic model
    field defaults.
    """

    @property
    def source_type(self) -> str:
        """Return 'default' source type identifier."""
        return "default"

    @property
    def source_id(self) -> str:
        """Return 'defaults' source identifier."""
        return "defaults"

    def __init__(self, defaults: dict[str, Any]) -> None:
        """Initialize with default values.

        Args:
            defaults: Dict of default values. Can be flat (key → value)
                or nested (section → {key → value}) for sectioned configs.
        """
        self._defaults = defaults

    def get(self, key: str, section: str | None = None) -> Any | None:
        """Retrieve a default value for the given key."""
        if section:
            section_data = self._defaults.get(section)
            if isinstance(section_data, dict):
                return section_data.get(key)
            return None
        return self._defaults.get(key)

    def has(self, key: str, section: str | None = None) -> bool:
        """Check if a default exists for the key."""
        if section:
            section_data = self._defaults.get(section)
            if isinstance(section_data, dict):
                return key in section_data
            return False
        return key in self._defaults

    def keys(self, section: str) -> set[str]:
        """Return all keys available for the given section."""
        section_data = self._defaults.get(section)
        if isinstance(section_data, dict):
            return set(section_data.keys())
        return set()
