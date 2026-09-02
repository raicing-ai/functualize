"""Job execution engine — single execution path for all entry points.

Provides JobExecutionEngine which handles the complete execution lifecycle:
RunContext-equivalent context creation, DI resolution, hook invocation,
middleware wrapping, and structured result capture.

Only imports from `_types/`, `_primitives/`, `_events/`, and stdlib.
"""

from __future__ import annotations

import inspect
import logging
import sys
import time
import types
from collections.abc import Callable
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Literal,
    Union,
    cast,
    get_args,
    get_origin,
)

from pydantic import ValidationError

from functualize._engine.context import ExecutionContext
from functualize._engine.missing_value import MissingValueError
from functualize._engine.resolution import ResolutionPlan, build_resolution_plan
from functualize._engine.validation import ArgValidator
from functualize._events import EventBus, HookEvent, HookRegistry
from functualize._primitives import DIRegistry, MissingProviderError
from functualize._primitives.capability_names import INJECTED_PARAM_TYPE_NAMES
from functualize._types import AmbiguousJobError, JobResult, RunStatus
from functualize._types.annotations import resolved_hints
from functualize._types.redaction import Secret, redacted_snapshot

NoneType = type(None)

if TYPE_CHECKING:
    from functualize._engine.middleware import ExecutionMiddlewareChain
    from functualize._engine.result import RegisteredJob

logger = logging.getLogger(__name__)


def _per_invocation_types() -> set[type]:
    """The capability types the engine instantiates per invocation.

    Derived from the capability registry (ADR-014), not restated here. It was
    restated here, and there were two lists — the resolution plan's ("is this
    parameter resolvable?") and the resolver's ("instantiate it") — so a type
    present in one but not the other resolved to nothing, with no error.

    Returns a fresh mutable set because both callers add the dynamic
    ``JobConfigView`` type to it.
    """
    from functualize._engine.capabilities.registry import PER_INVOCATION_TYPES

    return set(PER_INVOCATION_TYPES)


class _MinimalConfigView:
    """Minimal config view stub for engine usage without injected factory.

    Satisfies the basic interface expected by RunContext when no
    config_view_factory is provided (test scenarios).
    """

    def __init__(self, section_prefix: str = "") -> None:
        self._prefix = section_prefix

    def get(self, key: str, default: Any = None) -> Any:
        return default

    def set_prefix(self, prefix: str) -> None:
        self._prefix = prefix


def _result_failure(result: Any) -> BaseException | None:
    """The exception a JobResult represents, or None if it succeeded.

    The lifecycle swallows a job's exception into the result, so retry has to
    read failure off the result rather than wait for a raise that never comes.
    """
    if getattr(result, "status", None) is RunStatus.SUCCESS:
        return None
    exception = getattr(result, "exception", None)
    if isinstance(exception, BaseException):
        return exception
    return RuntimeError(f"job failed with status {getattr(result, 'status', None)}")


def _missing_required_fields(error: ValidationError) -> tuple[str, ...]:
    """Top-level field names a :class:`ValidationError` reports as *absent*.

    Only ``missing`` is recoverable by asking (T45): a value that was supplied
    and failed its constraint is a wrong answer, not an absent one, and
    re-prompting for it would loop rather than converge.

    Nested locations are skipped. ``("db", "host")`` names a field inside a
    sub-model, which the caller cannot supply as a flat CLI value — offering to
    collect it would produce an answer the retry silently drops.
    """
    names: list[str] = []
    for detail in error.errors():
        if detail.get("type") != "missing":
            continue
        location = detail.get("loc") or ()
        if len(location) == 1 and isinstance(location[0], str):
            names.append(location[0])
    return tuple(dict.fromkeys(names))


_PROMPTABLE_TYPES: tuple[type, ...] = (str, int, float, bool, Path, Decimal)


def _is_promptable(annotation: Any) -> bool:
    """Whether one typed line of text could plausibly satisfy ``annotation``.

    A prompt collects a **string**. That is enough for a scalar — Pydantic
    coerces ``"5"`` to ``5`` — and hopeless for a sub-model, a list, or a dict:
    whatever the user types fails validation on the retry, so they are
    interrogated for a value they were never able to give and *then* shown the
    field error they would have got for free.

    Optional wrappers are unwrapped, since ``str | None`` is still answerable by
    typing a string. Anything else is left to the ordinary ValidationError path,
    which reports it properly.
    """
    if annotation is None:
        return False
    if annotation is Secret or get_origin(annotation) is Secret:
        return True
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        return any(
            _is_promptable(arg) for arg in get_args(annotation) if arg is not NoneType
        )
    if origin is Literal:
        return True
    if isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return True
        # `BaseModel` and the container types land here and are refused.
        return annotation in _PROMPTABLE_TYPES
    return False


class JobExecutionEngine:
    """Executes jobs with full lifecycle: DI resolution, hooks, middleware.

    This is the single execution path shared by CLI invocations, rc.invoke(),
    and the standalone CLI. All entry points delegate here.

    The engine:
    1. Builds an ExecutionContext for the invocation
    2. Resolves DI parameters from the registry + per-invocation capabilities
    3. Fires lifecycle hooks (pre-execute, before_job, after_success/failure, teardown)
    4. Wraps execution in middleware chain
    5. Returns a structured JobResult

    Args:
        di_registry: The application's DI registry for type resolution.
        hook_registry: Hook registry for lifecycle event dispatch.
        middleware_chain: Middleware chain for job execution wrapping.
        event_bus: EventBus for structured event emission.
        max_invoke_depth: Maximum recursion depth for nested invokes.
    """

    def __init__(
        self,
        di_registry: DIRegistry,
        hook_registry: HookRegistry,
        middleware_chain: ExecutionMiddlewareChain,
        event_bus: EventBus,
        max_invoke_depth: int = 10,
        plugin_config_registry: Any = None,
        resolution_chain: Any = None,
        gate_registry: Any = None,
        config_view_factory: Callable[..., Any] | None = None,
        config_resolver: Callable[..., Any] | None = None,
    ) -> None:
        self._di_registry = di_registry
        self._hook_registry = hook_registry
        self._middleware_chain = middleware_chain
        self._event_bus = event_bus
        self._max_invoke_depth = max_invoke_depth
        self._plugin_config_registry = plugin_config_registry
        self._resolution_chain = resolution_chain
        self._gate_registry = gate_registry
        self._registered_jobs: dict[str, RegisteredJob] = {}
        self._registry_mirrors: list[dict[str, RegisteredJob]] = []
        self._resolution_plan_cache: dict[int, ResolutionPlan] = {}
        # {id(function): ((param_name, GroupOptions subclass), ...)} — usually
        # empty, and the empty answer is what most executions look up (S6a).
        # The class is `Any` because the detection is structural rather than an
        # `issubclass` against the real base (see group_options_detection): the
        # engine must not import `_types.group_options` to answer this.
        self._group_options_cache: dict[int, tuple[tuple[str, Any], ...]] = {}
        self._config_view_factory = config_view_factory
        self._config_resolver = config_resolver
        self._arg_validator = ArgValidator()
        self._workflow_state_store: Any = None
        self._preflight_pipeline: Any = None
        self._job_graph: Any = None
        self._exec_policy_impl: Any = None
        self._workflows_validated_token: tuple[int, int] | None = None
        self._live_step_values: dict[str, dict[str, Any]] = {}
        # Cache the config view type for isinstance/identity checks
        self._config_view_type: type | None = None
        if config_view_factory is not None:
            _probe = config_view_factory(section_prefix="__type_probe__")
            if _probe is not None:
                self._config_view_type = type(_probe)

    def register_job(self, entry: RegisteredJob) -> None:
        """Register a job entry for programmatic lookup."""
        self._registered_jobs[entry.name] = entry
        # The graph is derived from this mapping; a new entry can add edges
        # or resolve a previously unknown reference, so the built graph is
        # stale until it is rebuilt (and revalidated).
        self._job_graph = None

    def add_registry_mirror(self, mirror: dict[str, RegisteredJob]) -> None:
        """Register an external dict holding the same RegisteredJob entries.

        When a lazily-registered entry is materialized (its module imported
        and the frozen RegisteredJob replaced with one carrying the real
        function), the replacement is propagated to every mirror that still
        holds the old entry — keeping e.g. the app-level JobRegistry
        consistent with the engine without the engine importing app types.
        """
        if mirror not in self._registry_mirrors:
            self._registry_mirrors.append(mirror)

    def materialize_job(self, name: str) -> RegisteredJob:
        """Look up a job and guarantee its function is the real callable.

        Same lookup semantics as get_job(); public entry point for callers
        (e.g. the CLI) that need a live function and config_class.

        Raises:
            KeyError: If the job name is not registered.
            AmbiguousJobError: If a bare name matches multiple jobs.
            JobMaterializationError: If the deferred module import fails.
            DIValidationError: If the materialized function has
                unsatisfiable DI bindings.
        """
        return self.get_job(name)

    def resolve_config_model(self, job_name: str) -> Any | None:
        """Resolve a job's config model to a validated instance, without running it.

        The read-only half of what :meth:`execute` does before it invokes the
        job — the full ladder (default < config file < env < …), through the
        same ``_config_resolver`` execution uses, so ``func builtin env`` and
        ``func builtin info --job`` show the values a run would actually see.

        Returns ``None`` when the job declares no config model. Propagates
        ``ValidationError`` when a required field is unresolved: a caller
        asking "what is this job's config?" is better told it is incomplete
        than handed a half-built object.
        """
        entry = self.materialize_job(job_name)
        config_class = entry.config_class
        if config_class is None:
            return None
        config_view = self._make_config_view(job_name)
        if self._config_resolver is not None:
            return self._config_resolver(
                config_class=config_class,
                job_name=job_name,
                config_view=config_view,
                cli_values={},
            )
        return config_class()

    # ── The one fingerprint-key derivation ────────────────────────────────
    #
    # There were three conventions across six call sites, and the writer used
    # a fourth thing again: `compute_args_hash(config, context.call_kwargs)`
    # with the *whole* kwargs mapping. By the time the pre-flight runs, that
    # mapping holds five different kinds of thing, and only one of them
    # belongs in the key:
    #
    #   DI-injected capabilities   no — unreconstructable, and `repr` carries
    #                              a memory address, so a job with a `Log`
    #                              parameter got a new key every single run
    #                              and could never report fresh
    #   the resolved config model  no — already passed as `config`
    #   resolved GroupOptions      no — same, via config resolution
    #   FromJob upstream values    no — derived from an upstream whose own
    #                              freshness is separately checked, and
    #                              circular for a reader to reconstruct
    #   what the CALLER passed     yes
    #
    # Hence: config + (call_kwargs - everything the executor injected). The
    # subtraction is exact rather than a type-sniffing heuristic because the
    # executor recorded each of its own injections in `context.injected`.
    #
    # And because the engine passes no explicit args when it triggers a run
    # itself — a dependency, a `FromJob` upstream, a plain `func <job>` — the
    # explicit half is `{}` there, which is what lets a reader holding only a
    # job name reconstruct the key. See `fingerprint_key_for`.

    def _args_hash_for(self, context: Any) -> str:
        """The args hash for an in-flight run: config + caller-passed args."""
        from functualize._primitives.fingerprint import (
            compute_args_hash,
            config_payload,
        )

        rc = self._run_context_of(context)
        config = getattr(rc, "job_config", None) if rc is not None else None
        injected = getattr(context, "injected", None) or set()
        explicit = {
            name: value
            for name, value in context.call_kwargs.items()
            if name not in injected
        }
        return compute_args_hash(config_payload(config), explicit)

    def fingerprint_key_for(self, job_name: str, method: str) -> str:
        """The key an **engine-triggered** run of ``job_name`` writes under.

        The reader-side counterpart of :meth:`_args_hash_for`. It resolves
        config through :meth:`resolve_config_model`, which is the same
        ``_config_resolver`` execution uses — so reader and writer agree by
        construction rather than by convention.

        The explicit-args half is ``{}`` because that is what an
        engine-triggered run has: a dependency, a `FromJob` upstream and a
        plain ``func <job>`` all pass no arguments of their own.

        Propagates nothing: an unresolvable config degrades to ``None`` here,
        because every caller is a *read* path (`why`, a `FromJob` lookup) that
        must not turn a missing config field into a crash.
        """
        from functualize._primitives.fingerprint import (
            compute_args_hash,
            config_payload,
            fingerprint_key,
        )

        try:
            config = self.resolve_config_model(job_name)
        except Exception as exc:
            # `resolve_config_model` deliberately propagates ValidationError.
            # A read path degrades — but says so, rather than silently
            # answering as though the job declared no config.
            logger.debug(
                "config for %r could not be resolved while deriving its "
                "fingerprint key (%s); using no config",
                job_name,
                exc,
            )
            config = None
        args_hash = compute_args_hash(config_payload(config), {})
        return fingerprint_key(job_name, args_hash, method)

    def _ensure_materialized(self, entry: RegisteredJob) -> RegisteredJob:
        """Materialize a lazily-registered entry; no-op for live entries.

        Imports the job module (once), replaces the frozen RegisteredJob
        with one carrying the real function and detected config_class
        (never clobbering an explicit config_class), swaps the entry in
        the engine registry and all mirrors, and runs the deferred DI
        binding validation on the real function.
        """
        function: Any = entry.function
        if not getattr(function, "__functualize_lazy__", False):
            return entry

        import dataclasses

        from functualize._primitives.di import DIValidationError

        real_fn, detected_config = function.materialize()
        new_entry = dataclasses.replace(
            entry,
            function=real_fn,
            config_class=entry.config_class or detected_config,
        )

        # Swap in own registry + mirrors, only where the old entry still sits
        if self._registered_jobs.get(entry.name) is entry:
            self._registered_jobs[entry.name] = new_entry
        for mirror in self._registry_mirrors:
            if mirror.get(entry.name) is entry:
                mirror[entry.name] = new_entry

        # Deferred DI validation (skipped at boot for lazy entries)
        errors = self._di_binding_errors(entry.name, real_fn)
        if errors:
            raise DIValidationError(errors)

        return new_entry

    def _make_config_view(self, section_prefix: str) -> Any:
        """Create a config view using the injected factory.

        Uses the config_view_factory injected at construction time.
        The factory encapsulates the resolution chain and creates
        properly-scoped config views without requiring _config imports.

        If no factory is injected (e.g., in tests), returns a minimal
        stub that satisfies the ConfigView protocol.

        Args:
            section_prefix: The default section prefix for config lookups.

        Returns:
            A ConfigView-compatible instance.
        """
        if self._config_view_factory is not None:
            return self._config_view_factory(section_prefix=section_prefix)
        # Minimal stub for test scenarios without factory injection
        return _MinimalConfigView(section_prefix)

    def _make_empty_chain(self) -> Any:
        """Create an empty resolution chain using the injected factory or fallback."""
        if self._config_view_factory is not None:
            return self._resolution_chain
        return None

    def validate_di_bindings(self) -> None:
        """Validate that all registered jobs have satisfiable DI bindings.

        Inspects each registered job's function signature and tries to resolve
        each class-typed parameter from the DI registry. Collects ALL errors
        (doesn't fail-fast) and raises DIValidationError if any are found.

        Per-invocation types (RunContext, Log, etc.) are excluded from validation.
        Optional[T] parameters are excluded (they resolve to None gracefully).

        Lazily-registered jobs (LazyJobFunction entries, warm-cache boot)
        are skipped here; their validation runs at materialization
        (first use) via _ensure_materialized.

        Raises:
            DIValidationError: If any job has unsatisfiable DI bindings.
        """
        from functualize._primitives.di import DIValidationError, ResolutionError

        errors: list[ResolutionError] = []

        for name, entry in self._registered_jobs.items():
            if getattr(entry.function, "__functualize_lazy__", False):
                continue
            errors.extend(self._di_binding_errors(name, entry.function))

        if errors:
            raise DIValidationError(errors)

    def _di_binding_errors(self, name: str, func: Callable[..., Any]) -> list[Any]:
        """Collect DI binding errors for a single job function.

        The per-job body of validate_di_bindings, extracted so the same
        validation can run deferred at materialization time.
        """
        from typing import get_type_hints

        from functualize._engine.resolution import (
            _extract_provide_qualifier,
            _is_optional_type,
        )
        from functualize._primitives.di import (
            AmbiguousProviderError,
            MissingProviderError,
            ResolutionError,
        )

        errors: list[ResolutionError] = []

        # Per-invocation types handled by the engine, not the DI registry —
        # the one list (see _primitives/capability_names).
        per_invocation_type_names = INJECTED_PARAM_TYPE_NAMES

        sig = inspect.signature(func)

        try:
            hints = get_type_hints(func, include_extras=True)
        except Exception:
            hints = {}

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            annotation = hints.get(param_name, param.annotation)

            if annotation is inspect.Parameter.empty:
                continue

            if isinstance(annotation, str):
                continue

            # Handle Optional[T]
            is_optional, inner_type = _is_optional_type(annotation)
            if is_optional:
                # Optional params always resolve to None if no provider — skip
                continue

            # Skip `FromJob` parameters — the engine injects these from the
            # upstream's recorded value, so the DI registry is not supposed to
            # have a provider for them. Without this, declaring
            # `Annotated[Report, FromJob("make-report")]` on a *discovered* job
            # fails boot with "No provider for Report". It went unnoticed
            # because every existing test annotates a builtin (`str`), and
            # builtins are skipped two checks below.
            from functualize._types.from_job import FromJob

            if any(
                isinstance(meta, FromJob)
                for meta in (
                    get_args(annotation)[1:]
                    if get_origin(annotation) is Annotated
                    else ()
                )
            ):
                continue

            # Extract qualifier from Annotated
            base_type, qualifier = _extract_provide_qualifier(annotation)

            # Skip non-class types (int, str, etc.)
            if not isinstance(base_type, type):
                continue

            # Skip per-invocation types
            if base_type.__name__ in per_invocation_type_names:
                continue

            # Skip builtin types (int, str, float, bool, etc.)
            if base_type.__module__ == "builtins":
                continue

            # Skip Pydantic models (config types resolved via config chain)
            try:
                from pydantic import BaseModel as _PydanticBaseModel

                if issubclass(base_type, _PydanticBaseModel):
                    continue
            except ImportError:
                pass

            # Try resolving from DI registry
            try:
                self._di_registry.resolve(
                    base_type,
                    qualifier=qualifier,
                )
            except MissingProviderError as e:
                e.job_name = name
                errors.append(e)
            except AmbiguousProviderError as e:
                e.job_name = name
                errors.append(e)
            except Exception as e:
                err = ResolutionError(
                    f"Factory error for {base_type.__name__} in job '{name}': {e}"
                )
                err.__cause__ = e
                errors.append(err)

        return errors

    def get_job(self, name: str) -> RegisteredJob:
        """Look up a registered job by qualified name, with fallback.

        Delegates to :func:`~functualize._types.naming.resolve_name`, the one
        naming policy — exact match, then normalized match (so ``invoke(
        "build_wheel")`` reaches the registered ``build-wheel``), then leaf
        match (so a bare name finds ``build.compile-it``).

        This used to carry its own lookup, which made it the *fifth*
        implementation of "what job does this name mean". The others were
        consolidated into `JobGraph`; this one was reachable only through
        `rc.invoke`, so it drifted quietly — it could not resolve a Python
        spelling, and a caller who typed one got a bare KeyError.

        Args:
            name: The registered job name (qualified, bare, or in the Python
                spelling of either).

        Returns:
            The RegisteredJob metadata.

        Raises:
            KeyError: If the job name is not registered and no fallback match.
            AmbiguousJobError: If a bare name matches multiple qualified names.
        """
        from functualize._types.naming import resolve_name

        if name in self._registered_jobs:
            return self._ensure_materialized(self._registered_jobs[name])

        try:
            resolved = resolve_name(name, self._registered_jobs)
        except LookupError as exc:
            if "ambiguous" in str(exc):
                matches = [
                    qualified
                    for qualified in self._registered_jobs
                    if qualified.rsplit(".", 1)[-1] == name.rsplit(".", 1)[-1]
                ]
                raise AmbiguousJobError(name, matches) from exc
            raise KeyError(f"Job '{name}' not found in engine registry") from exc

        return self._ensure_materialized(self._registered_jobs[resolved])

    def execute(
        self,
        job_name: str,
        function: Callable[..., Any],
        *,
        kwargs: dict[str, Any],
        invoke_depth: int = 0,
        cwd: Path | None = None,
        job_directory: Path | None = None,
        config_class: type | None = None,
        parent_scope: Any | None = None,
        workflow_scope_id: str | None = None,
        run_dependencies: bool = True,
        force_fresh: bool = False,
        force: bool = False,
        group_option_values: dict[str, Any] | None = None,
    ) -> JobResult:
        """Execute a job, then record the run in history (T42).

        The lifecycle itself is :meth:`_execute_lifecycle`; this wrapper exists
        only so that history is written on **every** way out of it — the normal
        return, a validation failure, a blocked pre-flight, a failed dependency
        — from one place rather than five. Instrumenting the five return points
        by hand is how one of them ends up forgotten and a whole class of run
        silently stops being recorded.

        Only **top-level** runs are recorded (``invoke_depth == 0``). A
        workflow's steps, a job's dependencies, and ``rc.invoke`` children all
        run at ``invoke_depth + 1``; recording them would bury the handful of
        things the user actually launched under the internals of one of them,
        and a 200-record ring would evict real history within a single deep
        workflow.
        """
        result = self._execute_lifecycle(
            job_name,
            function,
            kwargs=kwargs,
            invoke_depth=invoke_depth,
            cwd=cwd,
            job_directory=job_directory,
            config_class=config_class,
            parent_scope=parent_scope,
            workflow_scope_id=workflow_scope_id,
            run_dependencies=run_dependencies,
            force_fresh=force_fresh,
            force=force,
            group_option_values=group_option_values,
        )
        if invoke_depth == 0:
            self._record_history(job_name, kwargs, result)
        return result

    def _record_history(
        self, job_name: str, kwargs: dict[str, Any], result: JobResult
    ) -> None:
        """Append one run record to the state store's history ring (T42).

        Best-effort and silent, exactly like the shell-mode recorder it shares
        the ring with: history is a convenience, so a store that cannot be
        written must not turn a job that ran fine into a visible failure. The
        one thing worth being strict about is what it must *not* write —
        argument values, which can be secrets. Only the ``args_hash`` goes in,
        so the record identifies a run without persisting its inputs (schema
        §1: secrets are never stored in history, hashed only).
        """
        from datetime import UTC, datetime

        try:
            from functualize._primitives.fingerprint import compute_args_hash

            record = {
                "namespace": "job",
                "job": job_name,
                "args_hash": compute_args_hash(call_args=self._hashable(kwargs)),
                "status": result.status.value.lower(),
                "duration_ms": round(result.duration_ms, 3),
                "at": datetime.now(UTC).isoformat(),
            }
            self._state_store().append_history(record)
        except Exception as exc:  # noqa: BLE001 - convenience, never fatal
            logger.warning(
                "could not record job history (%s: %s)", type(exc).__name__, exc
            )

    @staticmethod
    def _hashable(kwargs: dict[str, Any]) -> dict[str, Any]:
        """A JSON-safe view of ``kwargs`` for hashing only.

        Non-serializable arguments (a DI capability, a live object) become
        their type name — the hash need only be stable and collision-resistant
        for "the same call", not reversible, and it is never stored.
        """
        safe: dict[str, Any] = {}
        for key, value in kwargs.items():
            if isinstance(value, (str, int, float, bool, type(None))):
                safe[key] = value
            else:
                safe[key] = f"<{type(value).__name__}>"
        return safe

    def _execute_lifecycle(
        self,
        job_name: str,
        function: Callable[..., Any],
        *,
        kwargs: dict[str, Any],
        invoke_depth: int = 0,
        cwd: Path | None = None,
        job_directory: Path | None = None,
        config_class: type | None = None,
        parent_scope: Any | None = None,
        workflow_scope_id: str | None = None,
        run_dependencies: bool = True,
        force_fresh: bool = False,
        force: bool = False,
        group_option_values: dict[str, Any] | None = None,
    ) -> JobResult:
        """Execute a job with full lifecycle.

        Creates ExecutionContext, resolves DI parameters, invokes hooks,
        wraps middleware, and returns structured result.

        Args:
            job_name: Registered job name.
            function: The job callable.
            kwargs: Arguments passed (Python values, no string coercion).
            invoke_depth: Current recursion depth.
            cwd: Working directory (defaults to Path.cwd()).
            job_directory: Directory containing the job source file.
            config_class: Optional Pydantic model for config validation.
            parent_scope: WorkflowScope to propagate to child context.
            workflow_scope_id: For a `@workflow` job, the scope to resume.
                Omitted, each invocation walks a fresh scope (§A.7).
            group_option_values: Flat ``{field: raw_value}`` map of group flags
                given mid-path on the command line (S6a). The non-CLI layers
                resolve without it, so a programmatic ``invoke()`` omits it.

        Returns:
            JobResult with status, duration, return value, metadata.
        """
        # Materialize lazy functions BEFORE any signature introspection so
        # resolution-plan/validator caches key on the real function and the
        # ExecutionContext carries it. Callers that fetched the entry from a
        # bypassing registry (e.g. app.execute via JobRegistry) land here.
        if getattr(function, "__functualize_lazy__", False):
            entry = self._registered_jobs.get(job_name)
            if entry is not None and entry.function is function:
                entry = self._ensure_materialized(entry)
                function = entry.function
                if config_class is None:
                    config_class = entry.config_class
            else:
                lazy_fn: Any = function
                real_fn, detected_config = lazy_fn.materialize()
                errors = self._di_binding_errors(job_name, real_fn)
                if errors:
                    from functualize._primitives.di import DIValidationError

                    raise DIValidationError(errors)
                function = real_fn
                if config_class is None:
                    config_class = detected_config

        start_time = time.perf_counter()

        # Build execution context. Constructed *above* the workflow prelude, not
        # below it, because a `@workflow` job can be refused before the prelude
        # walks — and that refusal fires AFTER_FAILURE, which needs a context to
        # hand the hook. The prelude itself does not read `context`, so its
        # position here is inert for every path that reaches the walk.
        context = ExecutionContext(
            job_name=job_name,
            function=function,
            call_kwargs=dict(kwargs),
            invoke_depth=invoke_depth,
            cwd=cwd,
            job_directory=job_directory,
            start_time=start_time,
            config_class=config_class,
            parent_scope=parent_scope,
        )

        # The @workflow prelude (§A.7): walk the declared graph first, and run
        # the body only if it reached END. A blocked or failed walk returns
        # here, before DI resolution and before any hook fires — the body is
        # the job, and the job has not been reached yet.
        workflow_runner = None
        declaration = getattr(function, "__functualize_workflow__", None)
        if declaration is not None:
            workflow_runner, early = self._run_workflow_prelude(
                job_name,
                declaration,
                scope_id=workflow_scope_id,
                invoke_depth=invoke_depth,
                start_time=start_time,
            )
            if early is not None:
                return early

        # Resolve DI parameters
        try:
            di_kwargs, per_invocation_caps = self._resolve_di_parameters(
                function, context
            )
            context.capabilities = per_invocation_caps
            # Only inject DI params not already provided by caller
            for param_name, value in di_kwargs.items():
                if param_name not in context.call_kwargs:
                    context.call_kwargs[param_name] = value
                    context.injected.add(param_name)
        except MissingProviderError:
            raise

        # Ensure RunContext is always available in capabilities for middleware
        from functualize._engine.capabilities.runcontext import RunContext

        if RunContext not in (context.capabilities or {}):
            if context.capabilities is None:
                context.capabilities = {}
            job_config = self._make_config_view(job_name)
            rc = RunContext(
                name=job_name,
                config=job_config,
                logger=logging.getLogger(f"functualize.job.{job_name}"),
                plugin_configs=(
                    self._plugin_config_registry.get_all()
                    if self._plugin_config_registry is not None
                    else None
                ),
                cwd=cwd,
                job_directory=job_directory,
                _invoke_depth=invoke_depth,
                _max_invoke_depth=self._max_invoke_depth,
                _execution_engine=self,
                _di_registry=self._di_registry,
                _workflow_scope=parent_scope,
                _caps=context.capabilities,
            )
            context.capabilities[RunContext] = rc

        # Resolve config, then validate function arguments against Field()
        # constraints. Both run BEFORE PRE_EXECUTE hooks, and both raise
        # ValidationError — so both belong in the same handler. Config
        # resolution used to sit outside it, which meant a missing required
        # config field escaped `execute()` as a raised exception instead of a
        # FAILURE result. The CLI renders `result.exception` as a field-level
        # error panel and can only do that for a *returned* JobResult, so the
        # most common user error was the one that printed a raw traceback.
        try:
            if config_class is not None:
                self._resolve_config_model(function, context, config_class, job_name)

            # After the job's own config: a GroupOptions parameter is never the
            # job's config class (see _primitives/group_options_detection), so
            # the two never contend for the same parameter.
            self._resolve_group_options(function, context, group_option_values)

            validated_kwargs = self._arg_validator.validate(
                function, context.call_kwargs
            )
            context.call_kwargs = validated_kwargs
            # What the job was *actually* given, after config resolution and
            # coercion — the only honest answer to "why did this step do that",
            # and the thing a workflow step record has to carry. Secrets are
            # masked here rather than at the reader: this lands in state.json
            # and is handed to external agents over MCP.
            context.metadata["resolved_inputs"] = redacted_snapshot(context.call_kwargs)
        except (ValidationError, MissingValueError) as validation_error:
            # `MissingValueError` joins `ValidationError` here rather than
            # escaping (T45): it is raised *from* config resolution when no
            # surface could answer, so it is the same failure by a clearer
            # name. Letting it propagate would break the invariant this handler
            # exists for — every config failure comes back as a FAILURE
            # JobResult the CLI can render, never a raw traceback.
            # On validation failure: fire AFTER_FAILURE hook, return FAILURE
            # without invoking PRE_EXECUTE hooks or executing the function
            duration_ms = context.elapsed_ms

            # Build RunContext for hooks (same pattern as _execute_with_lifecycle)
            from functualize._engine.capabilities.runcontext import (
                RunContext as _RunContext,
            )

            _rc_for_hooks = (
                context.capabilities.get(_RunContext, context)
                if context.capabilities
                else context
            )
            self._hook_registry.invoke(
                HookEvent.AFTER_FAILURE,
                job_name,
                _rc_for_hooks,
                exception=validation_error,
            )

            self._event_bus.emit(
                "job.execute.end",
                resource=job_name,
                job_name=job_name,
                duration_ms=duration_ms,
                status="failure",
            )

            return JobResult(
                status=RunStatus.FAILURE,
                return_value=None,
                duration_ms=duration_ms,
                metadata=dict(context.metadata),
                exception=validation_error,
                job_name=job_name,
            )

        # Dependencies (§D.1) run before pre-flight, not after: a dep may
        # regenerate a file that this job fingerprints, so checking staleness
        # first would compare against sources the dep is about to change. Same
        # ordering make uses — build prerequisites, then compare timestamps.
        if run_dependencies:
            dep_failure = self._run_dependencies(
                job_name, function, context, invoke_depth, workflow_scope_id
            )
            if dep_failure is not None:
                return dep_failure

        # Inject `FromJob` values after the upstreams have run, before the
        # pre-flight decision — a guard may be a callable reading one.
        self._inject_from_job(job_name, function, context, workflow_scope_id)

        # Pre-flight (§D.2/§D.3): guards and file staleness decide whether the
        # body runs at all. Placed after config resolution because a guard may
        # be a callable taking the resolved config, and before PRE_EXECUTE
        # because a skipped job must not fire hooks that assume it ran.
        if self._run_mode_skip(job_name, function, context):
            duration_ms = (time.perf_counter() - start_time) * 1000
            metadata = dict(context.metadata)
            metadata["skip_reason"] = "already ran this session (Exec.run)"
            return JobResult(
                status=RunStatus.SKIPPED,
                return_value=None,
                duration_ms=duration_ms,
                metadata=metadata,
                job_name=job_name,
            )

        from functualize._engine.guards import GuardState

        preflight_decision = self._preflight_check(job_name, function, context)

        # Fill in the `Sources` capability, if the job asked for one. This sits
        # before the force branch below on purpose: that branch discards the
        # decision, and discarding it after binding would hand a job an empty
        # source map on exactly the runs a `FromJob` dependent triggers.
        self._bind_preflight_capabilities(context, preflight_decision)

        # Two overrides, and they are not the same claim.
        #
        # `force_fresh` comes from the workflow walker, for a `FromJob`
        # dependent that needs this job's *value* when the recorded one cannot
        # be reused. Freshness answers "are the outputs on disk current?" — it
        # says nothing about a return value that was never storable, so
        # honouring it there would hand the dependent nothing. It overrides
        # **only** SKIP_FRESH: a platform mismatch, a satisfied `status` guard
        # or a gate awaiting input all still stand, because wanting a value is
        # not a reason to run somewhere the job does not belong.
        #
        # `force` comes from a person typing `--force`, which is the stronger
        # claim "run anyway" — so it also overrides a satisfied `status` guard,
        # matching Taskfile's `-f`. Neither overrides a failing `Precondition`
        # (still exit 3) or a gate (still exit 5): those say the declared
        # conditions for running were not met, and `--force` does not change
        # what is true about the world. Neither touches the `Exec.run` skip
        # above, which is intra-run de-duplication rather than a freshness
        # claim.
        if preflight_decision is not None:
            _state = preflight_decision.verdict.state
            if (force_fresh and _state is GuardState.SKIP_FRESH) or (
                force and _state in (GuardState.SKIP_FRESH, GuardState.SKIP_SATISFIED)
            ):
                preflight_decision = None
        if preflight_decision is not None and not preflight_decision.should_run:
            return self._preflight_result(
                job_name, context, preflight_decision, start_time
            )

        # Fire pre-execute hooks
        self._event_bus.emit(
            "job.execute.start",
            resource=job_name,
            job_name=job_name,
            invoke_depth=invoke_depth,
        )

        # Mark execution phase on perf timeline (only for top-level invocations)
        from functualize._events.perf import perf_timeline

        if invoke_depth == 0:
            perf_timeline.mark(f"execution.{job_name}.start")

        # Execute with lifecycle. The finally is the engine-owned unwind for
        # sh.defer() (§B.5): it covers success, failure, Ctrl+C
        # (KeyboardInterrupt propagates) — the cases a user-level try/finally
        # in job code cannot be trusted to cover.
        try:
            result: JobResult = self._exec_policy().call(
                lambda: self._execute_with_lifecycle(context),
                getattr(getattr(function, "__functualize_job__", None), "exec", None),
                job_name=job_name,
                failure_of=_result_failure,
            )
        finally:
            self._run_deferred_shells(context)

        if invoke_depth == 0:
            perf_timeline.mark(f"execution.{job_name}.end")

        if workflow_runner is not None:
            # Body-once-per-scope (§A.7): record what it returned so replaying
            # a finished scope answers with the same value instead of running
            # the body again.
            workflow_runner.record_body(
                result.return_value,
                status="success" if result.status is RunStatus.SUCCESS else "failed",
            )
            result.metadata["workflow_scope"] = workflow_runner.scope_id

        # Record staleness only for a run that actually succeeded: writing a
        # fingerprint after a failure would mark the job current and skip the
        # retry the user is about to make.
        if preflight_decision is not None and result.status is RunStatus.SUCCESS:
            declaration = getattr(function, "__functualize_job__", None)
            if declaration is not None:
                self._preflight().record(
                    job_name,
                    declaration,
                    key=preflight_decision.key,
                    return_value=result.return_value,
                )

        return result

    def _state_store(self) -> Any:
        """The runtime state store, resolved the way `func state` resolves it.

        Built lazily and cached: most jobs never touch it, and resolving the
        path walks the filesystem upward looking for `.functualize/`.
        """
        if self._workflow_state_store is None:
            from functualize._primitives.state_store import StateStore

            self._workflow_state_store = StateStore.for_project(Path.cwd())
        return self._workflow_state_store

    def _validate_workflows_once(self) -> None:
        """Run workflow validation once per registry generation.

        Keyed on the registry's size and the graph object's identity: a new
        registration replaces the graph (`register_job` invalidates it), so a
        job added after the last validation forces another pass. Cheap enough
        to be unconditional, and unconditional is the point — a check that
        runs only on some paths is not a check.
        """
        token = (len(self._registered_jobs), id(self._job_graph))
        if getattr(self, "_workflows_validated_token", None) == token:
            return

        from functualize._engine.workflow_validation import (
            validate_workflow_declarations,
        )

        validate_workflow_declarations(registry=self._registered_jobs)
        self._workflows_validated_token = token

    def _run_workflow_prelude(
        self,
        job_name: str,
        declaration: Any,
        *,
        scope_id: str | None,
        invoke_depth: int,
        start_time: float,
    ) -> tuple[Any, JobResult | None]:
        """Walk a `@workflow` job's graph before its body runs.

        Returns the runner (so the caller can record the epilogue) and, when
        the body must not run, the `JobResult` to return instead.
        """
        # Validate before walking, not only at boot. `register_dynamic_job`
        # never calls the boot validator, so a dynamically registered workflow
        # reached a live walk unchecked — the same second-door shape SG closed
        # for the job graph. Validation is memoized per registry generation, so
        # this costs one pass rather than one per invocation.
        self._validate_workflows_once()

        from functualize._engine.workflow_runner import WorkflowRunner
        from functualize._engine.workflow_walker import (
            StepBlocked,
            StepOutcome,
            WalkOutcome,
        )

        def run_step(step_name: str) -> Any:
            entry = self.get_job(step_name)
            step_result = self.execute(
                step_name,
                entry.function,
                kwargs={},
                invoke_depth=invoke_depth + 1,
                config_class=entry.config_class,
                # Run the step *inside* the scope, so a `FromJob` parameter
                # resolves against what the walk has already recorded rather
                # than falling through to the fingerprint store and, finding
                # nothing, silently taking the parameter's default.
                #
                # Unless the step is itself a workflow: a nested workflow owns
                # its own scope (§A.7), and handing it the parent's would make
                # the two walks share one set of step records and one epilogue
                # slot — the inner body's return value would surface as the
                # outer's.
                # A nested workflow's scope is *derived*, not fresh. It must
                # still be its own scope — sharing the parent's would merge
                # two sets of step records and two epilogue slots, surfacing
                # the inner body's return value as the outer's — but it must
                # also be the *same* scope on re-entry, or a gate inside it
                # can never be resumed: each parent run would spawn a new
                # child, and the input an agent deposited would belong to a
                # scope nothing re-enters (Part I cell G×W×W).
                workflow_scope_id=(
                    f"{runner.scope_id}::{step_name}"
                    if getattr(entry.function, "__functualize_workflow__", None)
                    else runner.scope_id
                ),
            )
            # SKIPPED counts as satisfied: a step whose guards or fingerprint
            # said "no work to do" has done its job, and failing the walk over
            # it would make declaring a cache on a step break every workflow
            # using it.
            # A nested workflow that stopped at a gate has not failed. It
            # must reach the parent walk as a block, or the parent records the
            # step failed, marks its own scope failed, and resuming the child
            # leaves the parent permanently failed (Part I cell G×W×W).
            if step_result.status is RunStatus.BLOCKED:
                raise StepBlocked(
                    str(step_result.metadata.get("workflow_scope") or ""),
                    str(step_result.metadata.get("blocked_on") or step_name),
                )
            if step_result.status not in (RunStatus.SUCCESS, RunStatus.SKIPPED):
                # Surface the step's own exception rather than a wrapper, so
                # the walk records the reason the step actually failed.
                raise step_result.exception or RuntimeError(
                    f"step {step_name!r} returned {step_result.status.value}"
                )
            # Keep the in-process value for the walk's lifetime. If this
            # step's return cannot be carried through the state store, a later
            # step reading it with `FromJob` has nowhere else to look, and
            # re-running is not available inside a walk (resolved 19b).
            self.publish_live_step_value(
                runner.scope_id, step_name, step_result.return_value
            )

            return StepOutcome(
                step_result.return_value,
                dict(step_result.metadata.get("resolved_inputs") or {}),
            )

        runner = WorkflowRunner(
            self._state_store(),
            run_step=run_step,
            scope_id=scope_id,
            gate_registry=self._gate_registry,
            prompt_gates=getattr(getattr(self, "_app", None), "_prompt_gates", False),
        )
        run = runner.prelude(job_name, declaration)
        if run.should_run_body:
            return runner, None

        duration_ms = (time.perf_counter() - start_time) * 1000
        metadata: dict[str, Any] = {
            "workflow_scope": run.scope_id,
            "workflow_status": run.outcome.value,
        }
        if run.body_done:
            # An already-completed scope: replaying it is a no-op that answers
            # with the value the body returned the first time.
            return None, JobResult(
                status=RunStatus.SUCCESS,
                return_value=run.body_value,
                duration_ms=duration_ms,
                metadata=metadata,
                job_name=job_name,
            )
        if run.outcome is WalkOutcome.BLOCKED:
            metadata["blocked_on"] = run.blocked_on
            return None, JobResult(
                status=RunStatus.BLOCKED,
                return_value=None,
                duration_ms=duration_ms,
                metadata=metadata,
                job_name=job_name,
            )
        return None, JobResult(
            status=RunStatus.FAILURE,
            return_value=None,
            duration_ms=duration_ms,
            metadata=metadata,
            exception=RuntimeError(run.error) if run.error else None,
            job_name=job_name,
        )

    def _get_resolution_plan(self, function: Callable[..., Any]) -> ResolutionPlan:
        """Get or build a ResolutionPlan for a function (cached by id(function))."""
        func_id = id(function)
        if func_id in self._resolution_plan_cache:
            return self._resolution_plan_cache[func_id]

        from functualize._engine.capabilities.runcontext import RunContext

        registered_types = set(self._di_registry.available_types())
        # Per-invocation capability types are always resolvable even when
        # not explicitly registered in the DI registry
        _config_view_type = self._config_view_type
        per_invocation_types = _per_invocation_types()
        if _config_view_type is not None:
            per_invocation_types.add(_config_view_type)
        registered_types |= per_invocation_types

        plan = build_resolution_plan(
            function,
            registered_types=registered_types,
            runcontext_type=RunContext,
        )
        self._resolution_plan_cache[func_id] = plan
        return plan

    def _resolve_di_parameters(
        self,
        function: Callable[..., Any],
        context: ExecutionContext,
    ) -> tuple[dict[str, Any], dict[type, Any]]:
        """Resolve DI-annotated parameters for a job function invocation.

        Uses the cached ResolutionPlan to determine which parameters should
        be resolved from the DI registry.

        Args:
            function: The job callable.
            context: The execution context.

        Returns:
            Tuple of (resolved_kwargs, per_invocation_capabilities).

        Raises:
            MissingProviderError: If a required parameter type has no provider.
        """
        plan = self._get_resolution_plan(function)
        resolved: dict[str, Any] = {}
        per_invocation_caps: dict[type, Any] = {}

        _config_view_type = self._config_view_type
        per_invocation_type_set = _per_invocation_types()
        if _config_view_type is not None:
            per_invocation_type_set.add(_config_view_type)

        for binding in plan.params:
            if binding.source == "skip":
                continue

            if binding.source == "runcontext":
                # RunContext is created per-invocation and injected
                from functualize._engine.capabilities.runcontext import RunContext

                # Build a config view using the injected factory
                job_config = self._make_config_view(context.job_name)

                rc = RunContext(
                    name=context.job_name,
                    config=job_config,
                    logger=logging.getLogger(f"functualize.job.{context.job_name}"),
                    plugin_configs=(
                        self._plugin_config_registry.get_all()
                        if self._plugin_config_registry is not None
                        else None
                    ),
                    cwd=context.cwd,
                    job_directory=context.job_directory,
                    _invoke_depth=context.invoke_depth,
                    _max_invoke_depth=self._max_invoke_depth,
                    _execution_engine=self,
                    _di_registry=self._di_registry,
                    _workflow_scope=context.parent_scope,
                    _caps=per_invocation_caps,
                )
                resolved[binding.name] = rc
                per_invocation_caps[RunContext] = rc
                continue

            if binding.source == "di":
                # Check if this is a per-invocation capability type
                if (
                    binding.annotation in per_invocation_type_set
                    and binding.qualifier is None
                ):
                    # An OPTIONAL tty (tty: TTY | None) degrades to None when
                    # terminal ownership cannot be granted, so an adaptive job
                    # (`if tty is not None`) falls through to its live/plain
                    # path instead of getting a handle whose run() would raise.
                    # A required tty (tty: TTY) is always injected — the body
                    # may assume it, and tty.run refuses at the floor. Guarded
                    # on is_optional (rare) to keep the common path import-free.
                    if binding.is_optional:
                        from functualize._engine.capabilities.tty import (
                            TTY as _TTY,
                        )
                        from functualize._engine.capabilities.tty import (
                            terminal_available,
                        )

                        if binding.annotation is _TTY and not terminal_available():
                            resolved[binding.name] = None
                            continue

                    # Create fresh per-invocation instance
                    if binding.annotation not in per_invocation_caps:
                        instance = self._create_per_invocation_cap(
                            binding.annotation, context, per_invocation_caps
                        )
                        per_invocation_caps[binding.annotation] = instance
                    resolved[binding.name] = per_invocation_caps[binding.annotation]
                    continue

                # Per-invocation capabilities take precedence over DI registry
                if (
                    binding.annotation in per_invocation_caps
                    and binding.qualifier is None
                ):
                    resolved[binding.name] = per_invocation_caps[binding.annotation]
                    continue

                # Try resolving from the DI registry
                try:
                    instance = self._di_registry.resolve(
                        binding.annotation,
                        qualifier=binding.qualifier,
                        caps=per_invocation_caps,
                    )
                    resolved[binding.name] = instance
                except MissingProviderError:
                    if binding.is_optional:
                        resolved[binding.name] = None
                    else:
                        raise

        return resolved, per_invocation_caps

    def _create_per_invocation_cap(
        self,
        type_: type,
        context: ExecutionContext,
        caps: dict[type, Any],
    ) -> Any:
        """Create a fresh per-invocation capability instance.

        A lookup in the capability registry, not a ladder over concrete types.
        It was a 129-line ``if/elif`` chain ending in a bare ``type_()``
        fallback, so a capability whose branch was never added was constructed
        with no arguments — which either worked by accident or produced an
        inert object, and never said which. Every branch is now a
        ``CapabilitySpec.factory`` written beside its capability (ADR-014).

        Args:
            type_: The capability type to create.
            context: The current execution context.
            caps: Already-created per-invocation capabilities.

        Returns:
            A new instance of the capability type.

        Raises:
            KeyError: If ``type_`` is not in the registry. Deliberately loud:
                the old silent fallback is the failure this replaced.
        """
        from functualize._engine.capabilities.registry import (
            SPEC_BY_TYPE,
            CapabilityContext,
        )

        # The one type resolved by *identity against a runtime value* rather
        # than statically: the config-view class is discovered at boot, so it
        # cannot be a key in a registry written at import time.
        if self._config_view_type is not None and type_ is self._config_view_type:
            return self._make_config_view(context.job_name)

        spec = SPEC_BY_TYPE.get(type_)
        if spec is None or spec.factory is None:
            raise KeyError(
                f"no capability factory for {type_!r}. Declare a CapabilitySpec "
                f"beside the capability and add its name to "
                f"_primitives/capability_names.INJECTED_PARAM_TYPE_NAMES; see "
                f"contributor/adr/014-capability-registry.md."
            )
        return spec.factory(CapabilityContext(engine=self, context=context, caps=caps))

    def _run_deferred_shells(self, context: ExecutionContext) -> None:
        """Unwind ``sh.defer()`` registrations for this invocation (§B.5).

        Owned by the engine because it owns job lifecycle. Never raises — a
        cleanup failure must not replace the job's own result or exception.
        """
        caps = context.capabilities
        if not caps:
            return
        from functualize._types.shell import Shell

        shell = caps.get(Shell)
        run_deferred = getattr(shell, "run_deferred", None)
        if run_deferred is None:
            return
        try:
            run_deferred()
        except Exception:
            logger.warning("Deferred shell unwind failed", exc_info=True)

    def _resolve_prompt_capability(self) -> Any:
        """A ``Prompt`` bound to the active collector, or ``None``.

        ``None`` when nothing can collect — which is the non-interactive
        answer, and is what turns a would-be hang into a typed error at the
        call site (see ``_engine/missing_value``).
        """
        from functualize._engine.capabilities.prompt import Prompt as _Prompt
        from functualize._engine.surface_routing import active_collector

        collector = active_collector(getattr(self, "_app", None))
        if collector is None:
            return None
        return _Prompt(_provider=collector)

    def _resolve_shell_sinks(
        self,
    ) -> tuple[Callable[[str], None] | None, Callable[[str], None] | None]:
        """Bind the Shell's two channels to the active surface (S6b T-S6b-3).

        Returns ``(echo_sink, output_sink)``:

        * **echo** — the command line being run. Diagnostic, so it shares
          ``log()``'s destination: **stderr** when piped. Sending it to stdout
          would interleave "$ git status" into a caller's data stream.
        * **output** — live output under ``stream=True``. Data, so it goes to
          **stdout** when piped (§C.1), which is what makes
          ``func build | grep …`` work.

        A TUI surface overrides both with its panel writer; the fallback below
        is the plain/piped CLI, which is also the right answer for a job run
        under MCP or from a test.
        """
        app = getattr(self, "_app", None)
        writer = getattr(app, "shell_surface_writer", None) if app else None
        if callable(writer):
            sinks = writer()
            if isinstance(sinks, tuple) and len(sinks) == 2:
                return sinks

        def _echo(text: str) -> None:
            print(text, file=sys.stderr, flush=True)

        def _out(text: str) -> None:
            sys.stdout.write(text)
            sys.stdout.flush()

        return _echo, _out

    def _resolve_shell_program(self) -> str | None:
        """Resolve ``[shell] program`` from config (None → platform default)."""
        return self._resolve_shell_setting("program")

    def _resolve_sudo_password(self) -> Any:
        """Resolve ``[shell] sudo_password`` as a ``Secret`` (§B.4/§B.6).

        Wrapped so it masks in any echo and is redacted from command displays;
        None when unset (``sh.sudo`` then requires an explicit ``password=``).
        """
        value = self._resolve_shell_setting("sudo_password")
        if value is None:
            return None
        from functualize._types.redaction import Secret

        return Secret(value)

    @staticmethod
    def _secrets_of(model: Any) -> frozenset[str]:
        """The secret strings carried by an already-resolved config model.

        Feeds ``WiredStdout`` so a secret cannot leak through the explicit data
        channel any more than through a command echo (schema §5). Best-effort by
        design: redaction must never be the reason a job fails, so any problem
        yields an empty set rather than raising.

        Takes the model rather than a job name on purpose. This used to resolve
        the config a *second* time, from the job name, with ``cli_values={}`` —
        so a credential passed as ``--credential`` was in the model the job
        received and absent from the set that redacts its output, and
        ``out.write(config.credential)`` printed it in full. The env tier
        masked, which is why every test passed. Only the instance the job is
        actually handed has seen every precedence tier, so only it can answer
        this. Resolving twice also duplicated any ``RemoteSource`` fetch and
        could redact a rotated-away value.
        """
        from functualize._types.redaction import collect_secret_values, is_secret_field

        if model is None:
            return frozenset()

        fields = getattr(type(model), "model_fields", None)
        if not isinstance(fields, dict):
            return frozenset()

        values: list[Any] = []
        plain: set[str] = set()
        for name, info in fields.items():
            try:
                value = getattr(model, name)
            except Exception:
                continue
            values.append(value)
            # `collect_secret_values` only sees real `Secret` instances. A field
            # marked with `json_schema_extra={"secret": True}` stays a plain
            # `str`, so without this branch the marker would mask the field in
            # `info --job` while its value flowed through `out.emit()` intact —
            # the declaration/value split this work exists to close. One
            # detector, both markers.
            if is_secret_field(info) and isinstance(value, str) and value:
                plain.add(value)
        return frozenset(collect_secret_values(values) | plain)

    def _arm_output_redaction(self, context: ExecutionContext, model: Any) -> None:
        """Tell this run's ``Stdout`` which strings to mask.

        Called once the config model the job will receive exists. DI wiring runs
        first — a capability has to be built before the job's arguments are
        resolved — so the capability starts with an empty set and is armed here
        rather than at construction.
        """
        from functualize._engine.capabilities.stdout import WiredStdout

        secrets = self._secrets_of(model)
        if not secrets:
            return
        for cap in (context.capabilities or {}).values():
            if isinstance(cap, WiredStdout):
                cap.add_secrets(secrets)

    def _resolve_shell_setting(self, key: str) -> str | None:
        """Resolve a non-empty string from the ``[shell]`` config section."""
        if self._resolution_chain is None:
            return None
        try:
            resolved = self._resolution_chain.resolve(key, "shell")
        except Exception:
            return None
        value = getattr(resolved, "value", None)
        return value if isinstance(value, str) and value.strip() else None

    @property
    def job_graph(self) -> Any:
        """The dependency graph, built and validated on first use."""
        if self._job_graph is None:
            from functualize._engine.job_graph import JobGraph

            self._job_graph = JobGraph(self._registered_jobs)
        return self._job_graph

    def _declared_dep_names(self, job_name: str) -> list[str]:
        """Direct dependencies of ``job_name`` — `Deps` and `FromJob` alike."""
        names: list[str] = self.job_graph.deps_of(job_name)
        return names

    def _unreusable_upstreams(self, function: Any) -> set[str]:
        """Upstreams a `FromJob` needs whose recorded value cannot be reused.

        Those must actually run: the dependent asked for a value, and the only
        copy of it is the one the body produces. Freshness cannot stand in —
        it certifies files, and this value was never storable.

        `run=False` is excluded by construction: it means "read what is
        recorded, cause no work", so a missing value is the answer it asked
        for rather than a reason to run anything.
        """
        from functualize._types.from_job import from_job_refs

        store = self._state_store()
        if store is None:
            return set()

        needed: set[str] = set()
        for ref in from_job_refs(function).values():
            if not ref.run:
                continue
            for method in ("checksum", "timestamp", "none"):
                record = store.get_fingerprint(
                    self.fingerprint_key_for(ref.name, method)
                )
                if record is None:
                    continue
                if record.get("return_value_reusable") is False:
                    needed.add(ref.name)
                break
        return needed

    def _scope_step_succeeded(self, scope_id: str, node: str) -> bool:
        """True when ``node`` already completed successfully in this scope.

        Reads the walk's step records — the same ones the walker replays from
        — so "already ran here" has one answer rather than one per consumer.
        """
        store = self._state_store()
        if store is None:
            return False
        scope = store.get_scope(scope_id)
        for key, record in ((scope or {}).get("steps") or {}).items():
            if key.split("::", 1)[0] == node and isinstance(record, dict):
                return bool(record.get("status") == "success")
        return False

    def _run_dependencies(
        self,
        job_name: str,
        function: Any,
        context: Any,
        invoke_depth: int,
        workflow_scope_id: str | None = None,
    ) -> JobResult | None:
        """Run ``job_name``'s dependency graph; None when all succeeded.

        Returns a FAILURE result when a dep failed, so the dependent never
        runs against a half-built world — the whole point of declaring the
        edge.
        """
        # Ask the resolved dependency list, not `Deps` specifically: a job
        # whose only edge comes from a `FromJob` parameter has no `Deps` at
        # all, and asking the wrong question skipped its upstream entirely.
        if not self._declared_dep_names(job_name):
            return None

        from functualize._engine.scheduler import DepScheduler

        order = self.job_graph.order_for(job_name)
        if not order:
            return None
        graph = {node: self.job_graph.deps_of(node) for node in order}

        declaration = getattr(function, "__functualize_job__", None)
        deps = getattr(declaration, "deps", None) if declaration else None
        from functualize._types.from_job import from_job_names

        unreusable_upstreams = self._unreusable_upstreams(function)
        from_job_upstreams = set(from_job_names(function))
        live_values: dict[str, Any] = {}

        def run_node(node: str) -> Any:
            # Inside a walk, a dependency that is *also* a graph node has
            # already run under its node identity — boot validation requires
            # the graph to order it first (Part I cell D×W). Its step record
            # satisfies the edge, so re-running it would execute the same node
            # twice per scope: once as a dependency and once as a node. A
            # non-idempotent job corrupted its own output that way, and every
            # resume repeated it, because this pass consulted no records at
            # all.
            if workflow_scope_id is not None and self._scope_step_succeeded(
                workflow_scope_id, node
            ):
                return True

            # `get_job`, not a raw registry read: on a warm boot the entry's
            # function is a deferred-import stand-in, and only materializing
            # yields something runnable. Reading the entry directly worked
            # cold and failed warm with "dependencies failed".
            entry = self.get_job(node)
            result = self.execute(
                node,
                entry.function,
                kwargs={},
                invoke_depth=invoke_depth + 1,
                config_class=entry.config_class,
                # The plan already contains this node's own dependencies, in
                # order. Letting it schedule them again would run a shared
                # upstream once per path into it — a diamond ran its base
                # three times before this.
                run_dependencies=False,
                # A `FromJob` dependent needs this job's *value*, and the
                # recorded one cannot be reused, so freshness must not stand
                # in for it (resolved Q19, T32b).
                force_fresh=node in unreusable_upstreams,
            )
            # Keep the value of any upstream that just ran for this job's
            # `FromJob` parameters. Injection otherwise reads the fingerprint
            # record, which only exists when the upstream declared
            # `cache=Fingerprint(...)` — so a plain `@job` upstream ran, and
            # the consumer silently received its parameter default. That made
            # `FromJob` quietly depend on an unrelated declaration.
            #
            # A forced run is the same case sharpened: it ran precisely
            # because its value could not be read back, so the copy in hand is
            # the only one.
            if node in from_job_upstreams and result.status is RunStatus.SUCCESS:
                live_values[node] = result.return_value

            # A dep that was skipped as fresh has satisfied the edge; only a
            # real failure blocks the dependent.
            return result.status in (RunStatus.SUCCESS, RunStatus.SKIPPED)

        report = DepScheduler(graph, policy=getattr(deps, "policy", "fail-fast")).run(
            run_node
        )

        if live_values:
            context.metadata["_from_job_live"] = live_values
        context.metadata["dependencies"] = {
            "ran": report.succeeded,
            "failed": report.failed,
            "skipped": report.skipped,
        }
        if report.ok:
            return None

        duration_ms = context.elapsed_ms
        return JobResult(
            status=RunStatus.FAILURE,
            return_value=None,
            duration_ms=duration_ms,
            metadata=dict(context.metadata),
            exception=RuntimeError(
                f"dependencies failed for {job_name!r}: {', '.join(report.failed)}"
            ),
            job_name=job_name,
        )

    def _exec_policy(self) -> Any:
        """The `Exec` policy (timeout/retry/run), built once per engine.

        One instance because run-mode dedup is session state: a fresh policy
        per invocation would make ``Exec(run="once")`` run once *per call*.
        """
        if self._exec_policy_impl is None:
            from functualize._engine.exec_policy import ExecPolicy

            self._exec_policy_impl = ExecPolicy()
        return self._exec_policy_impl

    def _run_mode_skip(self, job_name: str, function: Any, context: Any) -> bool:
        """True when `Exec.run` says this invocation is a duplicate."""
        exec_decl = getattr(
            getattr(function, "__functualize_job__", None), "exec", None
        )
        mode = getattr(exec_decl, "run", "always") if exec_decl else "always"
        if mode == "always":
            return False

        args_hash = self._args_hash_for(context)
        cache = self._exec_policy().run_modes
        if cache.seen(job_name, mode, args_hash):
            return True
        cache.remember(job_name, mode, args_hash)
        return False

    def _inject_from_job(
        self, job_name: str, function: Any, context: Any, scope_id: str | None
    ) -> None:
        """Fill each ``FromJob`` parameter with the upstream's value (§D.5).

        Two ways to satisfy one meaning — "give me that job's result":

        * **Inside a workflow scope**, read the walk's recorded step result.
          The graph already ordered the upstream and the walk already ran it;
          running it again here would execute it outside the scope and defeat
          the memoization. Boot validation guarantees the node is an ancestor,
          so a missing record means the walk genuinely has not reached it.
        * **Outside**, read the fingerprint record. The dependency pass above
          has already ensured the upstream ran or was fresh, so by this point
          a value exists unless the upstream declared no `Fingerprint` (there
          is nowhere to record one) or its return was not serializable.

        An explicitly-passed argument always wins: a caller naming the value
        is not overridden by a cached one.
        """
        from functualize._types.from_job import from_job_refs, from_job_types

        refs = from_job_refs(function)
        if not refs:
            return

        # The declared `T` in `Annotated[T, FromJob(...)]`. The writer stored
        # JSON-compatible data without a reliable type; the consumer's
        # annotation is what rebuilds `Report` rather than `{"rows": 42}`.
        wanted = from_job_types(function)

        live = context.metadata.get("_from_job_live") or {}

        for param, ref in refs.items():
            if param in context.call_kwargs:
                continue  # caller supplied it
            if ref.name in live:
                context.call_kwargs[param] = live[ref.name]
                context.injected.add(param)
                continue
            value = self._from_job_value(ref, scope_id, wanted.get(param))
            if value is not None:
                context.call_kwargs[param] = value
                context.injected.add(param)

    def _live_step_value(self, scope_id: str, step: str) -> Any:
        """The in-process value for ``step`` in this walk, if it is still held.

        Only reached when the recorded value could not be carried, so this is
        the tail: a step returning a live handle. Returns None when the walk
        is not this process's — a resumed scope has records but no memory, and
        None is the honest answer there.
        """
        live = self._live_step_values.get(scope_id) or {}
        return live.get(step)

    def publish_live_step_value(self, scope_id: str, step: str, value: Any) -> None:
        """Record a step's in-process value for the duration of this walk."""
        self._live_step_values.setdefault(scope_id, {})[step] = value

    def forget_live_step_values(self, scope_id: str) -> None:
        """Drop a finished walk's in-process values."""
        self._live_step_values.pop(scope_id, None)

    def _from_job_value(
        self, ref: Any, scope_id: str | None, expected_type: Any = None
    ) -> Any:
        """The recorded value for one ``FromJob`` reference, or None."""
        store = self._state_store()
        if store is None:
            return None

        from functualize._primitives.fingerprint import reusable_return_value

        if scope_id is not None:
            scope = store.get_scope(scope_id)
            steps = (scope or {}).get("steps", {})
            for key, record in steps.items():
                if key.split("::", 1)[0] == ref.name and isinstance(record, dict):
                    value = reusable_return_value(
                        record, job_name=ref.name, expected_type=expected_type
                    )
                    if value is not None:
                        return value
                    # Resolved 19b: the record exists but its value could not
                    # be carried. Inside a walk, re-running is not the remedy —
                    # the step already ran in this scope, and running it again
                    # would execute outside the walk's ordering and defeat the
                    # memoization the walk exists to provide. Fall back to the
                    # live in-process value the walk still holds.
                    #
                    # The order is deliberately record-first. Live-first would
                    # leave the store path exercised only on resume, and a
                    # second path reached only in a rare case is exactly how
                    # the warm-boot divergences happened.
                    return self._live_step_value(scope_id, ref.name)

        for method in ("checksum", "timestamp", "none"):
            record = store.get_fingerprint(self.fingerprint_key_for(ref.name, method))
            if record is not None:
                return reusable_return_value(
                    record, job_name=ref.name, expected_type=expected_type
                )
        return None

    def _preflight(self) -> Any:
        """The guard/fingerprint pipeline, built once per engine."""
        if self._preflight_pipeline is None:
            from functualize._engine.preflight import Preflight

            self._preflight_pipeline = Preflight(self._state_store())
        return self._preflight_pipeline

    def _preflight_check(
        self, job_name: str, function: Any, context: Any
    ) -> Any | None:
        """Evaluate guards and staleness, or None when nothing is declared.

        Returning None for an undeclared job keeps the common case free: a
        plain `@job` pays no state-store read and no guard evaluation.
        """
        declaration = getattr(function, "__functualize_job__", None)
        if declaration is None:
            return None
        if (
            getattr(declaration, "guards", None) is None
            and getattr(declaration, "cache", None) is None
            and getattr(getattr(declaration, "exec", None), "platforms", None) is None
        ):
            return None

        rc = self._run_context_of(context)
        config = getattr(rc, "job_config", None) if rc is not None else None
        decision = self._preflight().check(
            job_name,
            declaration,
            config=config,
            args_hash=self._args_hash_for(context),
        )
        context.metadata["preflight"] = {
            "state": decision.verdict.state.value,
            "reason": decision.verdict.reason,
            "checks": list(decision.verdict.checks),
        }
        return decision

    @staticmethod
    def _bind_preflight_capabilities(context: Any, decision: Any) -> None:
        """Complete every capability whose spec declares a pre-flight bind.

        DI resolves before the pre-flight runs — it must, because the
        pre-flight's args hash reads ``context.injected`` — so a capability
        carrying pre-flight data is injected **empty** and completed here, the
        last point before the body is invoked at which the decision exists.

        Which capabilities those are is read from the registry rather than
        written out here. The old shape was one hard-coded call at one line:
        lose it and the capability resolves, injects, and reports nothing, with
        no error anywhere — the "wired but inert" failure
        ``contributor/guides/wiring-discipline.md`` exists for. A second
        capability of the same shape would have had to remember it again; now
        it declares it and this loop finds it.

        A job that asked for none of them costs nothing here.
        """
        from functualize._engine.capabilities.registry import CAPABILITY_SPECS

        caps = context.capabilities or {}
        if not caps:
            return
        for spec in CAPABILITY_SPECS:
            if spec.preflight_bind is None or spec.type is None:
                continue
            instance = caps.get(spec.type)
            if instance is not None:
                spec.preflight_bind(instance, decision)

    def _preflight_result(
        self, job_name: str, context: Any, decision: Any, start_time: float
    ) -> JobResult:
        """The JobResult for a job the pre-flight pipeline stopped."""
        from functualize._engine.guards import GuardState

        state = decision.verdict.state
        status = {
            # A failing `Precondition` is a refusal, not a failure: nothing
            # ran and nothing raised — the job declined to start because a
            # declared condition for running it was not met. Its own docstring
            # already says "non-zero = refuse"; this is where that becomes an
            # exit code the caller can act on (3, not 1).
            GuardState.ERROR: RunStatus.REFUSED,
            GuardState.REFUSED: RunStatus.REFUSED,
            GuardState.BLOCKED: RunStatus.BLOCKED,
        }.get(state, RunStatus.SKIPPED)

        duration_ms = (time.perf_counter() - start_time) * 1000
        self._event_bus.emit(
            "job.execute.end",
            resource=job_name,
            job_name=job_name,
            duration_ms=duration_ms,
            status=status.value.lower(),
        )
        metadata = dict(context.metadata)
        metadata["skip_reason"] = decision.verdict.reason
        return JobResult(
            status=status,
            return_value=(
                decision.recorded_value if status is RunStatus.SKIPPED else None
            ),
            duration_ms=duration_ms,
            metadata=metadata,
            job_name=job_name,
        )

    @staticmethod
    def _run_context_of(context: Any) -> Any:
        from functualize._engine.capabilities.runcontext import RunContext

        caps = getattr(context, "capabilities", None) or {}
        return caps.get(RunContext)

    def _group_options_params(
        self, function: Callable[..., Any]
    ) -> tuple[tuple[str, Any], ...]:
        """The ``(param_name, class)`` pairs of a function's GroupOptions params.

        Cached by ``id(function)`` like the resolution plan, and for the same
        reason: this runs on every execution, and ``get_type_hints`` on a job
        that declares none is pure overhead. Materialization swaps the entry to
        the real function before any introspection, so the key is stable.
        """
        func_id = id(function)
        cached = self._group_options_cache.get(func_id)
        if cached is not None:
            return cached

        from functualize._primitives.group_options_detection import (
            is_group_options_class,
        )

        sig = inspect.signature(function)
        hints = resolved_hints(function)
        found: list[tuple[str, Any]] = []
        for param_name, param in sig.parameters.items():
            annotation = hints.get(param_name, param.annotation)
            if is_group_options_class(annotation):
                found.append((param_name, annotation))

        result = tuple(found)
        self._group_options_cache[func_id] = result
        return result

    def _resolve_group_options(
        self,
        function: Callable[..., Any],
        context: ExecutionContext,
        cli_values: dict[str, Any] | None,
    ) -> None:
        """Build and inject each declared ``GroupOptions`` parameter (S6a).

        A ``GroupOptions`` subclass carries the flags declared by a *group*,
        not by this job, so it is resolved against the **group path** rather
        than the job name: ``class DeployOptions(GroupOptions, group="deploy")``
        reads the ``[deploy]`` config section and the ``DEPLOY__ENV`` env var.
        Everything else is the job-config ladder unchanged, which is why this
        delegates to the same ``_config_resolver``: default < config file <
        env < group-CLI (D-c — a mid-path flag beats the environment, matching
        how a job's own flag beats it).

        ``cli_values`` is the **flat** merge the dispatcher produced, nearest
        declaration already winning (§5, C-D3). Each class is handed only the
        keys it declares, so a job that injects two ancestor types sees one
        value for a field they share.

        Resolution is unconditional, not gated on ``cli_values``: a job run as
        ``invoke("deploy.web.run")`` has no CLI layer but must still see its
        group's file/env/default values, and must see the same ones the CLI
        run resolves.
        """
        declared = self._group_options_params(function)
        if not declared:
            return

        for param_name, options_class in declared:
            group_path: str = options_class.__group_path__
            field_names = set(options_class.model_fields.keys())
            scoped_values = (
                {k: v for k, v in cli_values.items() if k in field_names}
                if cli_values
                else {}
            )
            # The env key is built from this name by the resolver, so the
            # dotted path is flattened first: `deploy.web` -> `DEPLOY_WEB__ENV`.
            # The *config view* keeps the dotted path, so the file section
            # stays `[deploy.web]`.
            env_scope = group_path.replace(".", "_")
            config_view = self._make_config_view(group_path)

            def _build(
                values: dict[str, Any],
                _cls: type = options_class,
                _scope: str = env_scope,
                _view: Any = config_view,
            ) -> Any:
                if self._config_resolver is not None:
                    return self._config_resolver(
                        config_class=_cls,
                        job_name=_scope,
                        config_view=_view,
                        cli_values=values,
                        group_scope=_scope,
                    )
                return _cls(**values)

            # A required group option resolves through the same ladder as a
            # required job-config field, so it gets the same T45 treatment.
            # Prompting for one and not the other would make "is this field
            # asked for?" depend on which *kind* of field it is — the exact
            # distinction users cannot see and should not have to.
            instance = self._resolve_with_prompt(
                _build,
                options_class,
                env_scope,
                scoped_values,
                group_scope=env_scope,
            )
            context.call_kwargs[param_name] = instance
            context.injected.add(param_name)

    def _resolve_with_prompt(
        self,
        build: Callable[[dict[str, Any]], Any],
        config_class: type,
        section: str,
        values: dict[str, Any],
        *,
        group_scope: str | None = None,
    ) -> Any:
        """Build a config model, asking for what the chain could not supply (T45).

        A required field resolving to nothing is the single most common way a
        run dies, and by this point the chain has already tried defaults, the
        config file, the environment and the CLI — so the only source left is
        the person running it. Ask them, **if** a surface can ask.

        Off an interactive surface the original ``ValidationError`` is
        deliberately re-raised rather than restated as a typed substitute: it
        drives the CLI's field-level panel and the config-source hint, which
        name the files that were really read, the ``config.<slot>.<ext>`` rule
        and ``JOB_<FIELD>``. Substituting it would trade a good diagnostic for
        a worse one on the path users hit most (CI).

        Args:
            build: Resolves the model from a value mapping.
            config_class: The model, read for field metadata (secret, type).
            section: The config section, which is also the env-var scope.
            values: The CLI-supplied values to resolve from.

        Returns:
            The resolved model instance.

        Raises:
            ValidationError: Unrecoverable, or nothing could be asked.
            MissingValueError: The user was asked and entered nothing.
        """
        try:
            return build(values)
        except ValidationError as exc:
            # Only *missing* errors are recoverable by asking: a value that was
            # supplied and failed its constraint is a wrong answer, not an
            # absent one, and re-asking would loop rather than converge. And
            # only fields one typed line can satisfy — asking for a sub-model
            # or a list interrogates the user and *then* shows them the field
            # error they would have got for free.
            fields = getattr(config_class, "model_fields", {})
            missing = tuple(
                name
                for name in _missing_required_fields(exc)
                if _is_promptable(getattr(fields.get(name), "annotation", None))
            )
            prompt = self._resolve_prompt_capability() if missing else None
            if prompt is None:
                raise
            collected = self._prompt_for_missing_config(
                config_class, section, missing, prompt, group_scope=group_scope
            )
            # One retry only. If the answers still do not validate, the second
            # ValidationError propagates and is rendered normally — better a
            # field-level error than an interrogation the user cannot escape.
            return build({**values, **collected})

    def _prompt_for_missing_config(
        self,
        config_class: type,
        job_name: str,
        missing: tuple[str, ...],
        prompt: Any,
        *,
        group_scope: str | None = None,
    ) -> dict[str, Any]:
        """Collect ``missing`` from an interactive surface.

        Shares :mod:`functualize._engine.missing_value` with the sudo-password
        fallback so the two features cannot drift into disagreeing about what
        "non-interactive" means (Merge B). Fields flagged secret are collected
        masked — the same test that decides whether a value is redacted in
        ``state.json`` decides whether it is echoed while being typed.

        Args:
            config_class: The Pydantic config model being resolved.
            job_name: The config section, which is also the env-var scope.
            missing: Field names the chain could not supply.
            prompt: The ``Prompt`` capability. Never ``None`` — the caller has
                already established that a surface can answer, because the
                non-interactive case keeps the original ``ValidationError``.

        Returns:
            The collected values, keyed by field name.

        Raises:
            MissingValueError: When the user was asked and entered nothing.
                Declining is not the same as never being asked, so it keeps its
                own message rather than reusing the validation error.
        """
        from functualize._engine.missing_value import (
            env_var_for,
            group_env_var_for,
            resolve_missing_value,
        )
        from functualize._types.redaction import is_secret_field

        fields = getattr(config_class, "model_fields", {})

        collected: dict[str, Any] = {}
        for name in missing:
            collected[name] = resolve_missing_value(
                prompt,
                field=name,
                env_var=(
                    group_env_var_for(group_scope, name)
                    if group_scope is not None
                    else env_var_for(job_name, name)
                ),
                message=f"{job_name}: {name}",
                secret=is_secret_field(fields.get(name)),
            )
        return collected

    def _resolve_config_model(
        self,
        function: Callable[..., Any],
        context: ExecutionContext,
        config_class: type,
        job_name: str,
    ) -> None:
        """Resolve a Pydantic config model and inject into context.

        Uses the resolution chain and CLI values from call_kwargs to resolve
        the config model. The resolved model is injected into:
        1. The RunContext's job_config property
        2. The call_kwargs for the config model parameter

        Args:
            function: The job function (to find config param name).
            context: The execution context.
            config_class: The Pydantic model class.
            job_name: The job name for config section prefix.
        """
        from pydantic import BaseModel

        # Get the RunContext from capabilities to set job_config on it
        from functualize._engine.capabilities.runcontext import RunContext

        rc = context.capabilities.get(RunContext) if context.capabilities else None

        # Build a config view using the injected factory
        config_view = self._make_config_view(job_name)

        # Extract CLI values from call_kwargs that match config fields
        cli_values: dict[str, Any] = {}
        config_field_names = set(
            cast("type[BaseModel]", config_class).model_fields.keys()
        )
        for field_name in config_field_names:
            if field_name in context.call_kwargs:
                cli_values[field_name] = context.call_kwargs.pop(field_name)

        # Resolve the config model via injected resolver, asking for anything
        # the whole ladder came up empty on (T45 — see `_resolve_with_prompt`,
        # shared with the group-options path so the two cannot drift).
        def _resolve(values: dict[str, Any]) -> Any:
            if self._config_resolver is not None:
                return self._config_resolver(
                    config_class=config_class,
                    job_name=job_name,
                    config_view=config_view,
                    cli_values=values,
                )
            return config_class(**values)

        config_instance = self._resolve_with_prompt(
            _resolve, config_class, job_name, cli_values
        )

        # Set on RunContext's job_config
        if rc is not None:
            rc.job_config = config_instance

        # This instance has seen every precedence tier, the command line
        # included; nothing earlier has. Arm output redaction from it.
        self._arm_output_redaction(context, config_instance)

        # Find the config parameter name in the function signature and inject.
        #
        # Annotations are resolved rather than read raw. Under
        # `from __future__ import annotations` (PEP 563) every annotation is a
        # string, so `isinstance(annotation, type)` below matches nothing, no
        # parameter is injected, and the job dies at call time with a
        # "missing 1 required positional argument" that names the config
        # parameter but says nothing about config. Discovery already resolves
        # hints for this exact reason; this path had been left raw.
        sig = inspect.signature(function)
        # Empty when a hint cannot be resolved (a TYPE_CHECKING-only import);
        # the loop then falls back to the raw annotation rather than failing.
        hints = resolved_hints(function)

        for param_name, param in sig.parameters.items():
            annotation = hints.get(param_name, param.annotation)
            if (
                isinstance(annotation, type)
                and issubclass(annotation, BaseModel)
                and annotation is not BaseModel
                and issubclass(annotation, config_class)
            ):
                context.call_kwargs[param_name] = config_instance
                context.injected.add(param_name)
                break

    def _execute_with_lifecycle(self, context: ExecutionContext) -> JobResult:
        """Execute a job with hooks, middleware, and instrumentation.

        Catches all exceptions to ensure hooks always fire and a
        JobResult is always returned.

        Args:
            context: The fully-resolved execution context.

        Returns:
            JobResult with status, duration, return value, exception info.
        """
        job_name = context.job_name
        function = context.function
        call_kwargs = context.call_kwargs

        # Fire PRE_EXECUTE hooks — may block execution
        decision = self._hook_registry.invoke_pre_execute(
            job_name, context, context.call_kwargs
        )
        if decision is not None and decision.action == "block":
            duration_ms = context.elapsed_ms
            self._hook_registry.invoke(HookEvent.ON_TEARDOWN, job_name, context)
            self._event_bus.emit(
                "job.execute.end",
                resource=job_name,
                job_name=job_name,
                duration_ms=duration_ms,
                status="failure",
            )
            return JobResult(
                status=RunStatus.FAILURE,
                return_value=None,
                duration_ms=duration_ms,
                metadata={**dict(context.metadata), "blocked_reason": decision.reason},
                job_name=job_name,
            )

        # Handle MODIFY decision - replace kwargs
        if (
            decision is not None
            and decision.action == "modify"
            and decision.kwargs is not None
        ):
            context.call_kwargs = decision.kwargs
            call_kwargs = decision.kwargs

        # Fire before_job hook (pass RunContext from capabilities)
        from functualize._engine.capabilities.runcontext import (
            RunContext as _RunContext,
        )

        _rc_for_hooks = (
            context.capabilities.get(_RunContext, context)
            if context.capabilities
            else context
        )
        self._hook_registry.invoke(HookEvent.BEFORE_JOB, job_name, _rc_for_hooks)

        result_value: Any = None
        exception: BaseException | None = None

        def _execute_job() -> Any:
            return function(**call_kwargs)

        try:
            if self._middleware_chain.has_middleware:
                result_value = self._middleware_chain.execute(
                    context,
                    _execute_job,
                    di_registry=self._di_registry,
                    resolution_plan_cache=self._resolution_plan_cache,
                )
            else:
                result_value = _execute_job()
        except BaseException as exc:
            exception = exc
            self._hook_registry.invoke(
                HookEvent.AFTER_FAILURE, job_name, _rc_for_hooks, exception=exc
            )
        else:
            self._hook_registry.invoke(
                HookEvent.AFTER_SUCCESS, job_name, _rc_for_hooks, result=result_value
            )

        # Always fire teardown
        self._event_bus.emit(
            "job.teardown.start",
            resource=job_name,
            job_name=job_name,
        )
        self._hook_registry.invoke(HookEvent.ON_TEARDOWN, job_name, _rc_for_hooks)
        teardown_duration = context.elapsed_ms
        self._event_bus.emit(
            "job.teardown.end",
            resource=job_name,
            job_name=job_name,
            duration_ms=teardown_duration,
        )

        # Emit completion event
        duration_ms = context.elapsed_ms
        self._event_bus.emit(
            "job.execute.end",
            resource=job_name,
            job_name=job_name,
            duration_ms=duration_ms,
            status="failure" if exception else "success",
        )

        # Merge RunContext metadata into result metadata
        result_metadata = dict(context.metadata)
        if hasattr(_rc_for_hooks, "_result_metadata"):
            result_metadata.update(_rc_for_hooks._result_metadata)
        if hasattr(_rc_for_hooks, "_metadata"):
            # Only merge non-framework keys from RunContext's _metadata
            for k, v in _rc_for_hooks._metadata.items():
                if k not in result_metadata:
                    result_metadata[k] = v

        if exception is not None:
            return JobResult(
                status=RunStatus.FAILURE,
                return_value=None,
                duration_ms=duration_ms,
                metadata=result_metadata,
                exception=exception,
                job_name=job_name,
            )

        return JobResult(
            status=RunStatus.SUCCESS,
            return_value=result_value,
            duration_ms=duration_ms,
            metadata=result_metadata,
            job_name=job_name,
        )
