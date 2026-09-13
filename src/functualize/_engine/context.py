"""Execution context — the input to the middleware chain.

ExecutionContext carries all information needed by middleware and the
execution engine to process a single job invocation: job identity,
resolved kwargs, timing, and references to capabilities and hooks.

Only imports from `_types/`, `_primitives/`, `_events/`, and stdlib.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._types.enums import RunStatus

if TYPE_CHECKING:
    from functualize._types.run_request import RunRequest


@dataclass
class ExecutionContext:
    """Context object passed through the execution middleware chain.

    Carries all state needed for a single job execution lifecycle:
    identity, resolved arguments, timing, and mutable metadata.

    Middleware can inspect and modify call_kwargs before execution,
    set metadata, or block execution by setting status to FAILURE.

    Attributes:
        job_name: Name of the job being executed.
        function: The callable job function.
        call_kwargs: Resolved keyword arguments for the job function.
        invoke_depth: Current recursion depth for nested invokes.
        cwd: Working directory for this execution.
        job_directory: Directory containing the job source file.
        start_time: Perf counter start time (set at context creation).
        status: Current execution status (middleware can set to block).
        metadata: Mutable metadata dict carried through execution.
        capabilities: Per-invocation capability instances (type → instance).
        config_class: Optional Pydantic model class for job config validation.
        parent_scope: Optional workflow scope propagated from parent invoke.
        request: The :class:`RunRequest` this execution was asked for, when it
            came through :meth:`JobExecutionEngine.run`. It carries the delivery
            inputs — ``prompt_gates``, ``output_format``, ``force`` — which the
            kernel used to read off the app object as ``app._prompt_gates`` and
            friends (run-request-entry/T12 removed those). A capability factory
            or the workflow prelude reads them from here, so a run's delivery
            behaviour travels *with the run* instead of sitting on a
            process-lifetime object that a second, concurrent run would share.
            ``None`` only for a context built outside ``run()``.
        run_id: The run-log id this execution was recorded under, when the run
            log could be written. **Carried on the context, not in a
            `ContextVar`**, because `rc.invoke_parallel` runs its items on a
            thread pool and a fresh thread starts with an empty context — the
            batch items are exactly the children whose parentage the log most
            needs. A child request reads it from here to set its own
            ``parent_run_id``. ``None`` when the store could not be written, or
            for a context built outside ``run()``.

            **Provenance, not the working copy — and the distinction is the
            rule that was missing.** This context also carries ``job_name``,
            ``invoke_depth``, ``cwd``, ``job_directory``, ``parent_scope`` and
            ``config_class`` as its own fields, several of which the request
            holds too, so an unqualified reading makes ``request`` look like a
            second source of truth. It is not: the scalars are what *this
            execution* is running with, and ``request`` is what the door
            **asked for**. They start equal and a nested run's context
            legitimately differs from the request that began it.

            The two must never diverge for a *top-level* run, and that is
            asserted rather than assumed —
            ``tests/engine/test_context_request_agreement.py``.

            Reading it is narrow by design: a capability factory receives a
            ``CapabilityContext`` whose only route here is ``ctx.context``
            (`_engine/capabilities/spec.py`), which is why the whole object is
            carried rather than the one field ``_make_stdout`` needs.

            Collapsing the duplication — deleting the restated scalars and
            taking a ``.request.`` hop at the ~15 read sites — is
            `engine-sealed-construction`'s business (T6–T11 extract
            ``WorkflowOrchestrator`` and ``DependencyRunner`` from exactly this
            code). Doing it here would be a churn that feature has to redo, and
            would make its diff harder to read. Reviewed and deliberately
            deferred (rre F9).
        injected: Names in ``call_kwargs`` the **executor** put there.
    """

    job_name: str
    function: Callable[..., Any]
    call_kwargs: dict[str, Any]
    invoke_depth: int = 0
    cwd: Path | None = None
    job_directory: Path | None = None
    start_time: float = field(default_factory=time.perf_counter)
    status: RunStatus = RunStatus.RUNNING
    metadata: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[type, Any] = field(default_factory=dict)
    config_class: type | None = None
    parent_scope: Any | None = None
    request: RunRequest | None = None
    run_id: str | None = None

    #: Parameter names in ``call_kwargs`` that the executor injected — DI
    #: capabilities, the resolved config model, resolved group options, and
    #: `FromJob` upstream values.
    #:
    #: The fingerprint key is a function of the arguments that are
    #: *semantically part of the call*, and this set is what makes that an
    #: exact subtraction rather than a type-sniffing guess: the executor knows
    #: every injection it made, so ``call_kwargs - injected`` is precisely the
    #: arguments a caller actually passed. Everything in here is either
    #: unreconstructable by a later reader (a live capability instance, whose
    #: ``repr`` carries a memory address) or already accounted for elsewhere in
    #: the key (the resolved config, passed separately).
    #:
    #: A parameter the *caller* supplied is never added — `_inject_from_job`
    #: and the DI loop both skip names already in ``call_kwargs`` — so a
    #: caller-passed value correctly stays in the key.
    injected: set[str] = field(default_factory=set)

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time in milliseconds since context creation."""
        return (time.perf_counter() - self.start_time) * 1000

    @property
    def is_blocked(self) -> bool:
        """Whether execution has been blocked by middleware."""
        return self.status == RunStatus.FAILURE

    def set_result_metadata(self, key: str, value: Any) -> None:
        """Store a key-value pair in the execution metadata dict.

        Enforces a maximum of 64 keys. Writes beyond the limit are
        silently discarded unless updating an existing key.

        Args:
            key: Metadata key.
            value: Metadata value.
        """
        if key in self.metadata or len(self.metadata) < 64:
            self.metadata[key] = value
