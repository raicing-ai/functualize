"""RunContext module — thin facade providing execution context for jobs.

Delegates heavy logic to capability classes:
- invoke() / invoke_parallel() → _engine.capabilities.invoke.Invoke
- track_phase() → _engine.capabilities.workflow.WorkflowTracker
- emit() → EventBus.emit() (direct delegation)
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import UTC, datetime
from logging import Logger
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, TypedDict, TypeVar, cast, overload

from functualize._engine.capabilities.log import Log, validate_log_level
from functualize._types.enums import RunStatus, RunType

_module_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel

    from functualize._config.job_config import JobConfigView
    from functualize._engine.capabilities.invoke import Invoke
    from functualize._engine.capabilities.state_store import StateStore
    from functualize._engine.capabilities.workflow import WorkflowTracker
    from functualize._engine.capabilities.workflow_scope import WorkflowScope
    from functualize._engine.result import JobResult
    from functualize._events.perf import PerfTimeline, Phase
    from functualize._primitives.di import DIRegistry
    from functualize._types.interactivity import (
        PromptChoice,
        PromptRequest,
        PromptResponse,
    )

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


# Terminal states that cannot be transitioned from
_TERMINAL_STATES = frozenset(
    {RunStatus.SUCCESS, RunStatus.FAILURE, RunStatus.CANCELLED, RunStatus.TIMEOUT}
)


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

    # --- Callback registration (backward compat) ---

    def on_status_change(self, callback: Any) -> None:
        """Register a callback invoked on status transitions."""
        self._status_callbacks.append(callback)

    def on_phase_change(self, callback: Any) -> None:
        """Register a callback invoked on phase changes."""
        self._phase_callbacks.append(callback)

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
                perf_timeline=self._perf_timeline or self._resolve_timeline(),
                execution_engine=self._execution_engine,
                step_logger=self._logger,
            )
        return self._workflow_tracker

    def _resolve_timeline(self) -> Any:
        if self._perf_timeline is not None:
            return self._perf_timeline
        from functualize._events.perf import perf_timeline

        return perf_timeline

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
    def phases(self) -> list[JobPhase]:
        return self._get_tracker().steps

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
        return self._cwd if self._cwd is not None else Path.cwd()

    @property
    def job_directory(self) -> Path | None:
        return self._job_directory

    @property
    def run_status(self) -> RunStatus:
        return cast("RunStatus", self._metadata["run_status"])

    @property
    def run_duration(self) -> float:
        duration = self._metadata.get("duration")
        if duration is not None:
            return float(duration)
        start = self._metadata.get("start_time")
        if start is None:
            return 0.0
        return float((datetime.now(UTC) - start).total_seconds())

    @property
    def current_phase(self) -> JobPhase | None:
        return self._get_tracker().current_step

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

    def track_phase(
        self,
        phase_name: str,
        phase_message: str,
        phase_status: RunStatus = RunStatus.RUNNING,
    ) -> None:
        """Track a job phase. Delegates to WorkflowTracker.track_step()."""
        # Determine if this is a new phase or an update
        existing = self._get_tracker().get_step(phase_name)
        action = "updated" if existing is not None else "created"

        self._get_tracker().track_step(phase_name, phase_message, phase_status)

        # Build phase dict for callbacks (backward compat)
        phase_dict: JobPhase = {
            "name": phase_name,
            "message": phase_message,
            "status": phase_status,
            "start_time": None,
            "end_time": None,
            "duration": None,
        }

        # Invoke phase callbacks with (phase_dict, action)
        for cb in self._phase_callbacks:
            try:
                cb(phase_dict, action)
            except Exception:
                self._logger.warning(
                    "Phase callback %r raised an exception", cb, exc_info=True
                )

    def get_phase(self, phase_name: str) -> JobPhase | None:
        return self._get_tracker().get_step(phase_name)

    # --- Delegation: Event Emission ---

    def _resolve_event_bus(self) -> Any | None:
        """Resolve the EventBus from the execution engine's app."""
        if self._execution_engine is None:
            return None
        app = getattr(self._execution_engine, "_app", None)
        if app is None:
            return None
        return getattr(app, "_event_bus", None) or getattr(app, "event_bus", None)

    def emit(self, event_name: str, resource: str = "", **payload: Any) -> None:
        """Emit a structured event. Delegates to EventBus.emit()."""
        return self._emit_event(event_name, resource, payload)

    def on_event(self, pattern: str, callback: Callable[[Any], None]) -> Any | None:
        """Subscribe to structured events for the life of this execution.

        The inbound counterpart to :meth:`emit` — lets code holding a
        RunContext (notably a job-owned UI, which receives the context via
        its ``TTY`` handle) observe events as they happen, including those
        emitted by children started with :meth:`invoke`.

        Args:
            pattern: Exact event name, prefix wildcard (``"job.*"``), or
                the global wildcard (``"*"``).
            callback: Receives a StructuredEvent. Called synchronously on the
                emitting thread — which is a worker thread for most job
                events, so a UI callback must marshal onto its own loop.

        Returns:
            A SubscriptionHandle for :meth:`off_event`, or None when no
            EventBus is reachable (e.g. a RunContext built outside the
            engine), so callers can subscribe unconditionally.
        """
        event_bus = self._resolve_event_bus()
        if event_bus is None:
            return None
        return event_bus.subscribe(pattern, callback)

    def off_event(self, handle: Any) -> None:
        """Remove a subscription created by :meth:`on_event`.

        Accepts None (what ``on_event`` returns when no bus was reachable)
        so teardown paths need no guard of their own.
        """
        if handle is None:
            return
        event_bus = self._resolve_event_bus()
        if event_bus is not None:
            event_bus.unsubscribe(handle)

    def _emit_event(
        self, event_name: str, resource: str, payload: dict[str, Any]
    ) -> None:
        """Internal emit implementation — resolves EventBus and dispatches."""
        event_bus = self._resolve_event_bus()
        if event_bus is not None:
            event_bus.emit(event_name, resource=resource, **payload)
        app = (
            getattr(self._execution_engine, "_app", None)
            if self._execution_engine
            else None
        )
        if app is not None and not any(
            event_name.startswith(p) for p in self._FRAMEWORK_EVENT_PREFIXES
        ):
            _dispatch_to_surfaces(app, event_name, resource, payload)

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

    def track_run_status(
        self,
        run_status: RunStatus = RunStatus.RUNNING,
        failure_message: str = "",
    ) -> None:
        current_status = self._metadata["run_status"]
        if current_status in _TERMINAL_STATES:
            raise InvalidStateTransitionError(
                f"Cannot transition from terminal state {current_status.value} "
                f"to {run_status.value}"
            )
        self._metadata["run_status"] = run_status
        if run_status in _TERMINAL_STATES:
            self._metadata["end_time"] = datetime.now(UTC)
            start_time = self._metadata["start_time"]
            if start_time is not None:
                self._metadata["duration"] = (
                    self._metadata["end_time"] - start_time
                ).total_seconds()
        if failure_message:
            self._logger.error(f"Run status: {run_status.value} - {failure_message}")

    def set_run_status(self, status: RunStatus, message: str = "") -> None:
        old_status = self._metadata["run_status"]
        self.track_run_status(run_status=status, failure_message=message)
        # Invoke status callbacks
        for cb in self._status_callbacks:
            try:
                cb(old_status, status, message)
            except Exception:
                self._logger.warning(
                    "Status change callback %r raised an exception", cb, exc_info=True
                )

    # --- Perf Timeline ---

    @property
    def _timeline(self) -> PerfTimeline:
        if self._perf_timeline is not None:
            return self._perf_timeline
        from functualize._events.perf import perf_timeline

        return perf_timeline

    def _validate_mark_name(self, name: str) -> None:
        if not name or len(name) > 256:
            raise ValueError(
                "Mark name must be a non-empty string of at most 256 characters."
            )

    def perf_mark(self, name: str) -> None:
        self._validate_mark_name(name)
        tl = self._timeline
        if tl.enabled:
            tl.mark(f"{self._name}.{name}")

    def perf_mark_start(self, name: str) -> None:
        self._validate_mark_name(name)
        tl = self._timeline
        if tl.enabled:
            tl.mark(f"{self._name}.{name}.start")

    def perf_mark_end(self, name: str) -> None:
        self._validate_mark_name(name)
        tl = self._timeline
        if tl.enabled:
            tl.mark(f"{self._name}.{name}.end")

    def get_perf_phases(
        self,
        include: str | None = None,
        exclude: str | None = None,
    ) -> list[Phase]:
        from functualize._events._pattern_matcher import filter_phases

        report = self._timeline.report()
        prefix = f"{self._name}."
        job_phases = [p for p in report.phases if p.name.startswith(prefix)]
        unprefixed = [p.name[len(prefix) :] for p in job_phases]
        matching = set(filter_phases(unprefixed, include, exclude))
        return [p for p, u in zip(job_phases, unprefixed, strict=True) if u in matching]

    # --- Plugin Config ---

    @property
    def plugin_configs(self) -> MappingProxyType[str, BaseModel]:
        if self._plugin_configs is None:
            self._plugin_configs = {}
        return MappingProxyType(self._plugin_configs)

    def get_plugin_config(self, section: str) -> BaseModel:
        if self._plugin_configs is None or section not in self._plugin_configs:
            available = list((self._plugin_configs or {}).keys())
            raise KeyError(
                f"No plugin config for section '{section}'. Available: {available}"
            )
        return self._plugin_configs[section]

    def with_plugin_config(self, section: str, **overrides: Any) -> RunContext:
        current = self.get_plugin_config(section)
        model_class = type(current)
        new_config = model_class(**{**current.model_dump(), **overrides})
        new_configs = dict(self._plugin_configs or {})
        new_configs[section] = new_config
        return RunContext(
            name=self._name,
            config=self._config,
            logger=self._logger,
            metadata=self._metadata,
            plugin_configs=new_configs,
            state_store=self._state_store,
            resources=self._resources,
            perf_timeline=self._perf_timeline,
            _di_registry=self._di_registry,
            _caps=self._caps,
        )

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

    # --- Resources ---

    @property
    def resources(self) -> MappingProxyType[str, Any]:
        if self._resources is None:
            self._resources = {}
        return MappingProxyType(self._resources)

    def get_resource(self, name: str, type_: type[T]) -> T:
        if self._resources is None or name not in self._resources:
            available = list((self._resources or {}).keys())
            raise KeyError(f"Resource '{name}' not found. Available: {available}")
        resource = self._resources[name]
        if not isinstance(resource, type_):
            raise TypeError(
                f"Resource '{name}': expected {type_.__name__}, "
                f"got {type(resource).__name__}"
            )
        return resource

    # --- Job Schema ---

    def get_job_schema(self, job_name: str) -> Any:
        from functualize._engine.errors import JobNotFoundError

        if self._execution_engine is None:
            raise RuntimeError(
                "Cannot get job schema: RunContext was not created by JobExecutionEngine"
            )
        try:
            return self._execution_engine._app.job_registry.get_descriptor(job_name)
        except KeyError:
            raise JobNotFoundError(job_name) from None

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return read-only summaries of every registered job.

        For job-owned UIs that browse jobs (a launcher, a picker) — the
        counterpart to :meth:`get_job_schema` for one job. Returns plain
        dicts, not callables or descriptors, so a UI cannot accidentally
        reach into the registry or force a lazy job to materialize::

            for job in rc.list_jobs():
                print(job["name"], "—", job["description"])

        Each entry has ``name``, ``group``, ``description`` (the docstring's
        first line), and ``requires_tty``. Returns an empty list outside a
        real execution context.
        """
        if self._execution_engine is None:
            return []
        app = getattr(self._execution_engine, "_app", None)
        if app is None:
            return []

        getter = getattr(app, "get_jobs", None)
        if not callable(getter):
            return []
        try:
            descriptors = getter()
        except Exception:
            return []

        summaries: list[dict[str, Any]] = []
        for descriptor in descriptors or []:
            name = str(getattr(descriptor, "name", "") or "")
            if not name:
                continue
            docstring = getattr(descriptor, "docstring", "") or ""
            summaries.append(
                {
                    "name": name,
                    "group": name.rsplit(".", 1)[0] if "." in name else "",
                    "description": docstring.strip().splitlines()[0]
                    if docstring.strip()
                    else "",
                    "requires_tty": bool(getattr(descriptor, "requires_tty", False)),
                }
            )
        return summaries

    # --- Prompt System ---

    def _get_input_provider(self) -> Any | None:
        """Return the collector that should answer this job's prompts.

        Only surfaces that actually implement ``collect`` are eligible — a
        render-only surface (flow-viz) must never be handed a prompt it
        cannot answer.

        Stack-scoped: top-of-stack wins, so the phase that owns the terminal
        collects; see ``_engine/surface_routing.active_collector`` and
        contributor/adr/001-surface-architecture-collapse.md.
        """
        if self._execution_engine is None:
            return None
        app = getattr(self._execution_engine, "_app", None)
        if app is None:
            return None

        # Stack-scoped resolution: the topmost pushed surface that can collect
        # (the phase that owns the terminal), else the first registered
        # collector, else the kernel's TTY-gated stdin fallback (None off a
        # terminal — preserving default / InputNotAvailable behavior there).
        from functualize._engine.surface_routing import active_collector

        return active_collector(app)

    def prompt(self, request: PromptRequest) -> PromptResponse:
        from functualize._types.interactivity import InputNotAvailable
        from functualize._types.interactivity import PromptResponse as _PromptResponse

        filled = dataclasses.replace(request, source_job=self._name)
        provider = self._get_input_provider()
        if provider is None:
            if filled.required and filled.default is None:
                raise InputNotAvailable(
                    f"No InputProvider registered and prompt requires input "
                    f"(job='{self._name}', question='{filled.question}')"
                )
            return _PromptResponse(value=filled.default, source="default")
        return cast("PromptResponse", provider.collect(filled))

    def prompt_confirm(
        self,
        question: str,
        *,
        destructive: bool = False,
        default: bool | None = None,
        context_message: str | None = None,
        context_data: dict[str, Any] | None = None,
    ) -> bool:
        from functualize._types.interactivity import (
            PromptIntent,
            severity_for_intent,
        )
        from functualize._types.interactivity import (
            PromptRequest as _PromptRequest,
        )

        intent = (
            PromptIntent.CONFIRM_DESTRUCTIVE
            if destructive
            else PromptIntent.CONFIRM_NEUTRAL
        )
        # Derived, not hand-mapped — one source of truth for the styling.
        severity = severity_for_intent(intent)
        response = self.prompt(
            _PromptRequest(
                question=question,
                intent=intent,
                severity=severity,
                default=default,
                context_message=context_message,
                context_data=context_data,
                required=default is None,
            )
        )
        if response.was_cancelled:
            return False
        value = response.value
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("yes", "y", "true", "1")
        return bool(value) if value is not None else False

    def prompt_choice(
        self,
        question: str,
        choices: list[str] | list[PromptChoice],
        *,
        default: str | None = None,
        context_message: str | None = None,
    ) -> str:
        from functualize._types.interactivity import (
            PromptChoice as _PromptChoice,
        )
        from functualize._types.interactivity import (
            PromptIntent,
        )
        from functualize._types.interactivity import (
            PromptRequest as _PromptRequest,
        )

        normalized = [
            _PromptChoice(value=c) if isinstance(c, str) else c for c in choices
        ]
        response = self.prompt(
            _PromptRequest(
                question=question,
                intent=PromptIntent.SELECT,
                choices=normalized,
                default=default,
                context_message=context_message,
                required=default is None,
            )
        )
        return str(response.value) if response.value is not None else ""

    def prompt_text(
        self,
        question: str,
        *,
        default: str | None = None,
        secret: bool = False,
        placeholder: str | None = None,
        validator: str | Any | None = None,
        context_message: str | None = None,
    ) -> str:
        from functualize._types.interactivity import (
            PromptIntent,
        )
        from functualize._types.interactivity import (
            PromptRequest as _PromptRequest,
        )

        intent = PromptIntent.SECRET_INPUT if secret else PromptIntent.TEXT_INPUT
        response = self.prompt(
            _PromptRequest(
                question=question,
                intent=intent,
                default=default,
                placeholder=placeholder,
                validator=validator,
                context_message=context_message,
                required=default is None,
            )
        )
        return str(response.value) if response.value is not None else ""


def inject_resource(rc: RunContext, name: str, resource: Any) -> None:
    """Inject a named resource into a RunContext (for middleware/hooks)."""
    if rc._resources is None:
        rc._resources = {}
    rc._resources[name] = resource
