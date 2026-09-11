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
- EngineHost: What the execution engine needs from outside itself
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

    from functualize._types.descriptors import JobDescriptor, RegisteredJob
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


@runtime_checkable
class EngineHost(Protocol):
    """Everything the engine needs from outside itself, wired once.

    The execution engine is **complete at construction**. It is handed a host
    and reads it; it is no longer finished afterwards by owners that write
    private fields into it and read back out through a back-reference. There is
    no supported way to modify an engine once it is built — which is the point,
    because "open for modification" then stops being a review note and becomes
    structurally false for this axis.

    :class:`~functualize.app.core.FunctualizeApp` is the host that ships, and
    ``_app/boot.build_engine(host)`` is the one construction site both boot
    paths call. An engine may also be built with no host at all (embedding,
    unit tests); every member here then has a defined absent answer, which is
    why the engine's own accessors are None-tolerant rather than reaching for
    an attribute that may not be there.

    **Members ask; none of them lends.** ``registered_jobs()`` returns a
    read-only mapping: the app registry used to hand the engine its private
    dict by reference, so two objects shared mutable state with no contract
    between them, and only one of them knew it.

    Deliberately absent: everything the engine takes as a constructor argument
    already — the DI registry, the hook registry, the middleware chain, the
    event bus, the gate registry, the config factories. A port lists what must
    come *from outside*, not what it was handed at birth.
    """

    def get_descriptor(self, name: str) -> JobDescriptor | None:
        """The descriptor for ``name``, or None when nothing is registered.

        One call, replacing a walk from the kernel out through the app it was
        handed and into that app's registry.
        """
        ...

    def registered_jobs(self) -> Mapping[str, RegisteredJob]:
        """Every registered job, as a read-only mapping.

        Read-only on purpose: the engine asks, rather than being given the
        registry's private dict to mutate.
        """
        ...

    def replace_job(self, current: RegisteredJob, replacement: RegisteredJob) -> None:
        """Swap ``current`` for ``replacement`` wherever the host holds it.

        Materializing a lazily-registered job replaces the placeholder that
        carries the deferred import with one carrying the real function. The
        engine holds its own entry; the host holds the copy the rest of the app
        reads. This call is what keeps the two from diverging — a contract,
        where a shared dict was not.
        """
        ...

    def resolution_chain(self) -> Any:
        """The active config resolution chain.

        A method rather than a property because the app's sanctioned accessor
        has been one since the provenance panels began calling it, and a port
        that does not fit its implementation is the wrong port.

        Read live rather than captured: ``refresh()`` rebuilds the chain in
        place, and a captured copy would leave the engine resolving against a
        discarded one.
        """
        ...

    @property
    def fresh_root(self) -> Path:
        """Where this project's derived run state (fingerprints, history,
        workflow scopes) lives.

        One answer to a question three places in the kernel used to answer for
        themselves by asking the operating system — and answering it
        differently, which is why the durable run layer could not simply be
        added on top.
        """
        ...

    @property
    def max_invoke_depth(self) -> int:
        """The deepest chain of nested ``invoke()`` calls allowed.

        A property because it is resolved from configuration *after* the app
        exists, and the engine must see the resolved value rather than the
        constructor default it was built with.
        """
        ...

    @property
    def event_bus(self) -> Any:
        """The app's structured event bus, for ``RunContext.emit``/``on_event``."""
        ...

    def live_zone(self) -> Surface | None:
        """The surface that should host ``Live`` constructs, or None.

        Top of the pushed stack wins, then the first registered live-capable
        surface. None means ``Live`` no-ops, which is the correct answer in the
        kernel and on any surface without a live region.
        """
        ...

    def collector(self) -> PromptCollector | None:
        """The one surface that should answer a prompt, or None.

        None is not an error: it is what turns a would-be hang into a typed
        ``InputNotAvailable`` at the call site.
        """
        ...

    def push_surface(self, surface: Surface) -> None:
        """Push a phase-scoped surface onto the stack, for a ``TTY`` window.

        Paired with :meth:`pop_surface` so a crashing phase still unwinds
        before the next one starts.
        """
        ...

    def pop_surface(self, surface: Surface | None = None) -> None:
        """Pop that surface again — tolerant of an already-empty stack."""
        ...

    def scope_for(self, scope_id: str) -> Any:
        """The `WorkflowScope` named by ``scope_id``, created if it is new.

        The engine mints a scope for every run that arrives without one, which
        is where state lives — but *which* scope objects exist, and the
        `ON_SCOPE_CREATED` hook that announces a new one, are the host's
        business. Minting behind the host's back skipped the hook and left the
        app's registry empty, so a plugin watching for scopes saw none.

        Idempotent by id: asking twice returns the same object, which is what
        lets two runs naming one scope share it in-process.
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


def capability_value(capability: object) -> str:
    """The wire name of a capability, whatever spelling it arrived in.

    **Compare capabilities by value, never by member.** A plugin's executor is
    duck-typed — the registry accepts anything satisfying `AgentStepExecutor` —
    and the docs publish the bare strings, so a plugin declaring
    ``frozenset({"enforces_tool_allowlist"})`` is a legitimate executor. Set
    arithmetic between members and strings happens to work today only because
    :class:`AgentCapability` is a ``StrEnum`` and the ``str`` mixin's ``__eq__``
    and ``__hash__`` win the MRO. Under a plain ``Enum`` the same comparison
    reports a **false refusal** for a capability the executor did declare, and
    every test double in the suite uses the enum, so nothing would catch it
    (asp M-4).

    So the base stops being load-bearing: this function says what is meant, and
    a change to how the enum is spelled cannot silently invert a refusal.
    """
    value = getattr(capability, "value", capability)
    return value if isinstance(value, str) else str(value)


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
            **TRANSITIONAL(workflow-graph-semantics)** — always empty today.
            The port's single construction site passes an empty mapping,
            because binding an upstream node's output into a downstream step is
            the typed-outcome plumbing that feature builds; there is no other
            source for it. An executor may read it and will get nothing (asp
            M-3). Declared now rather than added later so the payload shape a
            plugin compiles against does not change under it.
        time_budget_s: The step's active-time budget in seconds, when it
            declared one.
    """

    request: RunRequest
    step_name: str
    instructions: str
    tools: tuple[str, ...]
    # TRANSITIONAL(workflow-graph-semantics): populated by nothing yet — see the
    # attribute note above.
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
            **TRANSITIONAL(durable-run-layer)** — the walker takes
            ``result.value`` and drops this, so an executor that fills it is
            writing the audit trail into nowhere. It lands when there is a run
            event stream to write it to; recording it in the step record first
            would put an unbounded, agent-controlled payload in the scope store
            (asp M-3).
    """

    value: Any
    # TRANSITIONAL(durable-run-layer): read by nothing yet — see the attribute
    # note above.
    tool_calls: tuple[Mapping[str, Any], ...] = ()


@runtime_checkable
class AgentStepExecutor(Protocol):
    """Protocol for running a workflow step by delegating it to an agent.

    Registered by an app method — ``app.extensions.register_agent_step_executor`` — and
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
    "EngineHost",
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
    "capability_value",
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
