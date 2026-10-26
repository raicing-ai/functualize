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

import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._discovery import Job
from functualize._primitives.entry_point_groups import PLUGINS

if TYPE_CHECKING:
    from functualize._config import ResolutionChain
    from functualize._config.settings_resolution import ResolvedSettings
    from functualize._types.protocols import (
        JobProvider,
        JobTransform,
        ModulePreFilter,
    )
    from functualize._types.settings import AppSettingsSchema

__all__ = [
    "CliConfig",
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
    job_providers: list[JobProvider | tuple[JobProvider, list[JobTransform]]] | None = (
        None
    )
    """Providers to add to the resolution pipeline, in declaration order.

    Each entry is a ``JobProvider`` or a ``(provider, [transform, ...])`` pair.
    They are added *after* whatever the boot path derives from ``directories``
    and ``functions``, so the pipeline order matches the order these fields are
    declared in.

    The type was ``list[Any]`` for as long as the field was read by nothing:
    ``boot_static`` and ``boot_standard`` both ignored it, so a caller who
    declared a provider here got an empty job list and no diagnostic. It is now
    honoured on both paths by ``_app.boot.wire_declared_job_providers``, and the
    annotation says what the docstring always promised.

    ``app.extensions.add_job_provider()`` remains the imperative equivalent -- the path a
    plugin uses from inside its ``__call__(app)``, where there is no
    ``JobSources`` left to declare into.
    """

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
    remote: bool = False
    """Whether to resolve declared remote annotations from the local vault.

    Set by ``remote_first()``. It exists because a *bare* ``None`` chain cannot
    distinguish "build the classic chain" from "build the remote chain" -- and
    that ambiguity is exactly how ``remote_first()`` came to resolve silently
    as ``classic()`` for its whole shipped life (ADR-016). The intent is now a
    fact in the data rather than an inference from absence.
    """

    vault_max_age: str | None = None
    """How old the vault may be before every run warns, e.g. ``"7d"``.

    None means unconfigured, which resolves to the ``"24h"`` default. The
    distinction matters: ``$FUNCTUALIZE_VAULT_MAX_AGE`` outranks this field, and
    a field that defaulted to ``"24h"`` could not be told apart from an author
    who wrote ``max_age="24h"`` on purpose.

    Only consulted when :attr:`remote` is set. Exceeding it warns and the run
    continues -- offline work stays possible (ADR-016).

    **The literal default lives in** ``_config.vault.DEFAULT_MAX_AGE``, not
    here, and is deliberately not imported: ``_config.vault`` pulls in
    ``cryptography``, and this module is on the cold boot path for every app
    including the ones that never open a vault. ``tests/config/
    test_vault_staleness.py`` asserts the two agree, so the duplication cannot
    drift.
    """

    vault_keyring_timeout: str | None = None
    """How long a run may wait on the OS keyring, e.g. ``"30s"`` or ``"2m"``.

    None means unconfigured, which resolves to a 30-second wait.
    ``$FUNCTUALIZE_VAULT_KEYRING_TIMEOUT`` outranks this field. The same
    duration spelling as ``vault_max_age``; a bare number is refused and a
    warning is logged, falling back to the default.

    Read lazily, only when a run is about to consult the keyring — a run
    that resolves no key never reads it, and neither does boot.

    **The literal default lives in** ``_config.vault.DEFAULT_KEYRING_TIMEOUT``,
    not here, for the same cold-boot reason as ``vault_max_age`` above, and
    ``tests/config/test_vault_keyring_timeout.py`` asserts the two agree.
    """

    settings: AppSettingsSchema | None = None
    """The settings vocabulary to resolve; None uses the built-in declaration."""
    resolved: ResolvedSettings | None = None
    """A supplied snapshot, useful when an embedding host already resolved it."""


@dataclass(frozen=True)
class PluginSources:
    """Plugin discovery settings.

    Controls how plugins are found and loaded:
    - entry_point_group: entry point group name for plugin discovery
    - explicit_plugins: list of pre-instantiated plugin objects
    - disabled: list of plugin names to skip during discovery
    - ambient_directory: whether the ``.functualize/plugins/`` convention
      directory in the *working* directory is loaded

    ``ambient_directory`` draws the same line ``adjacent-defects/T14`` drew for
    job discovery: a directory the caller **declared** is read, and the one the
    working directory supplies **implicitly** is not, when the caller asked for
    one file rather than for a project. `[tool.functualize] plugins_directories`
    is declared and is unaffected; only the convention fallback is refused.

    It defaults to ``True``, because a project app in its own directory is
    exactly who that convention is for. `func <file>.py <job>` sets it
    ``False``: the cwd there is wherever the user's shell happened to be, and
    a plugin module's top level runs during app construction — so a stray file
    under ``./.functualize/plugins/`` could take over an invocation that named
    a different program entirely.
    """

    entry_point_group: str = PLUGINS
    explicit_plugins: list[Any] | None = None
    disabled: list[str] | None = None
    ambient_directory: bool = True


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

    #: A caller-supplied pre-import predicate, for a host whose jobs no
    #: ``require_*`` setting can describe -- methods on a class, say.
    #:
    #: **Composed, not substituted.** It is ANDed onto the stack the nine
    #: settings above build, and runs last: its cost is unknown, so the cheap
    #: built-in checks short-circuit ahead of it.
    #:
    #: Its ``fingerprint()`` -- never the object -- is what joins the cache
    #: digest. The cache persists *negative* pre-filter decisions and replays
    #: them while the fingerprint matches, and ``str()`` of a callable carries
    #: its address, so identity would re-digest on every boot. See
    #: :class:`functualize.plugin.ModulePreFilter`.
    #:
    #: Note this is the one field that is not guaranteed hashable: the other
    #: nine are strings and tuples, and a filter object is hashable only if
    #: its own type is.
    pre_filter: ModulePreFilter | None = None


# =============================================================================
# CliConfig — the CLI layer's projection of the shared settings resolution
# =============================================================================

_VALID_OUTPUT_FORMATS = frozenset({"rich", "plain", "json"})

# Alias name validation pattern: starts with letter, then alphanumeric/underscore/dash
_ALIAS_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
_ALIAS_MAX_LENGTH = 32


def _warn(msg: str) -> None:
    """Emit a warning to stderr."""
    print(f"Warning: {msg}", file=sys.stderr)


def _validate_aliases(aliases_raw: Mapping[str, Any]) -> dict[str, str]:
    """Validate alias names against pattern and max length, warn on invalid."""
    validated: dict[str, str] = {}
    for name, target in aliases_raw.items():
        if not isinstance(target, str):
            _warn(f"alias '{name}': value must be a string, skipping")
            continue
        if len(name) > _ALIAS_MAX_LENGTH:
            _warn(
                f"alias '{name}': name exceeds {_ALIAS_MAX_LENGTH} characters, skipping"
            )
            continue
        if not _ALIAS_PATTERN.match(name):
            _warn(
                f"alias '{name}': name does not match pattern "
                f"[a-zA-Z][a-zA-Z0-9_-]*, skipping"
            )
            continue
        validated[name] = target
    return validated


def _absolute_import_libs(items: Any, anchor: Path) -> tuple[str, ...]:
    """Absolutise import_lib entries against ``anchor``, deduplicating resolved paths."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items or ():
        path = Path(str(item))
        if not path.is_absolute():
            path = anchor / path
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return tuple(result)


@dataclass(frozen=True)
class CliConfig:
    """Fully resolved CLI tool configuration (merged from all sources)."""

    discovery: DiscoveryConfig
    output: str  # "rich" | "plain" | "json"
    show_timing: bool
    aliases: dict[str, str]
    dotenv: bool
    dotenv_path: str | None
    scan_depth: int = (
        0  # Resolved from config escalation (CLI flag takes precedence externally)
    )
    import_libs: tuple[str, ...] = ()
    anchor: Path | None = None  # Directory containing the nearest config file
    # `[vault] keyring_timeout`, unparsed: the app layer parses it, and only
    # when it is about to consult the keyring.
    vault_keyring_timeout: str | None = None

    @classmethod
    def from_settings(cls, settings: ResolvedSettings) -> CliConfig:
        """Project a :class:`ResolvedSettings` onto this CLI-facing view."""
        values = settings.values

        output = str(values.get("cli.output", "rich"))
        if output not in _VALID_OUTPUT_FORMATS:
            _warn(
                f"[cli].output: invalid value '{output}', "
                f"must be one of {sorted(_VALID_OUTPUT_FORMATS)}, falling back to 'rich'"
            )
            output = "rich"

        try:
            scan_depth = int(values.get("discovery.scan_depth", 0))
        except (TypeError, ValueError):
            scan_depth = 0

        anchor = next(
            (layer.path.parent for layer in settings.layers if layer.kind == "project"),
            None,
        )

        aliases_raw: dict[str, Any] = {}
        for layer in settings.layers:
            layer_aliases = layer.values.get("aliases")
            if isinstance(layer_aliases, dict):
                for name, target in layer_aliases.items():
                    aliases_raw.setdefault(name, target)

        decorators = values.get("discovery.require_job_decorators")
        discovery = DiscoveryConfig(
            exclude_patterns=tuple(values.get("discovery.exclude_patterns", ()) or ()),
            extra_directories=tuple(
                values.get("discovery.extra_directories", ()) or ()
            ),
            require_file_prefix=values.get("discovery.require_file_prefix"),
            require_file_postfix=values.get("discovery.require_file_postfix"),
            require_file_import=values.get("discovery.require_file_import"),
            require_file_marker=values.get("discovery.require_file_marker"),
            require_job_decorators=tuple(decorators)
            if decorators is not None
            else None,
            require_job_prefix=values.get("discovery.require_job_prefix"),
            require_job_postfix=values.get("discovery.require_job_postfix"),
        )

        vault_keyring_timeout = None
        if settings.provenance.get("vault.keyring_timeout") not in (None, "default"):
            vault_keyring_timeout = values.get("vault.keyring_timeout")

        return cls(
            discovery=discovery,
            output=output,
            show_timing=bool(values.get("cli.show_timing", False)),
            aliases=_validate_aliases(aliases_raw),
            dotenv=bool(values.get("dotenv", False)),
            dotenv_path=values.get("dotenv_path"),
            scan_depth=scan_depth,
            import_libs=_absolute_import_libs(
                values.get("import_libs", ()), anchor or Path.cwd()
            ),
            anchor=anchor,
            vault_keyring_timeout=vault_keyring_timeout,
        )

    def config_sources(self) -> ConfigSources:
        """The `ConfigSources` every `func` door hands its app.

        One construction rather than one per door, so a setting added here
        reaches every entry point at once — four doors agreeing and a fifth
        not is a defect this repository has already shipped.
        """
        return ConfigSources(
            dotenv=self.dotenv,
            dotenv_path=self.dotenv_path,
            vault_keyring_timeout=self.vault_keyring_timeout,
        )


def resolve_app_settings(
    cwd: Path | None = None,
    *,
    flags: Mapping[str, Any] | None = None,
    global_dir: Path | None = None,
) -> ResolvedSettings:
    """Resolve the ``func`` settings schema against ``cwd`` and ``flags``."""
    from functualize._config.settings_resolution import resolve_settings
    from functualize._types.functualize_settings import FUNCTUALIZE_SETTINGS

    return resolve_settings(
        FUNCTUALIZE_SETTINGS,
        cwd or Path.cwd(),
        flags=flags,
        global_dir=global_dir,
    )
