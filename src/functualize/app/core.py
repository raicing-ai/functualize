"""FunctualizeApp public facade.

Thin public-facing class (≤300 LOC) that delegates boot orchestration to
``_app/boot`` and heavy internal logic to ``_app/impl``. All adapters
(CLI, HTTP, Lambda) connect via the facade methods defined here.

Facade methods:
- Job discovery: get_jobs, get_job
- Execution: execute
- DI registration: provide, provide_factory, provide_named
- Plugin commands: register_plugin_command, get_plugin_commands
- Observability: cache_stats, event_bus property
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from functualize._app.environment import DEFAULT_ENVIRONMENT
from functualize._types.enums import EnvironmentSource
from functualize._types.run_request import RunRequest, RunSurface
from functualize.app.config import (
    ConfigSources,
    DiscoveryConfig,
    ExecutionConfig,
    JobSources,
    PluginSources,
)

if TYPE_CHECKING:
    from functualize._app.models import PluginCommand
    from functualize._config import ResolutionChain
    from functualize._config.registry import ProviderRegistry
    from functualize._discovery.pipeline import ResolutionPipeline
    from functualize._discovery.registry import JobRegistry
    from functualize._engine.agent_step import AgentStepRegistry
    from functualize._engine.executor import JobExecutionEngine
    from functualize._engine.result import JobResult
    from functualize._events.bus import EventBus
    from functualize._events.hooks import HookRegistry
    from functualize._events.middleware_stack import MiddlewareStack
    from functualize._events.perf import PerfTimeline
    from functualize._gate._registry import GateRegistry
    from functualize._gate._resolver import GateResolver
    from functualize._plugins.domain_registry import DomainRegistry
    from functualize._plugins.loader import PluginLoader
    from functualize._primitives.di import DIRegistry
    from functualize._types.descriptors import (
        CacheInfo,
        ConfigFileInfo,
        JobDescriptor,
        RegisteredJob,
    )
    from functualize._types.protocols import (
        AgentStepExecutor,
        JobProvider,
        JobTransform,
    )
    from functualize.job._workflow_scope import WorkflowScope

DEFAULT_CONFIG_FILE_REGEX = r"^config\.(\w+)\.(\w+)$"

#: Sentinel written to a JobDescriptor's source/source_file by
#: register_dynamic_job — marks a job that came from code, not from a file.


class FunctualizeApp:
    """Application kernel — delivery-agnostic.

    Contains DI registry, execution engine, lifecycle management, discovery
    pipeline, config resolution, and RunContext construction. Adapters
    (CLI, HTTP, Lambda) connect via the facade methods.

    Constructor accepts grouped frozen dataclass configs:

        app = FunctualizeApp(
            "myapp",
            job_sources=JobSources(directories=["./jobs"]),
            config_sources=ConfigSources(dotenv=False),
            plugin_sources=PluginSources(entry_point_group="myapp.plugins"),
            execution=ExecutionConfig(max_invoke_depth=5),
        )

    Args:
        name: Application name (used for app dir fallback and logging).
        job_sources: Grouped job source configuration (JobSources()).
        config_sources: Configuration resolution settings (ConfigSources()).
        plugin_sources: Plugin discovery settings (PluginSources()).
        execution: Execution parameters (ExecutionConfig()).
    """

    # Both boot paths set these; the defaults keep active_environment() and
    # environment_source() answerable for a partially-constructed app (e.g.
    # a test double) rather than raising AttributeError.
    _environment: str = DEFAULT_ENVIRONMENT
    _environment_source: EnvironmentSource = EnvironmentSource.DEFAULT

    # ─── Boot-assigned attributes ────────────────────────────────────────
    # `__init__` delegates wiring to `_app.boot.boot_standard`/`boot_static`,
    # which assign these through the `app` parameter. A type checker only
    # infers instance attributes from assignments it can see *in this class*,
    # so without these declarations every read below is an `attr-defined`
    # error and every value reads back as `Any` — which then silently defeats
    # the return types of the facade methods that hand them out.
    #
    # These are bare annotations on purpose: they declare a type without
    # creating a class attribute, so runtime behaviour (including
    # `getattr(app, name, default)` and `hasattr`) is exactly as before.
    job_registry: JobRegistry
    plugin_loader: PluginLoader
    config_registry: ProviderRegistry
    _hook_registry: HookRegistry
    _di_registry: DIRegistry
    _gate_registry: GateRegistry
    _agent_step_registry: AgentStepRegistry
    _domain_registry: DomainRegistry
    _execution_engine: JobExecutionEngine
    _resolution_pipeline: ResolutionPipeline
    _resolution_chain: ResolutionChain
    _config_path: str
    _scope_registry: dict[str, WorkflowScope]
    _plugin_commands_list: list[PluginCommand]
    _surfaces: list[Any]
    _surface_stack: list[Any]
    # init_observability() sets these to a real instance, or to None when
    # observability is left inert; the `event_bus`/`middleware` properties
    # call it first and narrow the result.
    _event_bus: EventBus | None
    _middleware_stack: MiddlewareStack | None
    # Memo caches, invalidated by the mutators below.
    _jobs_memo: list[JobDescriptor] | None = None
    _cli_command_cache: Any = None
    # The programmatic scope seam, kept deliberately: an embedded host sets
    # this directly and it has no CLI spelling (`click_params.py` reads it).
    #
    # `_output_format`, `_prompt_gates` and `_force` used to be declared here
    # too — the deposit protocol. The CLI wrote them onto the app it was about
    # to run and the kernel read them back through `engine._app`, which meant
    # the delivery behaviour of a run lived on a process-lifetime object rather
    # than on the run. run-request/T12 removed all eleven writes: the doors that
    # parse those flags now state them when they build the command, and the
    # app's own root callback — which runs after its subcommands are built —
    # puts them in the per-invocation `ctx.obj` instead.
    _workflow_scope_id: str | None

    def __init__(
        self,
        name: str,
        *,
        job_sources: JobSources | None = None,
        config_sources: ConfigSources | None = None,
        plugin_sources: PluginSources | None = None,
        execution: ExecutionConfig | None = None,
        discovery_config: DiscoveryConfig | None = None,
    ):
        from functualize._events.perf import perf_timeline

        perf_timeline.mark("boot.total.start")

        # Phase: app_init — covers top-level imports and config dataclass resolution
        perf_timeline.mark("boot.app_init.start")

        from functualize._app.boot import boot_standard, boot_static

        self.name = name

        # --- Resolve grouped configs ---
        self._job_sources = job_sources if job_sources is not None else JobSources()
        self._config_sources = (
            config_sources if config_sources is not None else ConfigSources()
        )
        self._plugin_sources = (
            plugin_sources if plugin_sources is not None else PluginSources()
        )
        self._execution_config = (
            execution if execution is not None else ExecutionConfig()
        )
        self._discovery_config = discovery_config

        # Where this project's derived run state (fingerprints, history,
        # workflow scopes) lives. Read here, once, at the delivery boundary —
        # the kernel asks *this* object rather than the operating system, which
        # is what stops three call sites from answering the same question
        # differently (see `contributor/architecture/run-model/05-engine-seal.md` §C).
        self._state_root = Path.cwd()
        #: Set by boot_standard once `general.max_invoke_depth` resolves.
        self._resolved_max_invoke_depth: int | None = None

        # Extract effective values from resolved configs
        self._jobs_directories = self._job_sources.directories or []
        self._children = self._job_sources.children
        self._children_glob = self._job_sources.children_glob
        self._lazy_boot = self._job_sources.lazy
        # Set by boot_standard when lazy boot wires a CachedDirectoryScanProvider
        self._cached_provider: Any = None
        self._config_file_regex = self._config_sources.file_pattern

        # Detect static wiring fast path: all sources are explicit, zero I/O
        self._static_wiring = self._is_fully_explicit()

        perf_timeline.mark("boot.app_init.end")

        if self._static_wiring:
            boot_static(self, perf_timeline)
        else:
            boot_standard(self, perf_timeline)

    # ─── Constructor Resolution Helpers ──────────────────────────────────

    def _is_fully_explicit(self) -> bool:
        """Detect whether all sources are explicitly provided (static wiring)."""
        from functualize._app.impl import is_fully_explicit

        return is_fully_explicit(
            self._job_sources, self._config_sources, self._plugin_sources
        )

    # ─── Observability Integration ───────────────────────────────────────

    def _init_observability(self) -> None:
        """Initialize observability subsystem (idempotent)."""
        from functualize._app.boot import init_observability

        init_observability(self)

    @property
    def event_bus(self) -> EventBus:
        """The central event bus for structured event emission and subscription."""
        self._init_observability()
        return self._event_bus  # type: ignore[return-value]

    @property
    def middleware(self) -> MiddlewareStack:
        """Per-operation-point middleware registry for observability."""
        self._init_observability()
        return self._middleware_stack  # type: ignore[return-value]

    @property
    def hook_registry(self) -> HookRegistry:
        """Access to the hook system."""
        return self._hook_registry

    @property
    def perf_timeline(self) -> PerfTimeline:
        """The global PerfTimeline singleton instance."""
        from functualize._events.perf import perf_timeline

        return perf_timeline

    @property
    def execution_engine(self) -> JobExecutionEngine:
        """The job execution engine (read-only property)."""
        return self._execution_engine

    # ─── Engine Host ─────────────────────────────────────────────────────
    #
    # The engine's port onto this object (``_types.protocols.EngineHost``).
    # The engine is handed this app at construction and reads these live, so
    # nothing is written into it afterwards and a value resolved later — a
    # rebuilt config chain, a re-resolved invoke depth — is simply seen.
    #
    # They are declared for the port, not as a facade: delivery code should
    # reach the job facade above. `_app/boot.build_engine` is the caller of
    # record; `tests/engine/test_engine_is_sealed.py` is what holds the two
    # ends together.

    def get_descriptor(self, name: str) -> JobDescriptor | None:
        """The descriptor for ``name``, or None when nothing is registered."""
        try:
            return self.job_registry.get_descriptor(name)
        except KeyError:
            return None

    def registered_jobs(self) -> Mapping[str, RegisteredJob]:
        """Every registered job, as a read-only mapping.

        A view, not a copy. The engine reads this where it needs the whole set,
        and what it used to be handed instead was the registry's *private* dict
        by reference — two objects sharing mutable state with no contract
        between them. Read-only is what makes the sharing unnecessary, and it
        costs nothing: a proxy over a mapping already in memory.
        """
        return MappingProxyType(self.job_registry._registered_jobs)

    def replace_job(self, current: RegisteredJob, replacement: RegisteredJob) -> None:
        """Swap ``current`` for ``replacement`` in the job registry.

        The engine calls this when it materializes a lazily-registered entry:
        the placeholder that carries the deferred import is replaced by one
        carrying the real function. The engine keeps its own copy for
        resolution; this is what keeps the registry's from diverging from it.
        """
        jobs = self.job_registry._registered_jobs
        if jobs.get(current.name) is current:
            jobs[current.name] = replacement

    @property
    def state_root(self) -> Path:
        """Where this project's derived run state lives.

        One answer to a question three places in the kernel used to answer for
        themselves by asking the operating system — and one of them answered it
        differently, which is why a run's fingerprints could land somewhere
        other than the run's own project. Recorded when the app is constructed,
        so a later ``chdir`` cannot move a run's state out from under it.
        """
        return self._state_root

    @property
    def max_invoke_depth(self) -> int:
        """The deepest chain of nested ``invoke()`` calls allowed.

        The config-resolved value when boot found one, else the constructor's
        ``ExecutionConfig``. The engine reads this rather than the value it was
        built with, so the resolution order (`ExecutionConfig` at construction,
        then `general.max_invoke_depth` from config) is this object's business
        and no boot step has to know the engine exists to apply it.
        """
        resolved = self._resolved_max_invoke_depth
        if resolved is not None:
            return resolved
        return self._execution_config.max_invoke_depth

    def live_zone(self) -> Any | None:
        """The surface that should host ``Live`` constructs, or None.

        Top of the pushed stack wins, then the first registered live-capable
        surface. None is the kernel's answer, where ``Live`` no-ops.
        """
        from functualize._engine.surface_routing import active_live_zone

        return active_live_zone(self)

    def collector(self) -> Any | None:
        """The one surface that should answer a prompt, or None.

        None is not an error: it is what turns a would-be hang into a typed
        ``InputNotAvailable`` at the job's call site.
        """
        from functualize._engine.surface_routing import active_collector

        return active_collector(self)

    @property
    def domain_registry(self) -> Any:
        """The domain SDK registry (discovered at boot time)."""
        return self._domain_registry

    @property
    def cli_command(self) -> Any:
        """The CLI command tree — a ``click.Group``, lazily built.

        Holds discovered jobs (nested one group per dotted segment), plugin
        command namespaces, and the reserved ``builtin`` subtree.
        """
        if self._cli_command_cache is None:
            from functualize.app.adapters.cli import CliAdapter

            adapter = CliAdapter()
            adapter(self)
            self._cli_command_cache = adapter._cli_group
        return self._cli_command_cache

    @cli_command.setter
    def cli_command(self, value: Any) -> None:
        """Allow setting cli_command (patch support)."""
        self._cli_command_cache = value

    @cli_command.deleter
    def cli_command(self) -> None:
        """Allow deleting cli_command (patch restore)."""
        self._cli_command_cache = None

    # ─── DI Registry Facade ──────────────────────────────────────────────

    def provide(self, type_: type, instance: Any, qualifier: str | None = None) -> None:
        """Register a singleton instance in the DI registry."""
        self._di_registry.provide(type_, instance, qualifier)

    def provide_factory(
        self,
        type_: type,
        factory: Callable[..., Any],
        scope: str,
        qualifier: str | None = None,
    ) -> None:
        """Register a factory in the DI registry."""
        self._di_registry.provide_factory(type_, factory, scope, qualifier)

    def provide_named(self, name: str, instance: Any) -> None:
        """Register a string-keyed value in the DI registry."""
        self._di_registry.provide_named(name, instance)

    # ─── Gate Strategy Registry Facade ───────────────────────────────────

    def register_gate_strategy(self, name: str, resolver: GateResolver) -> None:
        """Register a gate resolution strategy by name.

        Args:
            name: Strategy identifier (1-64 characters).
            resolver: A GateResolver implementation instance.

        Raises:
            ValueError: If name length is outside [1, 64].
        """
        self._gate_registry.register_strategy(name, resolver)

    def register_gate_preset(self, name: str, strategies: list[str]) -> None:
        """Register an ordered fallback list of strategies under a preset name.

        Args:
            name: Preset identifier.
            strategies: Ordered list of strategy names (1-10 entries).

        Raises:
            ValueError: If strategies list length is outside [1, 10].
        """
        self._gate_registry.register_preset(name, strategies)

    # ─── Agent Step Executor Registry Facade ─────────────────────────────

    def register_agent_step_executor(self, executor: AgentStepExecutor) -> None:
        """Register an executor that services ``AgentStep`` nodes.

        Registered, never auto-discovered: a workflow that declares an agent
        step reaches an executor because a package registered one, not because
        a discovery scan found it.

        Args:
            executor: An implementation of `AgentStepExecutor` — a ``name``, a
                ``capabilities`` set, and ``execute(ctx)``.

        Raises:
            TypeError: ``executor`` does not satisfy `AgentStepExecutor`, so a
                forgotten capability declaration fails here rather than
                mid-walk.
            ValueError: Its name is empty or already registered.
        """
        from functualize._app.impl import register_agent_step_executor

        register_agent_step_executor(self, executor)

    @property
    def _gate_strategies(self) -> dict[str, GateResolver]:
        """Access the registered gate strategies dict."""
        return self._gate_registry._strategies

    @property
    def _gate_presets(self) -> dict[str, list[str]]:
        """Access the registered gate presets dict."""
        return self._gate_registry._presets

    def resolve_gate(
        self,
        model_class: type,
        *,
        force_gate: bool = False,
        gate_strategy: Any = None,
        resolved_fields: dict[str, Any] | None = None,
        workflow_context: dict[str, Any] | None = None,
        gate_name: str = "unnamed",
    ) -> Any:
        """Resolve a gate by applying the resolution algorithm."""
        from functualize._app.impl import resolve_gate

        return resolve_gate(
            self,
            model_class,
            force_gate=force_gate,
            gate_strategy=gate_strategy,
            resolved_fields=resolved_fields,
            workflow_context=workflow_context,
            gate_name=gate_name,
        )

    # ─── Job Facade ──────────────────────────────────────────────────────

    def get_jobs(self) -> list[JobDescriptor]:
        """Return all discovered job descriptors (Layer 2 memoized)."""
        if self._jobs_memo is not None:
            return self._jobs_memo
        result = self.job_registry.get_descriptors()
        self._jobs_memo = result
        return result

    def get_job(self, name: str) -> JobDescriptor | None:
        """Retrieve a single job descriptor by name."""
        result = self._resolution_pipeline.resolve_one(name)
        if result is not None:
            return result
        try:
            return self.job_registry.get_descriptor(name)
        except KeyError:
            return None

    def config_files(self, job_name: str | None = None) -> list[ConfigFileInfo]:
        """Return every config file the kernel discovered, and its role."""
        from functualize._app.impl import config_files

        return config_files(self, job_name)

    def resolution_chain(self) -> ResolutionChain:
        """Return the config resolution chain [CLI → Env → Files → Defaults].

        The sanctioned way to read provenance — which source supplied a value
        and in what precedence order. Long-lived consumers (TUI provenance
        panels, MCP introspection) must use this rather than reaching for the
        private ``_resolution_chain`` attribute.

        Returns:
            The active ResolutionChain. Never None on a booted app.
        """
        return self._resolution_chain

    @property
    def extension_state(self) -> dict[str, Any]:
        """Mutable namespace for consumer-owned state keyed by consumer name.

        A sanctioned place for long-lived consumers (MCP server, TUI
        orchestrator) to hang state that belongs to them, not to the kernel —
        instead of monkey-patching private attributes onto the app instance.

        Keys should be namespaced by consumer (e.g. ``"mcp"``,
        ``"orchestrator"``). The kernel never reads or interprets the
        contents; it only guarantees the dict exists and survives for the
        app's lifetime.

        Example:
            state = app.extension_state.setdefault("mcp", {})
            state["gate_checkpoints"] = {...}
        """
        # Lazily created: both boot paths and partially-constructed test
        # doubles get a working namespace without an __init__ contract.
        state = getattr(self, "_extension_state", None)
        if state is None:
            state = {}
            self._extension_state = state
        return state

    def refresh(self) -> None:
        """Re-read the project from disk: discovery and config resolution."""
        from functualize._app.impl import refresh

        return refresh(self)

    def active_environment(self) -> str:
        """Return the active environment name (e.g. ``"prod"``).

        Selects which ``config.<slot>.*`` overlay is merged on top of
        ``config.base.*``. See :meth:`environment_source` for whether it was
        chosen explicitly or defaulted.
        """
        return self._environment

    def environment_source(self) -> EnvironmentSource:
        """Return where the active environment name came from.

        ``EnvironmentSource.DEFAULT`` means nothing selected it — a
        meaningfully different state to show a user than an explicit choice,
        since it is the usual reason an overlay file "isn't working".
        """
        return self._environment_source

    def _file_source_infos(self) -> list[ConfigFileInfo]:
        """Return the FileSource's per-file info, or [] if there is none."""
        from functualize._app.impl import _file_source_infos

        return _file_source_infos(self)

    def get_job_config_section(self, job_name: str) -> str:
        """Return the TOML config section name used by the kernel for a job.

        Mirrors the kernel's config_prefix logic: grouped jobs use the group
        path as their section (shared by all jobs in the group); ungrouped
        jobs use the job's own name. This accounts for custom config_prefix
        on grouped jobs where the group may differ from the job name prefix.

        Args:
            job_name: Qualified job name (e.g., "infra.deploy" or "serve").

        Returns:
            The TOML section name (e.g., "infra" for a grouped job, "serve"
            for an ungrouped job).
        """
        descriptor = self.get_job(job_name)
        if descriptor is not None and descriptor.group is not None:
            return descriptor.group
        # Ungrouped job or not found — use the job name itself.
        # For qualified names not found in the registry, extract bare name.
        if descriptor is not None:
            return descriptor.name
        return job_name

    def execute(self, request: RunRequest) -> JobResult:
        """Execute a job — the single surface-facing entry.

        Takes a :class:`RunRequest` and nothing else. Every door builds one, so
        a run's origin is carried rather than reconstructed, and the delivery
        inputs travel with the run instead of being read off this object.

        **Why there is no ``(job_name, **kwargs)`` form.** There was one until
        run-request/T15, and it was the *accidental control channel* of spec
        §1.6a: a wire surface splatting a caller's payload into
        ``execute(name, **body)`` meant a JSON body of ``{"scope_id": "abc"}``
        did not arrive as an argument called ``scope_id`` — it chose **the scope
        the run joined**. ``group_option_values`` leaked the same way. Wave 3
        stopped every door from splatting; deleting the parameters is what makes
        it unrepresentable rather than merely unpractised.

        For the short programmatic spelling use
        :func:`request_for`: ``app.execute(request_for("build", target="x"))``.
        It puts every keyword in ``kwargs``, where a job argument belongs. A
        caller who genuinely means a control input constructs the request and
        names the field, so the intent is visible in their source instead of
        hiding in a dict key.

        A ``WorkflowScope`` is created for each top-level execution, grouping
        related invocations under one traceable context: the request's
        ``workflow_scope_id`` when it names one (reused if it already exists),
        otherwise a generated ``<job>-<hex>``.

        Args:
            request: The run to perform.

        Returns:
            JobResult with status, duration, return value, and metadata.
        """
        from uuid import uuid4

        job_name = request.job_name
        scope_id = request.workflow_scope_id
        group_option_values = (
            dict(request.group_option_values)
            if request.group_option_values is not None
            else None
        )
        kwargs = dict(request.kwargs)

        # Determine scope: explicit or auto-generated
        if scope_id is not None:
            # Use explicit scope — reuse if exists, create if not
            if scope_id in self._scope_registry:
                scope = self._scope_registry[scope_id]
            else:
                scope = self.create_workflow_scope(scope_id)
        else:
            # Auto-generate scope ID
            auto_id = f"{job_name}-{uuid4().hex[:8]}"
            scope = self.create_workflow_scope(auto_id)

        return self._execution_engine.run(
            request.replace(
                kwargs=kwargs,
                parent_scope=scope,
                workflow_scope_id=scope.scope_id,
                group_option_values=group_option_values,
            )
        )

    def execute_parallel(
        self,
        job_names: Sequence[str],
        *,
        timeout: float | None = None,
        observer: Any | None = None,
    ) -> list[JobResult]:
        """Execute jobs concurrently, returning results in input order (T40)."""
        from functualize._app.impl import execute_parallel

        return execute_parallel(self, job_names, timeout=timeout, observer=observer)

    def resolved_job_config(self, job_name: str) -> Any | None:
        """A job's config model, resolved through the full ladder but not run (T43).

        The public seam for ``func builtin env`` and ``func builtin info --job``:
        both need "what config would this job see?" without executing it, and
        both must agree with each other and with a real run — so they resolve
        through the one path the engine uses, not a re-implementation.

        Returns ``None`` when the job declares no config model. May raise
        ``ValidationError`` if a required field is unresolved (a caller asking
        for the config is better told it is incomplete than given a partial).
        """
        self.get_jobs()  # lazy boot: nothing is materialized until asked
        return self.execution_engine.resolve_config_model(job_name)

    # ─── Cache Stats ─────────────────────────────────────────────────────

    def explain(self, job_name: str) -> str:
        """Render why ``job_name`` would or would not run (§D.6).

        The prose half of :meth:`explain_verdicts`. Two forms of one answer,
        derived from one set of verdicts, so `func builtin why` and
        `func builtin why --json` cannot disagree.
        """
        from functualize._app.impl import explain

        return explain(self, job_name)

    def explain_verdicts(self, job_name: str) -> tuple[Any, list[Any], str, str | None]:
        """The raw material behind `func builtin why`.

        Returns ``(target_verdict, [(dep_name, dep_verdict), …], note, error)``.
        Evaluates the same pre-flight pipeline the executor consults, fresh
        rather than from a cache — a verdict is a function of the world *now*,
        and a stored explanation goes stale exactly when someone asks.

        Stays on the app because `func builtin why`, the JSON form and the TUI
        all need it and none of them may import the engine directly; the
        ~115 executable lines behind it live in `_app/impl.py` (T9).
        """
        from functualize._app.impl import explain_verdicts

        return explain_verdicts(self, job_name)

    def explain_data(self, job_name: str) -> dict[str, Any]:
        """The machine-readable half of :meth:`explain`, off the same verdicts."""
        from functualize._app.impl import explain_data

        return explain_data(self, job_name)

    def cache_stats(self) -> CacheInfo:
        """Return statistics about the job discovery cache.

        Returns a CacheInfo dataclass with entry_count, stale_count,
        file_size_bytes, and cache_path.
        """
        from functualize._app.impl import get_cache_stats

        return get_cache_stats(self)

    # ─── Provider/Transform Public API ───────────────────────────────────

    def add_job_provider(
        self,
        provider: JobProvider,
        transforms: list[JobTransform] | None = None,
    ) -> None:
        """Register a job provider with optional provider-scoped transforms."""
        self._resolution_pipeline.add_provider(provider, transforms)
        self._jobs_memo = None

    def add_job_transform(self, transform: JobTransform) -> None:
        """Register an app-level transform (applies to ALL providers)."""
        self._resolution_pipeline.add_transform(transform)
        self._jobs_memo = None

    # ─── Plugin Commands ─────────────────────────────────────────────────

    def register_plugin_command(
        self,
        name: str,
        callback: Callable[..., Any],
        help_text: str = "",
        namespace: str | None = None,
        needs_terminal: bool = False,
    ) -> None:
        """Register a command from a plugin.

        Args:
            name: Command name (lowercase alphanumeric + hyphens).
            callback: Callable to invoke when the command is executed.
            help_text: Help text (max 256 chars).
            namespace: Optional flat CLI namespace to mount the command under
                (``namespace="mcp"`` + ``name="serve"`` → ``func mcp serve``).
                None mounts the command at the top level.
            needs_terminal: True when running the command takes over the
                controlling terminal — a server speaking a protocol on stdio, a
                spawned editor. A TUI front-end reads this to step aside rather
                than capture the command's output on a worker thread, which for
                a stdio server would corrupt the protocol it speaks.
        """
        from functualize._app.impl import register_plugin_command

        register_plugin_command(
            self, name, callback, help_text, namespace, needs_terminal
        )

    def register_surface(self, surface: Any) -> None:
        """Register something that renders a job's events, answers its prompts, or both."""
        from functualize._app.impl import register_surface

        return register_surface(self, surface)

    def register_ambient_construct(
        self,
        construct_factory: Any,
        *,
        name: str | None = None,
        predicate: Any = None,
    ) -> None:
        """Register a live construct that renders by default for eligible jobs."""
        from functualize._app.impl import register_ambient_construct

        return register_ambient_construct(
            self, construct_factory, name=name, predicate=predicate
        )

    def resolve_ambient_constructs(self, descriptor: Any = None) -> list[Any]:
        """Instantiate the ambient constructs eligible for ``descriptor``.

        The public entry point for live zones that need to pre-mount ambient
        constructs. Delivery-layer surfaces (``_cli``) must come through here
        rather than reaching into ``_engine`` directly — see the "_cli uses
        public API only" import contract.

        Args:
            descriptor: The job about to run. None resolves none.

        Returns:
            Fresh construct instances, in registration order.
        """
        from functualize._engine.ambient import resolve_ambient_constructs

        return resolve_ambient_constructs(self, descriptor)

    def push_surface(self, surface: Any) -> None:
        """Push a phase-scoped surface onto the surface stack.

        Used by ``TTY.run`` and the orchestrator to make a job-owned app the
        active surface for the duration of a phase. Always pair with
        :meth:`pop_surface` in a ``finally`` so a crashing phase still unwinds
        before the shell resumes. Top-of-stack answers prompts, and while a
        terminal-owning surface is on the stack the fan-out skips other
        terminal surfaces (see ``_engine/surface_routing``).
        """
        if not hasattr(self, "_surface_stack"):
            self._surface_stack = []
        self._surface_stack.append(surface)

    def pop_surface(self, surface: Any = None) -> None:
        """Pop the top surface (or ``surface`` if given) off the stack.

        Tolerant of an already-empty stack and of a mismatched argument so a
        ``finally``-guaranteed unwind never raises over the original error.
        """
        stack = getattr(self, "_surface_stack", None)
        if not stack:
            return
        if surface is None or stack[-1] is surface:
            stack.pop()
        elif surface in stack:
            stack.remove(surface)

    def get_plugin_commands(self) -> list[PluginCommand]:
        """Return all registered plugin commands."""
        return list(self._plugin_commands_list)

    # ─── Decorator Shortcuts ─────────────────────────────────────────────

    @property
    def on_job_failure(self) -> Callable[..., Any]:
        """Decorator: register AFTER_FAILURE hook (global or job-scoped)."""
        from functualize._app.impl import make_on_job_failure_decorator

        return make_on_job_failure_decorator(self)

    @property
    def on_job_success(self) -> Callable[..., Any]:
        """Decorator: register AFTER_SUCCESS hook (global or job-scoped)."""
        from functualize._app.impl import make_on_job_success_decorator

        return make_on_job_success_decorator(self)

    @property
    def on_job_teardown(self) -> Callable[..., Any]:
        """Decorator: register ON_TEARDOWN hook (global or job-scoped)."""
        from functualize._app.impl import make_on_job_teardown_decorator

        return make_on_job_teardown_decorator(self)

    @property
    def before_job(self) -> Callable[..., Any]:
        """Decorator: register BEFORE_JOB hook (global or job-scoped)."""
        from functualize._app.impl import make_before_job_decorator

        return make_before_job_decorator(self)

    @property
    def pre_execute(self) -> Callable[..., Any]:
        """Decorator: register PRE_EXECUTE hook (global or job-scoped)."""
        from functualize._app.impl import make_pre_execute_decorator

        return make_pre_execute_decorator(self)

    @property
    def on_phase_failure(self) -> Callable[..., Any]:
        """Decorator: register ON_PHASE_FAILURE hook (global only)."""
        from functualize._app.impl import make_on_phase_failure_decorator

        return make_on_phase_failure_decorator(self)

    @property
    def on_phase_complete(self) -> Callable[..., Any]:
        """Decorator: register ON_PHASE_COMPLETE hook (global only)."""
        from functualize._app.impl import make_on_phase_complete_decorator

        return make_on_phase_complete_decorator(self)

    @property
    def on_phase_start(self) -> Callable[..., Any]:
        """Decorator: register ON_PHASE_START hook (global only)."""
        from functualize._app.impl import make_on_phase_start_decorator

        return make_on_phase_start_decorator(self)

    @property
    def on_invoke_failure(self) -> Callable[..., Any]:
        """Decorator: register INVOKE_FAILURE hook (global only)."""
        from functualize._app.impl import make_on_invoke_failure_decorator

        return make_on_invoke_failure_decorator(self)

    @property
    def on_invoke_start(self) -> Callable[..., Any]:
        """Decorator: register INVOKE_START hook (global only)."""
        from functualize._app.impl import make_on_invoke_start_decorator

        return make_on_invoke_start_decorator(self)

    @property
    def on_invoke_end(self) -> Callable[..., Any]:
        """Decorator: register INVOKE_END hook (global only)."""
        from functualize._app.impl import make_on_invoke_end_decorator

        return make_on_invoke_end_decorator(self)

    @property
    def on_ready(self) -> Callable[..., Any]:
        """Decorator: register APP_READY hook (global only)."""
        from functualize._app.impl import make_on_ready_decorator

        return make_on_ready_decorator(self)

    def on_event(self, pattern: str) -> Callable[..., Any]:
        """Decorator: subscribe to custom events matching pattern."""
        from functualize._app.impl import make_on_event_decorator

        return make_on_event_decorator(self, pattern)

    @property
    def run_middleware(self) -> Callable[..., Any]:
        """Decorator: register generator-based RunContext middleware."""
        from functualize._app.impl import make_run_middleware_decorator

        return make_run_middleware_decorator(self)

    # ─── Public Utilities ────────────────────────────────────────────────

    def register_run_middleware(
        self,
        middleware: Callable[[Any], Generator[None]],
        priority: int = 0,
    ) -> None:
        """Register RunContext middleware for job execution wrapping."""
        from functualize._app.impl import register_run_middleware

        register_run_middleware(self, middleware, priority)

    def create_workflow_scope(
        self,
        scope_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowScope:
        """Create a new WorkflowScope with the given identifier."""
        from functualize._app.impl import create_workflow_scope

        scope: WorkflowScope = create_workflow_scope(self, scope_id, metadata)
        return scope

    def get_workflow_scope(self, scope_id: str) -> WorkflowScope:
        """Retrieve an existing WorkflowScope by identifier."""
        from functualize._app.impl import get_workflow_scope

        scope: WorkflowScope = get_workflow_scope(self, scope_id)
        return scope

    def get_plugin(self, name: str) -> Any:
        """Look up a registered plugin instance by name."""
        from functualize._app.impl import get_plugin

        return get_plugin(self, name)

    def register_dynamic_job(
        self,
        name: str,
        function: Callable[..., Any],
        config_class: Any | None = None,
        group: str | None = None,
    ) -> None:
        """Register a callable as an executable job at runtime."""
        from functualize._app.impl import register_dynamic_job

        register_dynamic_job(self, name, function, config_class, group)

    @property
    def context(self) -> Any:
        """The observability context module (PropagationContext API)."""
        import functualize._events.tracing as ctx_module

        return ctx_module

    def instrument(self, operation_point: str, priority: int = 0) -> Callable[..., Any]:
        """Decorator to register a function as middleware for an operation point."""
        from functualize._app.impl import make_instrument_decorator

        return make_instrument_decorator(self, operation_point, priority)

    def resolve_model(self, section: str, model_class: type[object]) -> object:
        """Resolve a configuration model through the Resolution_Chain."""
        from functualize._app.impl import resolve_model

        return resolve_model(self, section, model_class)

    def run(self) -> None:
        """Entry point — delegates to the active adapter."""
        from functualize._app.impl import shutdown_plugins

        try:
            self.cli_command()
        finally:
            shutdown_plugins(self.plugin_loader, self)

    def _shutdown_plugins(self) -> None:
        """Invoke on_shutdown(app) on all PluginWithShutdown plugins."""
        from functualize._app.impl import shutdown_plugins

        shutdown_plugins(self.plugin_loader, self)

    def _build_resolution_chain(self) -> ResolutionChain:
        """Build a ResolutionChain [CLI → Env → Files → Defaults].

        The regex comparison stays here, not in `_app/impl`: the default it
        compares against is `ConfigSources.file_pattern`, and `_app` may not
        import a public folder to read it (the "Internal never imports public"
        contract). Reaching for it there passed ruff and broke `lint-imports`,
        which is the check that was actually about this.
        """
        from functualize._app.impl import _build_resolution_chain

        custom_regex = (
            self._config_file_regex
            if self._config_file_regex != ConfigSources.file_pattern
            else None
        )
        return _build_resolution_chain(self, custom_regex)

    # ─── Private Methods ─────────────────────────────────────────────────

    def _run_cli_adapter(self) -> None:
        """Build and run the CLI adapter (lazy import, zero CLI deps in kernel)."""
        from functualize.app.adapters.cli import CliAdapter

        adapter = CliAdapter()
        adapter(self)
        adapter.run()

    def _on_job_submit_event(self, event: Any) -> None:
        """Handle interactivity.job.submit: execute a job by name."""
        from functualize._app.impl import on_job_submit_event

        on_job_submit_event(self, event)

    def _update_run_context_configs(self, run_contexts: list[Any]) -> None:
        """Re-resolve config for RunContext instances after config path changes.

        Called by JobRegistry.update_config_paths() to avoid the registry
        importing from _config directly (peer-layer independence).

        Args:
            run_contexts: List of RunContext instances to update.
        """
        from functualize._config.job_config import JobConfigView

        for rc in run_contexts:
            rc._config = JobConfigView(
                resolution_chain=self._resolution_chain,
                default_section_prefix=rc.name,
            )


def request_for(
    job_name: str, surface: RunSurface = "app.execute", /, **kwargs: Any
) -> RunRequest:
    """Build a request for the common programmatic case.

    ``app.execute(request_for("build", target="x"))`` — the short spelling, with
    the surface defaulted rather than omitted, so even the convenience path
    names the door it came through.

    Control inputs are **not** accepted here: ``scope_id`` and
    ``group_option_values`` passed as keywords become job arguments, which is
    the point. A caller that means them as control inputs constructs a
    :class:`RunRequest` and says so (spec 1.6a).

    Both parameters are **positional-only**, and that is the same rule applied
    to this function's own signature. ``surface`` was keyword-only until
    run-request/T15, which left one square inch of the accidental control
    channel open: a caller splatting a payload — ``request_for(name, **body)``
    — with a body key literally called ``surface`` would have **relabelled the
    door the run came through**, and a door's identity is not something a
    caller may choose. Positional-only sends every keyword to ``kwargs``
    without exception. No caller passed it by keyword, so this costs nothing.
    """
    return RunRequest(job_name=job_name, surface=surface, kwargs=kwargs)
