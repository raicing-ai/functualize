"""RunContext module — thin facade providing execution context for jobs.

Delegates heavy logic to capability classes:
- invoke() / invoke_parallel() → _engine.capabilities.invoke.Invoke
- track_phase() → _engine.capabilities.workflow.WorkflowTracker
- emit() → EventBus.emit() (direct delegation)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, TypedDict, TypeVar, cast, overload

from functualize._engine.capabilities.log import Log, validate_log_level
from functualize._types.enums import RunStatus, RunType

_module_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pydantic import BaseModel

    from functualize._config.job_config import JobConfigView
    from functualize._engine.capabilities.discovery_facade import DiscoveryFacade
    from functualize._engine.capabilities.invoke import Invoke
    from functualize._engine.capabilities.observability_facade import (
        ObservabilityFacade,
    )
    from functualize._engine.capabilities.prompt_facade import PromptFacade
    from functualize._engine.capabilities.state_store import StateStore
    from functualize._engine.capabilities.wiring_facade import WiringFacade
    from functualize._engine.capabilities.workflow import WorkflowTracker
    from functualize._engine.capabilities.workflow_scope import WorkflowScope
    from functualize._engine.result import JobResult
    from functualize._events.perf import PerfTimeline
    from functualize._primitives.di import DIRegistry

T = TypeVar("T")


class InvalidStateTransitionError(Exception):
    """Raised when attempting to transition from a terminal state."""

    pass


class RunContextMetadata(TypedDict, total=False):
    """Metadata tracked by a RunContext instance."""

    run_type: RunType
    run_status: RunStatus
    start_time: datetime | None
    end_time: datetime | None
    duration: float | None
    presented_name: str | None


class JobPhase(TypedDict):
    """A single tracked job phase."""

    name: str
    status: RunStatus
    message: str
    start_time: datetime | None
    end_time: datetime | None
    duration: float | None


#: Terminal states that cannot be transitioned from.
#:
#: **Derived from `RunStatus.terminal`, not written out again.** This set and
#: the one in `_engine/capabilities/workflow.py` were two literals, one module
#: apart, and they disagreed: that one included REFUSED and this one did not.
#: Its comment even explained what the omission costs — *"a refused step simply
#: never gets `end_time` or `duration`, so it reads as still running in every
#: consumer of this record"* — and this copy had precisely that defect.
#:
#: `tests/context/test_runcontext_status.py` mirrored the omission and asserted
#: agreement with it, so the two could never converge by failing. Found by
#: adversarial review.
#:
#: The name survives because `functualize.job._runcontext` re-exports it.
_TERMINAL_STATES = frozenset(status for status in RunStatus if status.terminal)


def _dispatch_to_surfaces(
    app: Any, event_name: str, resource: str, payload: dict[str, Any]
) -> None:
    """Fan a structured event out to every registered Surface.

    Non-framework events only. One misbehaving surface must not take down the
    job or starve its peers, so each dispatch is isolated and failures are
    logged rather than raised.
    """
    from functualize._engine.surface_routing import iter_fanout_surfaces

    surfaces = iter_fanout_surfaces(app)
    if not surfaces:
        return

    from functualize._events.bus import StructuredEvent
    from functualize._events.tracing import current_context

    ctx = current_context()
    event = StructuredEvent(
        event_name=event_name,
        resource=resource,
        payload=payload,
        trace_id=ctx.trace_id,
        span_id=ctx.span_id,
    )
    for surface in surfaces:
        try:
            surface.handle_event(event)
        except Exception as exc:
            _module_logger.error(
                f"Surface '{getattr(surface, 'name', repr(surface))}' "
                f"handle_event() raised for event '{event_name}': {exc}",
                exc_info=True,
            )


class RunContext:
    """Execution context injected into each job — thin facade delegating to capabilities."""

    MAX_INVOKE_DEPTH: ClassVar[int] = 10
    _MAX_RESULT_METADATA_KEYS: ClassVar[int] = 64
    _FRAMEWORK_EVENT_PREFIXES: ClassVar[tuple[str, ...]] = (
        "job.execute.",
        "job.teardown.",
        "plugin.",
        "config.",
        "cli.",
        "tui.",
    )

    def __init__(
        self,
        name: str,
        config: JobConfigView,
        logger: Logger,
        metadata: dict[str, Any] | None = None,
        *,
        plugin_configs: dict[str, BaseModel] | None = None,
        state_store: StateStore | None = None,
        resources: dict[str, Any] | None = None,
        perf_timeline: PerfTimeline | None = None,
        _workflow_scope: WorkflowScope | None = None,
        _invoke_depth: int = 0,
        _parent_request: Any = None,
        _run_id: str | None = None,
        _max_invoke_depth: int = 10,
        _execution_engine: Any = None,
        cwd: Path | None = None,
        job_directory: Path | None = None,
        _di_registry: DIRegistry | None = None,
        _caps: dict[type, Any] | None = None,
    ):
        self._name = name
        self._config = config
        self._logger = logger
        self._metadata: dict[str, Any] = metadata.copy() if metadata else {}
        self._metadata.setdefault("run_type", RunType.JOB)
        self._metadata.setdefault("run_status", RunStatus.RUNNING)
        self._metadata.setdefault("start_time", datetime.now(UTC))
        self._metadata.setdefault("end_time", None)
        self._metadata.setdefault("duration", None)
        self._job_config: Any = None
        self._plugin_configs: dict[str, BaseModel] | None = plugin_configs
        self._state_store: StateStore | None = state_store
        self._resources: dict[str, Any] | None = resources
        self._perf_timeline: PerfTimeline | None = perf_timeline
        self._workflow_scope: WorkflowScope | None = _workflow_scope
        self._invoke_depth: int = _invoke_depth
        self._parent_request: Any = _parent_request
        #: The run-log id of *this* run, so `rc.invoke` children can name
        #: their parent. Carried rather than looked up: a batch item runs on
        #: a worker thread, where a `ContextVar` would be empty.
        self._run_id: str | None = _run_id
        self._max_invoke_depth: int = _max_invoke_depth
        self._execution_engine: Any = _execution_engine
        self._cwd: Path | None = cwd
        self._job_directory: Path | None = job_directory
        self._result_metadata: dict[str, Any] = {}
        self._di_registry: DIRegistry | None = _di_registry
        # The live per-invocation capability map (the same dict the engine
        # fills as it resolves bindings) — log() reads the job's own Log out
        # of it, so rc.log() and a `log: Log` parameter share one sink.
        self._caps: dict[type, Any] | None = _caps
        self._config.set_prefix(name)
        # Capability instances (lazily created)
        self._invoke_capability: Invoke | None = None
        self._workflow_tracker: WorkflowTracker | None = None
        # Callback registrations (for backward compat)
        self._status_callbacks: list[Any] = []
        self._phase_callbacks: list[Any] = []
        self._log_callbacks: list[Any] = []
        #: Facades. `RunContext` reached 800 lines by being the one object a
        #: job holds, so everything a job might ever want was a method on it
        #: (T8). These group the rarer capabilities behind a name that says
        #: which subject they belong to; the core a job actually reaches for —
        #: `config`, `log`, `invoke`, `state`, `cwd` — stays flat.
        self._discovery: DiscoveryFacade | None = None
        self._wiring: WiringFacade | None = None
        self._events: ObservabilityFacade | None = None
        self._prompts: PromptFacade | None = None

    def _derive(self, **overrides: Any) -> RunContext:
        """A copy of this context with ``overrides`` applied.

        Every field is carried by construction. The alternative — a second
        ``RunContext(...)`` call listing the fields it happens to need — is
        what ``wiring.with_plugin_config`` was, and it silently dropped seven:
        the derived context had no engine (so ``invoke`` raised), no run id, no
        cwd, and an ``_invoke_depth`` reset to 0, which defeats the recursion
        guard for everything downstream of it.

        Adding a field to ``__init__`` therefore does not require finding this
        function. That was the actual failure mode: ``_run_id`` was added to
        two construction sites and missed here.
        """
        fields: dict[str, Any] = {
            "name": self._name,
            "config": self._config,
            "logger": self._logger,
            "metadata": self._metadata,
            "plugin_configs": self._plugin_configs,
            "state_store": self._state_store,
            "resources": self._resources,
            "perf_timeline": self._perf_timeline,
            "_workflow_scope": self._workflow_scope,
            "_invoke_depth": self._invoke_depth,
            "_parent_request": self._parent_request,
            "_run_id": self._run_id,
            "_max_invoke_depth": self._max_invoke_depth,
            "_execution_engine": self._execution_engine,
            "cwd": self._cwd,
            "job_directory": self._job_directory,
            "_di_registry": self._di_registry,
            "_caps": self._caps,
        }
        fields.update(overrides)
        return RunContext(**fields)

    @property
    def prompts(self) -> PromptFacade:
        """`rc.prompts` — ask the person on the other end, if there is one."""
        if self._prompts is None:
            from functualize._engine.capabilities.prompt_facade import PromptFacade

            self._prompts = PromptFacade(self)
        return self._prompts

    @property
    def events(self) -> ObservabilityFacade:
        """`rc.events` — events, phases, run status and the perf timeline."""
        if self._events is None:
            from functualize._engine.capabilities.observability_facade import (
                ObservabilityFacade,
            )

            self._events = ObservabilityFacade(self)
        return self._events

    @property
    def wiring(self) -> WiringFacade:
        """`rc.wiring` — the plugin configs and resources this app provides."""
        if self._wiring is None:
            from functualize._engine.capabilities.wiring_facade import WiringFacade

            self._wiring = WiringFacade(self)
        return self._wiring

    @property
    def discovery(self) -> DiscoveryFacade:
        """`rc.discovery` — read-only questions about the registered jobs."""
        if self._discovery is None:
            from functualize._engine.capabilities.discovery_facade import (
                DiscoveryFacade,
            )

            self._discovery = DiscoveryFacade(self)
        return self._discovery

    # --- Callback registration (backward compat) ---

    def on_log(self, callback: Any) -> None:
        """Register a callback invoked on log emissions."""
        self._log_callbacks.append(callback)

    # --- Capability accessors (lazy init) ---

    def _get_invoke(self) -> Invoke:
        if self._execution_engine is None:
            raise RuntimeError(
                "Cannot invoke jobs: RunContext was not created by JobExecutionEngine"
            )
        if self._invoke_capability is None:
            from functualize._engine.capabilities.invoke import WiredInvoke

            self._invoke_capability = WiredInvoke(
                execution_engine=self._execution_engine,
                # The request that asked for *this* run, so `rc.invoke`'s
                # children inherit its delivery inputs instead of silently
                # taking defaults (run-request-entry, nested-inheritance fix).
                parent_request=self._parent_request,
                parent_run_id=self._run_id,
                invoke_depth=self._invoke_depth,
                max_invoke_depth=self._max_invoke_depth,
                workflow_scope=self._workflow_scope,
                cwd=self._cwd,
                run_context=self,
                # Without this the gate registry is None, and every gate
                # parameter `invoke()` accepts — `awaits_input`, `force_gate`,
                # `gate_strategy` — is silently inert: the dispatch is guarded
                # by `self._gate_registry is not None`, so it never ran. The
                # arguments were accepted and documented, and did nothing.
                gate_registry=getattr(self._execution_engine, "_gate_registry", None),
            )
        return self._invoke_capability

    def _get_tracker(self) -> WorkflowTracker:
        if self._workflow_tracker is None:
            from functualize._engine.capabilities.workflow import (
                WorkflowTracker as _WorkflowTracker,
            )

            self._workflow_tracker = _WorkflowTracker(
                job_name=self._name,
                run_context=self,
                perf_timeline=self._perf_timeline or self.events._resolve_timeline(),
                execution_engine=self._execution_engine,
                step_logger=self._logger,
            )
        return self._workflow_tracker

    # --- Properties ---

    @property
    def config(self) -> JobConfigView:
        return self._config

    @property
    def name(self) -> str:
        return self._name

    @property
    def metadata(self) -> dict[str, Any]:
        return self._metadata

    @property
    def result_metadata(self) -> dict[str, Any]:
        return self._result_metadata

    def set_result_metadata(self, key: str, value: Any) -> None:
        if (
            key in self._result_metadata
            or len(self._result_metadata) < self._MAX_RESULT_METADATA_KEYS
        ):
            self._result_metadata[key] = value

    @property
    def job_config(self) -> Any:
        return self._job_config

    @job_config.setter
    def job_config(self, value: Any) -> None:
        self._job_config = value

    @property
    def workflow_scope(self) -> WorkflowScope | None:
        return self._workflow_scope

    @property
    def cwd(self) -> Path:
        """This run's working directory: the one it named, or the project's.

        The run's own `cwd` wins when the request carried one. Otherwise the
        answer is the project root the engine's host knows, not the *process's*
        working directory — which is what this used to return, and which is a
        different directory whenever the two disagree.
        """
        if self._cwd is not None:
            return self._cwd
        if self._execution_engine is None:
            raise RuntimeError(
                "this RunContext was not created by an engine, so it has no "
                "working directory; pass cwd= when building it"
            )
        return cast("Path", self._execution_engine.state_root)

    @property
    def job_directory(self) -> Path | None:
        return self._job_directory

    # --- DI Subscript Access ---

    @overload
    def __getitem__(self, key: type) -> Any: ...
    @overload
    def __getitem__(self, key: tuple[type, str]) -> Any: ...
    @overload
    def __getitem__(self, key: str) -> Any: ...

    def __getitem__(self, key: type | str | tuple[type, str]) -> Any:
        from functualize._primitives.di import (
            AmbiguousProviderError,
            MissingProviderError,
        )

        if self._di_registry is None:
            raise RuntimeError(
                "Cannot use subscript access: RunContext has no DI registry attached"
            )
        if isinstance(key, tuple):
            type_, qualifier = key
            try:
                return self._di_registry.resolve(type_, qualifier=qualifier)
            except AmbiguousProviderError:
                raise MissingProviderError(
                    type_=type_,
                    job_name=self._name,
                    available=self._di_registry.available_types(),
                ) from None
        elif isinstance(key, str):
            try:
                return self._di_registry.resolve_named(key)
            except MissingProviderError:
                raise MissingProviderError(
                    type_=str,
                    job_name=self._name,
                    available=self._di_registry.available_types(),
                ) from None
        else:
            return self._di_registry.resolve(key)

    def __contains__(self, key: type | str) -> bool:
        if self._di_registry is None:
            return False
        if isinstance(key, str):
            return self._di_registry.has_named(key)
        return self._di_registry.has(key)

    # --- Delegation: Invoke ---

    def invoke(
        self,
        job_name: str,
        *,
        _propagate_scope: bool = True,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> JobResult:
        """Invoke another registered job. Delegates to Invoke capability."""
        return self._get_invoke()(job_name, timeout=timeout, **kwargs)

    def invoke_parallel(
        self, jobs: list[tuple[str, dict[str, Any]]]
    ) -> list[JobResult]:
        """Invoke multiple jobs concurrently. Delegates to Invoke.parallel()."""
        return self._get_invoke().parallel(jobs)

    # --- Delegation: Phase Tracking ---

    # --- Delegation: Event Emission ---

    # --- Logging ---

    def _log_sink(self) -> Log | None:
        """Return the job's own Log capability, or None when it has none.

        The engine creates Log per invocation and deposits it in the caps map
        (the same instance a ``log: Log`` parameter receives), so rc.log() and
        that parameter cannot drift to different sinks. A job that never asks
        for Log has no entry, and log() falls back to ``self._logger`` — the
        very ``functualize.job.<name>`` logger a per-job Log would write to.

        The unqualified DI registry is deliberately *not* consulted: the engine
        treats Log as per-invocation and skips the registry for it too
        (``executor._resolve_di_parameters``), so reading it here would make
        rc.log() disagree with the job's own parameter.
        """
        if self._caps is None:
            return None
        sink = self._caps.get(Log)
        return sink if isinstance(sink, Log) else None

    def log(self, message: object, level: str = "info") -> None:
        # Validate before the callbacks so an invalid level fails the same way
        # whichever sink is behind it — the Log capability, or the fallback
        # logger whose getattr would otherwise raise AttributeError instead.
        validate_log_level(level)
        msg = str(message)
        # Invoke log callbacks BEFORE emitting to logger
        for cb in self._log_callbacks:
            try:
                result = cb(level, msg)
                # If callback returns None, suppress the message
                if result is None:
                    return
                # If callback returns a string, use it as the new message
                if isinstance(result, str):
                    msg = result
            except Exception:
                self._logger.warning(
                    "Log callback %r raised an exception", cb, exc_info=True
                )
        sink = self._log_sink()
        if sink is not None:
            sink(msg, level=level)
        else:
            getattr(self._logger, level)(msg)

    # --- Run Status ---

    # --- Perf Timeline ---

    # --- State Store ---

    @property
    def state(self) -> StateStore:
        if self._workflow_scope is not None:
            return cast("StateStore", self._workflow_scope.state_store)
        if self._state_store is None:
            from functualize._engine.capabilities.state_store import (
                StateStore as _StateStore,
            )

            self._state_store = _StateStore()
        return self._state_store

    # --- Job Schema ---


def inject_resource(rc: RunContext, name: str, resource: Any) -> None:
    """Inject a named resource into a RunContext (for middleware/hooks)."""
    if rc._resources is None:
        rc._resources = {}
    rc._resources[name] = resource
