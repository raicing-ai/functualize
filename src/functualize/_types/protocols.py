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
- ModulePreFilter: Pre-import discovery predicates
- VaultKeyProvider: Where the local secrets vault's key comes from
- AgentStepExecutor: Runs a workflow step by delegating it to an agent

The agent step port carries its own payload vocabulary — ``AgentCapability``
(what an executor promises it can enforce), ``AgentStepContext`` (what it is
given) and ``AgentStepResult`` (what it returns). Those three live here rather
than in a module of their own because the port is their only consumer, and an
implementation that imports the Protocol needs the other three names at the
same moment.

Re-exported from functualize._types.interactivity:
- Surface: renders a job's events
- PromptCollector: answers a job's prompts
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
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
    from pathlib import Path

    from functualize._types.descriptors import JobDescriptor
    from functualize._types.run_request import RunRequest


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
class ModulePreFilter(Protocol):
    """Decide whether a module is worth importing, without importing it.

    Discovery reads a candidate file's AST before executing it, and a filter
    answers from that alone. The built-in filters
    (``_primitives/pre_filter.py``) express the ``require_*`` settings; a host
    whose jobs are, say, methods on classes cannot express itself in any of
    those and supplies its own.

    Implementations satisfy this structurally -- there is nothing to inherit,
    and ``_primitives`` does not import this module's package upward.

    ``fingerprint()`` is not decorative. The discovery cache persists
    *negative* pre-filter decisions and replays them, trusting them only while
    the discovery fingerprint matches. A caller-supplied predicate cannot join
    that hash by identity: ``_normalize_discovery_value`` renders an unknown
    value with ``str()``, and ``str()`` of a function carries its address, so
    the digest would differ on every boot and invalidate the cache on every
    run. Omitting it instead reproduces the X1-X4 replay defect that
    ``CACHE_VERSION`` 15->16->17 and ADR-010/ADR-011 exist to close. A stable,
    caller-declared string is the only option that keeps the cache both warm
    and correct.
    """

    def should_import(self, source_file: Path) -> bool:
        """Return whether this module should be imported for discovery."""
        ...

    def fingerprint(self) -> str:
        """Stable identity of this filter's logic, for cache invalidation.

        Must be identical across processes for identical behaviour, and must
        change when the predicate's behaviour changes. A host that forgets to
        bump it gets a stale cache -- the same contract as any cache key, and
        the same failure the ``require_*`` fields already have when a config
        is edited without invalidation.
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


@runtime_checkable
class VaultKeyProvider(Protocol):
    """Protocol for supplying the key that opens the local secrets vault.

    The vault caches values synced from remote providers (AWS Secrets Manager,
    Bitwarden, …) so that jobs resolve configuration without touching the
    network. It is encrypted at rest; this protocol is *where the key comes
    from*, and it is a seam rather than a fixed source so that an OS keychain,
    a cloud KMS, a password manager or a hosted control plane are all the same
    shape (ADR-016).

    Two implementations ship: an environment-variable provider
    (non-interactive) and an OS keychain provider (interactive).

    **Resolution order is part of the contract.** Non-interactive providers are
    consulted first, and interactive ones only when no key was found *and* a
    TTY is present. Reversed, an unattended run — CI, Lambda, a container —
    would block forever on a prompt nobody can answer.
    """

    def identifier(self) -> str:
        """Return the short provider name, e.g. 'env' or 'keychain'."""
        ...

    def interactive(self) -> bool:
        """Whether obtaining the key may prompt, block, or require a TTY.

        A provider returning True is never consulted on an unattended run.
        """
        ...

    def is_available(self) -> bool:
        """Whether this provider can supply a key in this environment.

        Reports capability, not success: a keychain provider returns False
        where no keyring exists, rather than raising when asked for a key.
        """
        ...

    def get_key(self, project_id: str) -> bytes | None:
        """Return the 32-byte key for a project's vault, or None.

        Args:
            project_id: The project identity the vault is scoped to. Vaults are
                per-project, so a provider may hold a distinct key per project.

        Returns:
            Exactly 32 bytes, or None when this provider has no key to offer.
            Returning None is normal and lets resolution continue; it is not an
            error.
        """
        ...


class AgentCapability(StrEnum):
    """A constraint an executor promises it can enforce on a step's behalf.

    Declared by the executor, required by the step, and compared **before the
    walk starts**. A step whose requirement the executor cannot honour is
    refused rather than run, because running it would leave the constraint
    silently unenforced — a workflow that appears to have restricted tools it
    left wide open.

    A ``StrEnum`` rather than ``(str, Enum)`` for the same reason
    :class:`~functualize._types.outcome.Family` is one: the contracts spell it
    ``(str, Enum)``, and on this interpreter that is the same type with a
    ``UP042`` warning attached.
    """

    ENFORCES_TOOL_ALLOWLIST = "enforces_tool_allowlist"
    PRESERVES_ACTIVE_TIME_BUDGET = "preserves_active_time_budget"
    SUPPORTS_VISIBLE_OUTPUT = "supports_visible_output"


@dataclass(frozen=True)
class AgentStepContext:
    """Everything an executor is given to perform one agent step.

    It **carries** the run's :class:`~functualize._types.run_request.RunRequest`
    rather than restating its fields: the request already holds where the run
    came from and what it was asked for, and a second shape for those would be
    a second answer to where a run came from.

    Attributes:
        request: The request the run reaching this step was built from.
        step_name: The declaring node's name — the step being executed.
        instructions: What the step asks the agent to do.
        tools: The tool allowlist the step declared, normalized to a tuple. An
            empty tuple means the step declared no constraint, which is not the
            same statement as "this step may use no tools".
        inputs: The values the step binds into the agent's work.
        time_budget_s: The step's active-time budget in seconds, when it
            declared one.
    """

    request: RunRequest
    step_name: str
    instructions: str
    tools: tuple[str, ...]
    inputs: Mapping[str, Any]
    time_budget_s: float | None


@dataclass(frozen=True)
class AgentStepResult:
    """What an executor returns for one agent step.

    Attributes:
        value: The step's result, recorded as the step's outcome.
        tool_calls: The tool invocations the agent reported, in order. Empty
            for an executor that does not surface them — an audit trail, not a
            contract, so nothing may require a non-empty tuple.
    """

    value: Any
    tool_calls: tuple[Mapping[str, Any], ...] = ()


@runtime_checkable
class AgentStepExecutor(Protocol):
    """Protocol for running a workflow step by delegating it to an agent.

    Registered by an app method — ``app.register_agent_step_executor`` — and
    **never auto-discovered**: auto-discovery is how a surface acquires
    behaviour nobody declared. ``GateResolver`` is the template, down to the
    registration door.

    The engine asks an executor only for steps that named it, or for every
    agent step when exactly one executor is registered. Nothing falls back to a
    different executor, and nothing falls back to a human.

    ``capabilities`` is a promise, and a missing flag is a **refusal**, not a
    default: a step requiring
    :attr:`AgentCapability.ENFORCES_TOOL_ALLOWLIST` from an executor that does
    not declare it fails validation, because running anyway would grant every
    tool the step meant to leave out.

    Implementations are checked with ``isinstance``; ``issubclass`` raises
    ``TypeError`` on this Protocol, because ``name`` and ``capabilities`` are
    data members — a fact no type checker will point out at the call site.
    """

    #: The name a step refers to this executor by, and the key it is looked up
    #: under in ``_engine.agent_providers.EXECUTOR_PROVIDERS``.
    name: str

    #: What this executor can enforce. Every flag absent from this set is a
    #: capability a step requiring it will be refused for.
    capabilities: frozenset[AgentCapability]

    def execute(self, ctx: AgentStepContext) -> AgentStepResult:
        """Perform one agent step.

        Args:
            ctx: The step, its inputs, and the request that reached it.

        Returns:
            The step's result.

        Raises:
            Any exception to fail the step. How a failure is routed around a
            step is not this port's business, and no exception here is
            answered by asking a human instead.
        """
        ...


__all__ = [
    # Protocols
    "AdapterPlugin",
    "AgentStepExecutor",
    "FormatProvider",
    "JobProvider",
    "JobTransform",
    "ModulePreFilter",
    "PluginWithShutdown",
    "Source",
    "VaultKeyProvider",
    # Agent step port payload vocabulary
    "AgentCapability",
    "AgentStepContext",
    "AgentStepResult",
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
