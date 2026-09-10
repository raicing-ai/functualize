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
    from functualize._types.protocols import (
        JobProvider,
        JobTransform,
        ModulePreFilter,
    )

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

    ``app.add_job_provider()`` remains the imperative equivalent -- the path a
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

    entry_point_group: str = "functualize.plugins"
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
