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

from collections.abc import Callable, Generator, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from functualize._app.environment import DEFAULT_ENVIRONMENT
from functualize._types.enums import EnvironmentSource
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
    from functualize._types.descriptors import CacheInfo, ConfigFileInfo, JobDescriptor
    from functualize._types.protocols import JobProvider, JobTransform
    from functualize.job._workflow_scope import WorkflowScope

DEFAULT_CONFIG_FILE_REGEX = r"^config\.(\w+)\.(\w+)$"

#: Sentinel written to a JobDescriptor's source/source_file by
#: register_dynamic_job — marks a job that came from code, not from a file.
_DYNAMIC_SOURCE = "<dynamic>"


def _is_dynamic(descriptor: JobDescriptor) -> bool:
    """True if the descriptor was registered from code rather than discovered."""
    return descriptor.source_file == _DYNAMIC_SOURCE


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
    # Set by the CLI on the app it is about to run; read through
    # `getattr(..., default)` off that path, so they stay undeclared at
    # runtime until the CLI assigns them.
    _output_format: str
    _prompt_gates: bool

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
        """Resolve a gate by applying the resolution algorithm.

        Delegates to the underlying GateRegistry.resolve_gate() method.

        Args:
            model_class: The Pydantic BaseModel subclass to resolve.
            force_gate: If True, dispatch to strategy even when fully resolved.
            gate_strategy: Override strategy — a single strategy name/enum,
                or list of strategies, or a preset name.
            resolved_fields: Dict of field names to already-resolved values.
            workflow_context: Arbitrary context from the current workflow state.
            gate_name: Identifier for the gate (used in error messages).

        Returns:
            A fully populated BaseModel instance.

        Raises:
            GateResolutionError: If all strategies fail to resolve.
            ValueError: If a preset references an unregistered strategy.
        """
        return self._gate_registry.resolve_gate(
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
        """Return every config file the kernel discovered, and its role.

        The single answer to "what happened with the config files": where
        they are, which environment slot each names, whether it is actually
        contributing under the active environment, how strongly it wins, and
        what it said. Delivery layers need all of that together — knowing a
        file merely exists cannot explain why its values aren't taking
        effect.

        Inactive (INERT) and unparsed files are included, precisely so a
        caller can show "present, but belongs to another environment"
        instead of silently omitting the file the user is asking about.

        Args:
            job_name: When given, each file's ``values`` are narrowed to that
                job's config section. When None, ``values`` are the file's
                full contents.

        Returns:
            Files in kernel discovery order. Empty if the active preset has
            no file source (e.g. ``env_only()``) or nothing was discovered.
        """
        infos = self._file_source_infos()
        if job_name is None:
            return infos

        section = self.get_job_config_section(job_name)
        narrowed: list[ConfigFileInfo] = []
        for info in infos:
            section_data = info.values.get(section)
            values = dict(section_data) if isinstance(section_data, dict) else {}
            narrowed.append(replace(info, values=values))
        return narrowed

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
        """Re-read the project from disk: discovery and config resolution.

        For persistent consumers (TUI, MCP server) whose process outlives the
        project state it booted from. After a job file is added, edited, or
        deleted — or a config file changes — ``refresh()`` makes the next
        :meth:`get_jobs` / :meth:`execute` observe the new state.

        Rebuilds:
        - Job discovery — re-runs the same registration the boot path uses,
          so added/removed/edited job modules are picked up.
        - The config resolution chain — unless an explicit chain was supplied
          via ``ConfigSources(config_resolution_chain=...)``, in which case
          the caller owns the chain and it is left untouched.
        - Live RunContext config views, so in-flight contexts see new values.

        Scope: refresh owns only what *discovery* produced. Jobs registered
        programmatically (decorators, ``register_job``) are left in place —
        their source is code that already ran, not a file being re-read. It
        does not re-run plugin boot.

        Not safe to call while a job is executing: it re-registers the very
        entries an in-flight execution resolves against. Call it on a
        boundary, e.g. between TUI shell cycles.
        """
        from functualize._app.boot import resolve_and_register_jobs

        registry = self.job_registry

        # Retire the previous discovery generation. Jobs registered from code
        # (register_dynamic_job) also live in _job_descriptors but carry the
        # "<dynamic>" sentinel — re-reading the disk can never rediscover
        # them, so purging them would destroy them permanently.
        retained = [d for d in registry._job_descriptors if _is_dynamic(d)]
        discovered_names = {
            d.name for d in registry._job_descriptors if not _is_dynamic(d)
        }
        registry._job_descriptors[:] = retained
        for name in discovered_names:
            registry._registered_jobs.pop(name, None)
            self._execution_engine._registered_jobs.pop(name, None)
        registry._registered_commands = {
            key: module_path
            for key, module_path in registry._registered_commands.items()
            # Keys are "<group_or___top__>::<job name>".
            if key.split("::", 1)[-1] not in discovered_names
        }

        # Drop the listing memo so get_jobs() re-reads the rebuilt registry.
        self._jobs_memo = None

        resolve_and_register_jobs(self)

        # Config: an explicitly-supplied chain is the caller's to manage;
        # rebuilding it would discard what they passed in.
        if self._config_sources.config_resolution_chain is None:
            self._resolution_chain = self._build_resolution_chain()
            engine = getattr(self, "_execution_engine", None)
            if engine is not None:
                engine._resolution_chain = self._resolution_chain

        # Push the (possibly new) chain into live RunContext config views.
        self.job_registry.update_config_paths()

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
        try:
            for source in self._resolution_chain.sources:
                if getattr(source, "source_type", "") != "file":
                    continue
                infos = getattr(source, "file_infos", None)
                return list(infos) if infos else []
        except (AttributeError, TypeError):
            pass
        return []

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

    def execute(
        self,
        job_name: str,
        *,
        scope_id: str | None = None,
        group_option_values: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> JobResult:
        """Execute a job by name — convenience facade.

        Automatically creates a WorkflowScope for each top-level execution.
        The scope groups related invocations under a single traceable context.

        Args:
            job_name: Name of the registered job to execute.
            scope_id: Optional explicit scope ID. If provided and a scope with
                that ID already exists, it will be reused. If not provided,
                a scope is auto-generated as ``f"{job_name}-{uuid4().hex[:8]}"``.
                For a ``@workflow`` job this is also the *persisted* scope, so
                passing the id of a blocked run is what resumes it (§A.7) —
                one identity for a run, in memory and in the state store.
            group_option_values: Values for the job's declared ``GroupOptions``
                fields (S6a), kept out of ``kwargs`` because they are not the
                job function's parameters — they belong to a *group* the job
                sits under. The CLI fills this from the flags it consumed
                mid-path; MCP fills it from the group fields in a tool's input
                schema. Omitted, the group's file/env/default layers still
                resolve, so a plain ``execute("deploy.web.run")`` is complete.
            **kwargs: Arguments passed to the job function.

        Returns:
            JobResult with status, duration, return value, and metadata.
        """
        from uuid import uuid4

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

        registered_job = self.job_registry.get_job(job_name)
        return self._execution_engine.execute(
            job_name,
            registered_job.function,
            config_class=registered_job.config_class,
            kwargs=kwargs,
            parent_scope=scope,
            workflow_scope_id=scope.scope_id,
            group_option_values=group_option_values,
        )

    def execute_parallel(
        self,
        job_names: Sequence[str],
        *,
        timeout: float | None = None,
        observer: Any | None = None,
    ) -> list[JobResult]:
        """Execute jobs concurrently, returning results in input order (T40).

        The public seam over ``Invoke.parallel`` for callers that are not
        themselves jobs — ``func builtin parallel``, primarily. It lives on the
        app because ``_cli`` may not import the engine, and because "run these
        N jobs at once" is the same operation whether a job asks for it or a
        command line does; two implementations would drift on the parts that
        matter (ordering, the timeout, how a failure is reported).

        Args:
            job_names: 1-32 registered job names.
            timeout: Seconds the batch may run before unfinished jobs come back
                as :attr:`RunStatus.TIMEOUT`. ``None`` uses the engine default
                (300s); ``<= 0`` waits indefinitely.
            observer: Notified on each worker thread around its job — what
                per-job output attribution is built on. See
                ``_engine.capabilities.invoke.ParallelObserver``.

        Returns:
            One :class:`JobResult` per name, in input order. Failures are
            *returned*, not raised — a batch reports on every job, including
            the ones that ran fine beside a broken one.
        """
        from pathlib import Path

        from functualize._engine.capabilities.invoke import WiredInvoke

        # Under lazy boot nothing is in the engine registry until something
        # asks, and `parallel` resolves names on a worker thread where a miss
        # surfaces as a bare KeyError per job rather than a usable error. The
        # normal CLI path materializes while building the command tree; this
        # command never builds one, so it has to ask here.
        self.get_jobs()

        invoke = WiredInvoke(
            execution_engine=self.execution_engine,
            gate_registry=getattr(self, "_gate_registry", None),
            invoke_depth=0,
            cwd=Path.cwd(),
        )
        return invoke.parallel(
            [(name, {}) for name in job_names],
            timeout=timeout,
            observer=observer,
        )

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

        Evaluates the same pre-flight pipeline the executor consults, so this
        can never describe a decision the run would not make. Evaluated fresh
        rather than read from a cache: a verdict is a function of the world
        *now* — files on disk, a precondition's exit code — and a stored
        explanation goes stale exactly when someone asks.

        Lives on the app because both `func why` and the TUI need it, and
        neither may import the engine directly.
        """
        from pathlib import Path

        from functualize._engine.explain import render_dep_line, render_verdict
        from functualize._engine.guards import GuardState, GuardVerdict
        from functualize._engine.preflight import Preflight
        from functualize._primitives.state_store import StateStore

        try:
            entry = self.execution_engine.materialize_job(job_name)
        except Exception as exc:
            return f"{job_name} → UNKNOWN\n  {type(exc).__name__}: {exc}"

        declaration = getattr(entry.function, "__functualize_job__", None)
        if declaration is None:
            return (
                f"{job_name} → WOULD RUN\n"
                "  no @job declaration — nothing guards or caches this job"
            )

        store = StateStore.for_project(Path.cwd())
        preflight = Preflight(store)

        def config_for(name: str) -> Any:
            """The config a run of ``name`` would resolve, or None.

            The fingerprint key is a function of the resolved config, so
            omitting it here addressed a *different* key than the run wrote
            under and this method reported "no previous run recorded" for a
            job that had just succeeded — the contradiction §D.6 exists to
            make impossible.

            `resolve_config_model` deliberately propagates ValidationError; on
            a read path that must degrade rather than turn `why` into a crash,
            so an unresolvable config becomes None *and says so* in the log.
            """
            import logging

            try:
                return self.execution_engine.resolve_config_model(name)
            except Exception as exc:
                logging.getLogger(__name__).debug(
                    "config for %r could not be resolved while explaining it "
                    "(%s); the verdict is computed without it",
                    name,
                    exc,
                )
                return None

        def verdict_for(name: str) -> Any:
            try:
                dep_entry = self.execution_engine.materialize_job(name)
            except Exception:
                return GuardVerdict(GuardState.RUN, "not registered")
            dep_declaration = getattr(dep_entry.function, "__functualize_job__", None)
            if dep_declaration is None:
                return GuardVerdict(GuardState.RUN, "no @job declaration")
            return preflight.check(
                name, dep_declaration, config=config_for(name)
            ).verdict

        # A dependency's own verdict matters: a fresh target with a stale dep
        # still runs, and a user staring at the target alone cannot see why.
        dep_lines = [
            render_dep_line(name, verdict_for(name))
            for name in self.execution_engine._declared_dep_names(job_name)
        ]
        # The *target's* verdict needs the same config as the dependencies'.
        # It produces the headline line, so getting this one wrong is the
        # visible half of the contradiction.
        rendered = render_verdict(
            job_name,
            preflight.check(job_name, declaration, config=config_for(job_name)).verdict,
            deps=dep_lines,
        )

        # Resolved Q19: a recorded value that cannot be handed to a `FromJob`
        # dependent is a reason the upstream keeps re-running, and it is
        # invisible in the freshness verdict — the job *is* fresh; only its
        # value cannot travel. `func why` is where someone already asks "why
        # did this run again", so the answer belongs here.
        note = self._return_value_note(job_name, declaration, store)
        return f"{rendered}\n  {note}" if note else rendered

    def _return_value_note(self, job_name: str, declaration: Any, store: Any) -> str:
        """One line about an unusable recorded return value, or ""."""
        from functualize._primitives.fingerprint import why_return_value_unreusable

        if getattr(declaration, "cache", None) is None:
            return ""
        for method in ("checksum", "timestamp", "none"):
            # Through the engine's own key derivation. Reading under
            # `compute_args_hash(None, {})` found no record for any job with a
            # config class, so the note this method exists to print was
            # unprintable exactly where it mattered most.
            record = store.get_fingerprint(
                self.execution_engine.fingerprint_key_for(job_name, method)
            )
            if record is not None:
                return why_return_value_unreusable(record)
        return ""

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
    ) -> None:
        """Register a command from a plugin.

        Args:
            name: Command name (lowercase alphanumeric + hyphens).
            callback: Callable to invoke when the command is executed.
            help_text: Help text (max 256 chars).
            namespace: Optional flat CLI namespace to mount the command under
                (``namespace="mcp"`` + ``name="serve"`` → ``func mcp serve``).
                None mounts the command at the top level.
        """
        from functualize._app.impl import register_plugin_command

        register_plugin_command(self, name, callback, help_text, namespace)

    def register_surface(self, surface: Any) -> None:
        """Register something that renders a job's events, answers its
        prompts, or both.

        The two capabilities are independent — a renderer need not be able to
        collect, and a collector need not render — so satisfying either is
        enough:

        - :class:`Surface` — has ``handle_event(event)``; receives the event
          fan-out.
        - :class:`PromptCollector` — has ``collect(request)``; eligible to
          answer ``rc.prompt_*()``.

        Raises:
            TypeError: If the object satisfies neither protocol.
        """
        from functualize._types.interactivity import PromptCollector, Surface

        renders = isinstance(surface, Surface)
        collects = isinstance(surface, PromptCollector)

        if not renders and not collects:
            raise TypeError(
                "Surface protocol not satisfied. An object registered here "
                "must implement handle_event(event) to receive events, "
                "collect(request) to answer prompts, or both."
            )

        # Skip duplicates
        if surface in self._surfaces:
            return

        self._surfaces.append(surface)

    def register_ambient_construct(
        self,
        construct_factory: Any,
        *,
        name: str | None = None,
        predicate: Any = None,
    ) -> None:
        """Register a live construct that renders by default for eligible jobs.

        The ambient tier of the ``Live`` model: where ``live.add(...)`` is the
        job asking for a construct, this is a plugin providing one for every
        job that matches ``predicate`` — with no job-author code::

            app.register_ambient_construct(
                FlowVizConstruct,
                predicate=lambda descriptor: descriptor.uses_invoke,
            )

        Pass a **factory** (a class or zero-arg callable), not an instance:
        each run gets a fresh construct, so one job's state cannot bleed into
        the next.

        Args:
            construct_factory: Zero-arg callable returning a construct with
                ``__rich__()`` and, optionally, ``handle_event(event)``.
            name: Identifier used for suppression (``live.suppress(name)``,
                ``@job(suppress_live=[name])``, ``[live] suppress``). Defaults
                to the factory's ``name`` attribute, else its ``__name__``.
            predicate: Optional ``(JobDescriptor) -> bool`` gate. Omit for
                always-on. A predicate that raises is treated as False.
        """
        from functualize._engine.ambient import AmbientEntry

        if not callable(construct_factory):
            raise TypeError(
                "register_ambient_construct() expects a factory (a class or "
                "zero-arg callable) returning a construct, not an instance — "
                "each run needs its own construct state."
            )

        resolved = name or getattr(construct_factory, "name", None)
        if not isinstance(resolved, str) or not resolved:
            resolved = getattr(construct_factory, "__name__", "construct")

        if not hasattr(self, "_ambient_constructs"):
            self._ambient_constructs: list[Any] = []
        if any(entry.name == resolved for entry in self._ambient_constructs):
            return  # idempotent: a re-run plugin must not double-register
        self._ambient_constructs.append(
            AmbientEntry(factory=construct_factory, name=resolved, predicate=predicate)
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

        Must stay argument-for-argument equivalent to the boot path's own
        call (``_app/boot.py`` step 6) — a rebuild that omits ``environment``
        silently disables overlay banding, so every ``config.<slot>.*`` file
        would merge in discovery order instead of only the active one.
        """
        from functualize._app.boot import build_resolution_chain

        custom_regex = (
            self._config_file_regex
            if self._config_file_regex != ConfigSources.file_pattern
            else None
        )
        return build_resolution_chain(
            self._config_path,
            self.name,
            self.config_registry,
            file_regex=custom_regex,
            environment=self._environment,
            event_bus=self.event_bus,
        )

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
