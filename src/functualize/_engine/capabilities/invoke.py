"""Invoke capability — job-to-job invocation interface.

Defines the Invoke class (stub) and WiredInvoke (engine-connected).
The actual implementation is backed by the execution engine and wired
at runtime. This module provides the type contract.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import BaseModel

    from functualize._engine.executor import JobExecutionEngine
    from functualize._gate._registry import GateRegistry
    from functualize._gate._strategy import GateStrategy
    from functualize._types.descriptors import JobDescriptor, JobResult
    from functualize.job._workflow_scope import WorkflowScope

logger = logging.getLogger(__name__)


class ParallelObserver(Protocol):
    """Notified on the worker thread as each parallel job starts and ends.

    The binding between a thread and the job running on it exists only inside
    ``parallel``'s executor, and it is what per-job output attribution needs —
    so it is handed out here rather than reconstructed (it cannot be).
    """

    def claim(self, job_name: str) -> None:
        """Called on the worker thread before the job runs."""
        ...

    def release(self, job_name: str, *, failed: bool) -> None:
        """Called on the same thread once it has, however it ended."""
        ...


DEFAULT_PARALLEL_TIMEOUT: float = 300.0
"""Seconds a batch of parallel jobs may run before the unfinished ones are
reported as :attr:`RunStatus.TIMEOUT` (T40).

Five minutes was hardcoded inside ``WiredInvoke.parallel``; it is a named
constant now because ``func builtin parallel --timeout`` has to be able to
override it and because a caller cannot reason about a number it cannot see.
"""


@dataclass(frozen=True)
class InvokeResult:
    """Lightweight result type for job invocations via the Invoke capability.

    This is used as the return type when the full JobResult from
    functualize._engine.result is not available (e.g., in testing contexts).
    The actual Invoke implementation returns functualize._engine.result.JobResult.
    """

    success: bool
    return_value: Any = None
    exception: BaseException | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Invoke:
    """Job-to-job invocation capability.

    Allows a job to invoke other jobs by name or function reference,
    run jobs in parallel, or introspect job schemas. The actual execution
    is delegated to the engine — this class raises NotImplementedError
    until wired.

    The engine replaces this stub with a fully-wired instance at runtime.
    """

    def __call__(
        self,
        job_or_fn: str | Callable[..., Any],
        *,
        config: BaseModel | None = None,
        awaits_input: type[BaseModel] | None = None,
        available_tools: list[str] | None = None,
        force_gate: bool = False,
        gate_strategy: GateStrategy | str | list[GateStrategy | str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> JobResult:
        """Invoke a job by name or function reference.

        Args:
            job_or_fn: Job name string or registered callable.
            config: Typed config (mutually exclusive with **kwargs).
            awaits_input: BaseModel subclass describing input the job needs;
                its JSON schema is attached to the result metadata for the
                caller (and drives gate resolution when gate params are set).
            available_tools: Restrict tool visibility at the gate (max 64).
            force_gate: Dispatch gate strategy even when fully resolved.
            gate_strategy: Override configured gate strategy for this invocation.
            timeout: Optional timeout in seconds.
            **kwargs: Arguments to pass to the job.

        Returns:
            A JobResult with status, return_value, exception, metadata.

        Raises:
            JobNotFoundError: If callable is not registered.
            ValueError: If both config and kwargs are provided.
            ValueError: If available_tools contains unregistered tool names.
            ValueError: If available_tools has more than 64 entries.
        """

        # --- Resolve job_or_fn ---
        self._resolve_job_name(job_or_fn)

        # --- Config-kwargs mutual exclusivity check ---
        if config is not None and kwargs:
            raise ValueError(
                "Cannot pass both 'config' and keyword arguments to invoke(). "
                "Use one or the other."
            )

        # --- Extract config fields as kwargs if config provided ---
        if config is not None:
            kwargs = config.model_dump()

        # --- Validate available_tools ---
        if available_tools is not None:
            if len(available_tools) > 64:
                raise ValueError(
                    f"available_tools must have at most 64 entries, "
                    f"got {len(available_tools)}"
                )
            self._validate_tool_names(available_tools)

        raise NotImplementedError(
            "Invoke capability is not wired. "
            "This instance must be replaced by the engine at runtime."
        )

    def parallel(
        self,
        jobs: Sequence[tuple[str | Callable[..., Any], dict[str, Any]]],
        *,
        timeout: float | None = None,
    ) -> list[JobResult]:
        """Invoke 1-32 jobs concurrently, returning results in input order.

        Args:
            jobs: List of (job_or_fn, kwargs) tuples to execute concurrently.
            timeout: Seconds the batch may run before unfinished jobs are
                reported as timed out. ``None`` uses
                :data:`DEFAULT_PARALLEL_TIMEOUT`; ``<= 0`` waits indefinitely.

        Returns:
            List of JobResult objects in the same order as input.

        Raises:
            ValueError: If more than 32 jobs are specified.
        """
        if len(jobs) > 32:
            raise ValueError(
                f"Invoke.parallel accepts at most 32 jobs, got {len(jobs)}"
            )

        raise NotImplementedError(
            "Invoke.parallel is not wired. "
            "This instance must be replaced by the engine at runtime."
        )

    def schema(self, job_or_fn: str | Callable[..., Any]) -> JobDescriptor:
        """Retrieve the JobDescriptor for a job by name or function reference.

        Args:
            job_or_fn: Job name string or registered callable.

        Returns:
            A JobDescriptor for the referenced job.

        Raises:
            JobNotFoundError: If the callable/name is not registered.
        """
        raise NotImplementedError(
            "Invoke.schema is not wired. "
            "This instance must be replaced by the engine at runtime."
        )

    def _resolve_job_name(self, job_or_fn: str | Callable[..., Any]) -> str:
        """Resolve a job_or_fn argument to a job name string.

        If job_or_fn is a string, returns it directly.
        If job_or_fn is a callable, looks it up in the job registry's
        function-to-name mapping and returns the registered name.

        Args:
            job_or_fn: Job name string or registered callable.

        Returns:
            The resolved job name string.

        Raises:
            JobNotFoundError: If callable is not found in the registry.
        """
        from functualize._engine.errors import JobNotFoundError

        if isinstance(job_or_fn, str):
            return job_or_fn

        if callable(job_or_fn):
            # Look up the callable in the job registry's function-to-name map.
            # The stub implementation has no registry reference, so this will
            # raise JobNotFoundError. The wired engine implementation overrides
            # this behavior.
            raise JobNotFoundError(job_or_fn)

        raise TypeError(
            f"job_or_fn must be a str or callable, got {type(job_or_fn).__name__}"
        )

    def _validate_tool_names(self, tool_names: list[str]) -> None:
        """Validate that all tool names in the list are registered.

        The stub implementation has no tool registry reference, so this
        is a no-op. The wired engine implementation performs actual
        validation against the registered tool set.

        Args:
            tool_names: List of tool names to validate.

        Raises:
            ValueError: If any tool name is not registered.
        """
        # No-op in stub — the wired engine performs actual validation.
        pass


class WiredInvoke(Invoke):
    """Engine-connected Invoke capability with full execution wiring.

    Connects function-ref resolution to the job registry, wires gate
    parameters through to the gate resolution system, propagates
    invoke_depth and scope_id, and attaches awaits_input schema metadata
    to the result.

    This class is instantiated per-invocation by the execution engine's
    DI resolution and replaces the stub Invoke.

    Args:
        execution_engine: The JobExecutionEngine for job lookup and execution.
        gate_registry: The GateRegistry for gate resolution dispatch.
        invoke_depth: Current recursion depth of the parent context.
        max_invoke_depth: Maximum allowed recursion depth.
        workflow_scope: The WorkflowScope to propagate to child executions.
        cwd: Working directory propagated to child executions.
    """

    def __init__(
        self,
        execution_engine: JobExecutionEngine,
        gate_registry: GateRegistry | None = None,
        invoke_depth: int = 0,
        max_invoke_depth: int = 10,
        workflow_scope: WorkflowScope | None = None,
        cwd: Path | None = None,
        run_context: Any | None = None,
    ) -> None:
        self._engine = execution_engine
        self._gate_registry = gate_registry
        self._invoke_depth = invoke_depth
        self._max_invoke_depth = max_invoke_depth
        self._workflow_scope = workflow_scope
        self._cwd = cwd
        self._rc = run_context

    def __call__(
        self,
        job_or_fn: str | Callable[..., Any],
        *,
        config: BaseModel | None = None,
        awaits_input: type[BaseModel] | None = None,
        available_tools: list[str] | None = None,
        force_gate: bool = False,
        gate_strategy: GateStrategy | str | list[GateStrategy | str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> JobResult:
        """Invoke a job by name or function reference (engine-wired).

        Performs full validation, function-ref resolution via job registry,
        gate dispatch, depth tracking, and scope propagation before
        delegating execution to the engine. When ``awaits_input`` is set,
        the model's JSON schema is attached to the result metadata.
        """
        from functualize._events.hooks import HookEvent
        from functualize._types.descriptors import JobResult as _JobResult
        from functualize._types.enums import RunStatus
        from functualize._types.errors import RecursionLimitError

        # --- Resolve job_or_fn ---
        job_name = self._resolve_job_name(job_or_fn)

        # --- Config-kwargs mutual exclusivity check ---
        if config is not None and kwargs:
            raise ValueError(
                "Cannot pass both 'config' and keyword arguments to invoke(). "
                "Use one or the other."
            )

        # --- Extract config fields as kwargs if config provided ---
        if config is not None:
            kwargs = config.model_dump()

        # --- Validate available_tools ---
        if available_tools is not None:
            if len(available_tools) > 64:
                raise ValueError(
                    f"available_tools must have at most 64 entries, "
                    f"got {len(available_tools)}"
                )
            self._validate_tool_names(available_tools)

        # --- Validate timeout ---
        if timeout is not None and timeout < 0.1:
            raise ValueError(f"Timeout must be at least 0.1 seconds, got {timeout}")

        # --- Check invoke_depth against max_invoke_depth ---
        if self._invoke_depth >= self._max_invoke_depth:
            raise RecursionLimitError(
                self._invoke_depth, self._max_invoke_depth, job_name
            )

        # --- Look up registered job ---
        registered_job = self._engine.get_job(job_name)
        # From here the resolved name is the one of record. `job_name` is
        # whatever the caller typed; hooks, gate context and the state store
        # all describe the job that *ran*, and an observer cannot correlate
        # `child_job` with a scope keyed `child-job`.
        job_name = registered_job.name
        child_depth = self._invoke_depth + 1

        # --- Gate dispatch: if force_gate or gate_strategy specified ---
        if (
            (force_gate or gate_strategy is not None)
            and self._gate_registry is not None
            and awaits_input is not None
        ):
            # Use awaits_input as the model class for gate resolution
            try:
                resolved = self._gate_registry.resolve_gate(
                    awaits_input,
                    force_gate=force_gate,
                    gate_strategy=gate_strategy,
                    resolved_fields=kwargs if kwargs else None,
                    workflow_context={
                        "job_name": job_name,
                        "invoke_depth": child_depth,
                        "scope_id": (
                            self._workflow_scope.scope_id
                            if self._workflow_scope
                            else None
                        ),
                    },
                    gate_name=job_name,
                )
            except Exception:
                # Gate resolution errors propagate to caller
                raise

            # Use what the gate resolved. This was discarded: the call ran
            # purely for its side effects and the child job then executed with
            # the *original* kwargs, so a gate that successfully collected
            # input threw the answer away and the job never saw it. An
            # explicitly-passed argument still wins — a caller naming a value
            # is not overridden by a gate that filled the same field.
            if resolved is not None:
                for field, value in resolved.model_dump().items():
                    kwargs.setdefault(field, value)

        # --- Fire INVOKE_START hook ---
        hook_registry = self._engine._hook_registry
        hooks = hook_registry._global_hooks.get(HookEvent.INVOKE_START, [])
        for hook in hooks:
            try:
                hook(self._rc, job_name, kwargs, child_depth)
            except Exception as e:
                logger.error(f"INVOKE_START hook raised: {e}")

        # --- Execute child job via engine ---
        parent_scope = self._workflow_scope

        def _do_execute() -> JobResult:
            return self._engine.execute(
                job_name=job_name,
                function=registered_job.function,
                config_class=registered_job.config_class,
                kwargs=kwargs,
                parent_scope=parent_scope,
                invoke_depth=child_depth,
                cwd=self._cwd,
                job_directory=registered_job.job_directory,
            )

        if timeout is not None:
            result = self._execute_with_timeout(_do_execute, job_name, timeout)
        else:
            result = _do_execute()

        # --- Handle awaits_input metadata ---
        if awaits_input is not None:
            schema_info = awaits_input.model_json_schema()
            result = _JobResult(
                status=result.status,
                return_value=result.return_value,
                duration_ms=result.duration_ms,
                metadata={
                    **result.metadata,
                    "_awaits_input": True,
                    "_input_schema": schema_info,
                    "_available_tools": available_tools,
                },
                exception=result.exception,
                job_name=result.job_name,
            )

        # --- Fire INVOKE_FAILURE hook ---
        # A refusal is a way for a child invoke to not have done its work, so
        # the hook that exists to notice that must see it. `== FAILURE` let a
        # refused child pass by silently.
        if result.status in (RunStatus.FAILURE, RunStatus.REFUSED):
            failure_hooks = hook_registry._global_hooks.get(
                HookEvent.INVOKE_FAILURE, []
            )
            for hook in failure_hooks:
                try:
                    hook(self._rc, job_name, child_depth, result)
                except Exception as e:
                    logger.error(f"INVOKE_FAILURE hook raised: {e}")

        # --- Fire INVOKE_END hook ---
        end_hooks = hook_registry._global_hooks.get(HookEvent.INVOKE_END, [])
        for hook in end_hooks:
            try:
                hook(self._rc, job_name, child_depth, result)
            except Exception as e:
                logger.error(f"INVOKE_END hook raised: {e}")

        # Re-raise BaseException subclasses that are not regular Exceptions
        if (
            result.exception is not None
            and isinstance(result.exception, BaseException)
            and not isinstance(result.exception, Exception)
        ):
            raise result.exception

        return result

    def parallel(
        self,
        jobs: Sequence[tuple[str | Callable[..., Any], dict[str, Any]]],
        *,
        timeout: float | None = None,
        observer: ParallelObserver | None = None,
    ) -> list[JobResult]:
        """Invoke 1-32 jobs concurrently, returning results in input order.

        Resolves function references to job names and executes each job
        with independent context via the engine.

        Args:
            jobs: ``(job_or_fn, kwargs)`` pairs, at most 32.
            timeout: Seconds the batch may run before unfinished jobs are
                reported as :attr:`RunStatus.TIMEOUT`. ``None`` uses
                :data:`DEFAULT_PARALLEL_TIMEOUT`; ``<= 0`` waits indefinitely.
            observer: Notified **on the worker thread**, around each job. Only
                this method knows which thread is running which job, and that
                binding is the whole basis of per-job output attribution
                (``func builtin parallel --output grouped|prefixed``); a caller
                cannot reconstruct it from the returned results.

        Returns:
            One JobResult per input, in input order.
        """
        from functualize._types.descriptors import JobResult as _JobResult
        from functualize._types.enums import RunStatus
        from functualize._types.errors import RecursionLimitError

        if len(jobs) == 0:
            return []

        if len(jobs) > 32:
            raise ValueError(
                f"Invoke.parallel accepts at most 32 jobs, got {len(jobs)}"
            )

        child_depth = self._invoke_depth + 1
        budget = DEFAULT_PARALLEL_TIMEOUT if timeout is None else timeout

        def _execute_single(
            index: int, job_or_fn: str | Callable[..., Any], kwargs: dict[str, Any]
        ) -> tuple[int, JobResult]:
            """Execute a single job in its own thread."""
            # Resolve job name
            try:
                job_name = self._resolve_job_name(job_or_fn)
            except Exception as e:
                return (
                    index,
                    _JobResult(
                        status=RunStatus.FAILURE,
                        duration_ms=0.0,
                        return_value=None,
                        exception=e,
                        job_name=str(job_or_fn),
                    ),
                )

            # From here on the job has a name, so its output can be attributed.
            # Wrapped in try/finally rather than paired by hand: every remaining
            # return path below is an *error* path, and an observer left holding
            # a claimed thread would swallow that job's output entirely — the
            # one case where seeing the output matters most.
            if observer is not None:
                observer.claim(job_name)
            outcome: tuple[int, JobResult] | None = None
            try:
                outcome = _run(index, job_or_fn, job_name, kwargs)
                return outcome
            finally:
                if observer is not None:
                    observer.release(job_name, failed=_is_failure(outcome))

        def _is_failure(outcome: tuple[int, JobResult] | None) -> bool:
            """Whether a finished job counts as failed, for the *reader*.

            `None` means `_run` raised, which nothing below is supposed to do —
            treated as failure so an unexpected escape is still surfaced rather
            than quietly logged as a clean run. BLOCKED and SKIPPED are not
            failures: the job did what it was asked to (`RunStatus.resumable`
            exists for exactly this distinction) and marking them `::error::`
            in a CI log would cry wolf.
            """
            if outcome is None:
                return True
            status = outcome[1].status
            return status not in (
                RunStatus.SUCCESS,
                RunStatus.SKIPPED,
                RunStatus.BLOCKED,
            )

        def _run(
            index: int,
            job_or_fn: str | Callable[..., Any],
            job_name: str,
            kwargs: dict[str, Any],
        ) -> tuple[int, JobResult]:
            """The body of one parallel job, once its name is known."""

            # Check recursion limit
            if child_depth > self._max_invoke_depth:
                return (
                    index,
                    _JobResult(
                        status=RunStatus.FAILURE,
                        duration_ms=0.0,
                        return_value=None,
                        exception=RecursionLimitError(
                            child_depth, self._max_invoke_depth, job_name
                        ),
                        job_name=job_name,
                    ),
                )

            try:
                registered_job = self._engine.get_job(job_name)
            except Exception as e:
                return (
                    index,
                    _JobResult(
                        status=RunStatus.FAILURE,
                        duration_ms=0.0,
                        return_value=None,
                        exception=e,
                        job_name=job_name,
                    ),
                )

            try:
                result = self._engine.execute(
                    job_name=job_name,
                    function=registered_job.function,
                    config_class=registered_job.config_class,
                    kwargs=kwargs,
                    parent_scope=None,  # Independent — no shared scope
                    invoke_depth=child_depth,
                    cwd=self._cwd,
                    job_directory=registered_job.job_directory,
                )
                return (index, result)
            except Exception as e:
                return (
                    index,
                    _JobResult(
                        status=RunStatus.FAILURE,
                        duration_ms=0.0,
                        return_value=None,
                        exception=e,
                        job_name=job_name,
                    ),
                )

        results: list[tuple[int, JobResult]] = []
        seen: set[int] = set()

        def _collect(idx: int, job_or_fn: Any, future: Any) -> None:
            """Record a finished future's outcome under ``idx``."""
            seen.add(idx)
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    (
                        idx,
                        _JobResult(
                            status=RunStatus.FAILURE,
                            duration_ms=0.0,
                            return_value=None,
                            exception=exc,
                            job_name=str(job_or_fn),
                        ),
                    )
                )

        # Not a `with` block: `ThreadPoolExecutor.__exit__` shuts down with
        # `wait=True`, so a timed-out batch would block here until the very job
        # it gave up on finished — the timeout would report correctly and then
        # not return. Shutting down with `wait=False` lets the call return on
        # time. Threads cannot be interrupted, so a job already running still
        # runs to completion in the background; that is a Python limitation,
        # not a choice, and it is why `cancel_futures` (which only stops jobs
        # that never started) is passed alongside.
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=32)
        try:
            futures: dict[
                concurrent.futures.Future[tuple[int, Any]],
                tuple[int, str | Callable[..., Any]],
            ] = {}

            for idx, (job_or_fn, kwargs) in enumerate(jobs):
                future = executor.submit(_execute_single, idx, job_or_fn, kwargs)
                futures[future] = (idx, job_or_fn)

            started = time.monotonic()
            try:
                # The timeout belongs on `as_completed`, not on `future.result()`.
                # It used to sit on the latter, inside this loop — where it could
                # never fire, because `as_completed` only ever yields futures that
                # have *already* finished. `--timeout` would have been decorative.
                for future in concurrent.futures.as_completed(
                    futures, timeout=budget if budget > 0 else None
                ):
                    idx, job_or_fn = futures[future]
                    _collect(idx, job_or_fn, future)
            except concurrent.futures.TimeoutError:
                elapsed_ms = (time.monotonic() - started) * 1000
                for future, (idx, job_or_fn) in futures.items():
                    if idx in seen:
                        continue
                    # A future can finish between the timeout firing and this
                    # sweep. Its real result is better than a timeout we would
                    # be inventing, so it is collected rather than overwritten.
                    if future.done():
                        _collect(idx, job_or_fn, future)
                        continue
                    future.cancel()
                    results.append(
                        (
                            idx,
                            _JobResult(
                                status=RunStatus.TIMEOUT,
                                duration_ms=elapsed_ms,
                                return_value=None,
                                exception=TimeoutError(
                                    f"Job '{job_or_fn}' exceeded the "
                                    f"{budget:g}s parallel timeout"
                                ),
                                job_name=str(job_or_fn),
                            ),
                        )
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        results.sort(key=lambda x: x[0])
        return [r for _, r in results]

    def schema(self, job_or_fn: str | Callable[..., Any]) -> JobDescriptor:
        """Retrieve the JobDescriptor for a job by name or function reference."""
        job_name = self._resolve_job_name(job_or_fn)
        # Look up descriptor via the engine's app reference if available
        app = getattr(self._engine, "_app", None)
        if app is not None:
            return cast("JobDescriptor", app.job_registry.get_descriptor(job_name))
        # Fallback: construct a minimal descriptor from RegisteredJob
        registered_job = self._engine.get_job(job_name)
        from functualize._types.descriptors import JobDescriptor as _JobDescriptor

        return _JobDescriptor(
            name=registered_job.name,
            group=registered_job.group,
            function=registered_job.function,
            docstring=registered_job.function.__doc__,
            parameters=[],
            source=registered_job.module_path,
            metadata={},
            module_path=registered_job.module_path,
            source_file="",
            source_mtime=0.0,
            content_hash="",
        )

    def _resolve_job_name(self, job_or_fn: str | Callable[..., Any]) -> str:
        """Resolve job_or_fn using the engine's job registry.

        If job_or_fn is a string, returns it directly.
        If job_or_fn is a callable, looks it up in the engine's registered
        jobs by matching function references.
        """
        from functualize._engine.errors import JobNotFoundError

        if isinstance(job_or_fn, str):
            return job_or_fn

        if callable(job_or_fn):
            # Search the engine's registered jobs for this callable
            for name, entry in self._engine._registered_jobs.items():
                if entry.function is job_or_fn:
                    return name
                # Also check if the callable has __wrapped__ pointing to
                # the registered function (decorator chains)
                original = getattr(entry.function, "__wrapped__", None)
                if original is not None and original is job_or_fn:
                    return name
                # Check the reverse: caller's function may be wrapped
                caller_original = getattr(job_or_fn, "__wrapped__", None)
                if caller_original is not None and caller_original is entry.function:
                    return name

            # Metadata fallback: an unmaterialized LazyJobFunction entry can
            # never match the caller's imported function by identity, but its
            # module/qualname mirror the real function's. Only lazy entries
            # participate so live registrations keep strict identity.
            fn_module = getattr(job_or_fn, "__module__", None)
            fn_qualname = getattr(job_or_fn, "__qualname__", None)
            if fn_module and fn_qualname:
                metadata_matches = [
                    name
                    for name, entry in self._engine._registered_jobs.items()
                    if getattr(entry.function, "__functualize_lazy__", False)
                    and entry.function.__module__ == fn_module
                    and entry.function.__qualname__ == fn_qualname
                ]
                if len(metadata_matches) == 1:
                    return metadata_matches[0]
                if len(metadata_matches) > 1:
                    from functualize._types.errors import AmbiguousJobError

                    raise AmbiguousJobError(fn_qualname, sorted(metadata_matches))
            raise JobNotFoundError(job_or_fn)

        raise TypeError(
            f"job_or_fn must be a str or callable, got {type(job_or_fn).__name__}"
        )

    def _execute_with_timeout(
        self,
        execute_fn: Callable[[], Any],
        job_name: str,
        timeout: float,
    ) -> JobResult:
        """Execute a job with a timeout."""
        from functualize._types.descriptors import JobResult as _JobResult
        from functualize._types.enums import RunStatus

        start_time = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(execute_fn)
            try:
                return cast("JobResult", future.result(timeout=timeout))
            except concurrent.futures.TimeoutError:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                return _JobResult(
                    status=RunStatus.TIMEOUT,
                    duration_ms=elapsed_ms,
                    return_value=None,
                    exception=TimeoutError(
                        f"Job '{job_name}' exceeded timeout of {timeout}s"
                    ),
                    job_name=job_name,
                )
