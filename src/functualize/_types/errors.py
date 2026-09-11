"""Shared error types for the functualize API surface.

These errors are raised across multiple layers and are part of the
public contract for job authors and platform developers.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._types.protocols import AgentCapability


class RecursionLimitError(Exception):
    """Raised when invoke_depth reaches max_invoke_depth.

    Attributes:
        depth: The current invoke depth when the limit was hit.
        max_depth: The configured maximum invoke depth.
        job_name: The name of the job that would have exceeded the limit.
    """

    def __init__(self, depth: int, max_depth: int, job_name: str) -> None:
        self.depth = depth
        self.max_depth = max_depth
        self.job_name = job_name
        super().__init__(
            f"Recursion limit reached: invoke_depth={depth} at "
            f"max_invoke_depth={max_depth} while invoking '{job_name}'"
        )


class WorkflowDepthExceededError(Exception):
    """A workflow nested deeper than `general.max_workflow_depth` allows.

    `durable-run-layer`/T12, inherited decision C9. A separate limit from
    `max_invoke_depth`, because they bound different things: that one counts
    *any* nested call, while this counts **workflows inside workflows** — each
    of which owns a scope, a set of step records, an epilogue slot and a lease.
    A run can legitimately invoke deeply without nesting a single workflow.

    Unbounded nesting is not a hypothetical: a workflow that names itself as a
    step type-checks, boots, and produces one scope per level until the disk
    or the recursion limit runs out — and every one of those scopes is a record
    somebody has to clean up.

    **No new exit code.** It is an ordinary refusal and reaches a caller through
    the outcome module's existing failure family, so there is one exit-code
    vocabulary rather than two.
    """

    def __init__(self, scope_id: str, depth: int, limit: int) -> None:
        super().__init__(
            f"Workflow nesting is {depth} deep at '{scope_id}', and the limit "
            f"is {limit}. Raise `general.max_workflow_depth` if this nesting "
            f"is intended, or flatten the graph."
        )
        self.scope_id = scope_id
        self.depth = depth
        self.limit = limit


class JobDependencyError(Exception):
    """Raised at boot when a job's ``Deps`` cannot be validated (§A.4):
    an unknown/unregistered dependency reference, or a dependency cycle.

    Attributes:
        message: Human-readable description of the problem.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class WorkflowDeclarationError(Exception):
    """Raised at boot when a ``@workflow`` graph cannot be validated (§A.7):
    a `Step` referencing an unknown job, or a cycle among nested workflows.

    Structural problems provable from the declaration alone (duplicate node
    names, edges to nowhere) raise at decoration time instead — this is for
    what only the live registry can settle.

    Attributes:
        message: Human-readable description of the problem.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class GroupOptionsConflictError(Exception):
    """Raised at discovery when two modules bind ``GroupOptions`` to one group.

    A group's flags must have exactly one declaration: the flags are inherited
    by every descendant job, so two competing declarations would make
    ``func deploy --env prod …`` mean different things depending on scan
    order. Mirrors the job name-conflict check.

    Attributes:
        group: The contested dotted group path.
        existing: Path of the module that already declared it.
        conflicting: Path of the module that tried to redeclare it.
    """

    def __init__(self, group: str, existing: str, conflicting: str) -> None:
        self.group = group
        self.existing = existing
        self.conflicting = conflicting
        super().__init__(
            f"Group {group!r} has more than one GroupOptions declaration: "
            f"{existing!r} and {conflicting!r}. A group's flags must be "
            "declared exactly once — merge them into a single class."
        )


class OrphanedPluginMetadataError(Exception):
    """Raised at boot when a job carries ``__functualize_ext_*`` metadata whose
    plugin is not loaded, and ``plugins.strict`` is enabled (§A.6).

    Attributes:
        orphans: List of ``(job_name, namespace)`` pairs with no owning plugin.
    """

    def __init__(self, orphans: list[tuple[str, str]]) -> None:
        self.orphans = orphans
        detail = ", ".join(f"{job}:{ns}" for job, ns in orphans)
        super().__init__(
            "Orphaned plugin metadata (no matching loaded plugin) under "
            f"plugins.strict: {detail}"
        )


class GateResolutionError(Exception):
    """Raised when all gate strategies fail to resolve input.

    Attributes:
        gate_name: The name of the gate that failed resolution.
        strategies_attempted: The number of strategies that were tried.
        last_error: Description of the last error encountered.
    """

    def __init__(
        self, gate_name: str, strategies_attempted: int, last_error: str
    ) -> None:
        self.gate_name = gate_name
        self.strategies_attempted = strategies_attempted
        self.last_error = last_error
        super().__init__(
            f"Gate '{gate_name}': all {strategies_attempted} strategies failed. "
            f"Last error: {last_error}"
        )


class JobNotFoundError(Exception):
    """Raised when a callable is not found in the job registry.

    Attributes:
        fn_or_name: The function reference or name string that was not found.
    """

    def __init__(self, fn_or_name: str | Callable[..., Any]) -> None:
        self.fn_or_name = fn_or_name
        if callable(fn_or_name) and not isinstance(fn_or_name, str):
            name = getattr(fn_or_name, "__qualname__", None) or getattr(
                fn_or_name, "__name__", repr(fn_or_name)
            )
            msg = f"Callable '{name}' is not registered in the job registry"
        else:
            msg = f"Job '{fn_or_name}' is not registered"
        super().__init__(msg)


class JobMaterializationError(Exception):
    """Raised when a lazily-registered job's module cannot be imported.

    Raised at first use (invocation or CLI dispatch) of a job whose
    registration deferred the module import. Chains the original
    ImportError/AttributeError as __cause__.

    Attributes:
        job_name: The registered job name being materialized.
        module_path: Dotted module path that failed to import/resolve.
        source_file: Source file recorded in the descriptor, if any.
    """

    def __init__(
        self, job_name: str, module_path: str, source_file: str | None = None
    ) -> None:
        self.job_name = job_name
        self.module_path = module_path
        self.source_file = source_file
        location = f" ({source_file})" if source_file else ""
        super().__init__(
            f"Job '{job_name}': failed to import module '{module_path}'{location}"
        )


class AmbiguousJobError(Exception):
    """Raised when a bare job name matches multiple registered jobs.

    Attributes:
        name: The ambiguous bare name.
        candidates: List of qualified names that match.
    """

    def __init__(self, name: str, candidates: list[str]) -> None:
        self.name = name
        self.candidates = candidates
        super().__init__(
            f"Ambiguous job name '{name}'. "
            f"Candidates: {candidates}. Use the qualified form."
        )


class ScopeStoreUnreadableError(Exception):
    """Raised when the workflow scope store exists but cannot be honoured.

    A version mismatch or corrupt content. **Never** degrades to "no scopes":
    the scope store is the only record of an in-flight run, including a human's
    recorded gate answers, so an unreadable one is a refusal, not an empty list.
    That is a deliberate divergence from the derived state store beside it,
    whose discard-on-mismatch rule is correct for a cache and wrong here.

    The file is **left where it is**. Refusing has to be a repeatable state: if
    the read moved the file aside, the next run would find nothing, read it as
    "no scopes", and start the workflow over silently — the exact failure this
    error exists to prevent. It moves only when a human asks, at
    ``func builtin data clear --scopes``, which the message names.

    Attributes:
        where: A human-readable account of the document that could not be read
            — a path under the filesystem substrate, a table row elsewhere. A
            description rather than a `Path`, because the store no longer knows
            it is talking to a filesystem and a substrate over a database has no
            path to name.
        scope_count: How many scopes were visible in it, or None if it could
            not be parsed at all.
        found_version: The format version on disk, when that is the cause.
        expected_version: The format version this build understands.

    ``scope_count`` is a **count, never content**. Scope records hold gate
    payloads and step return values, which may be secrets — the same reason run
    history stores ``args_hash`` and never argument values.
    """

    def __init__(
        self,
        where: str,
        *,
        scope_count: int | None = None,
        found_version: int | None = None,
        expected_version: int,
    ) -> None:
        self.where = where
        self.scope_count = scope_count
        self.found_version = found_version
        self.expected_version = expected_version
        super().__init__(self._message())

    def _message(self) -> str:
        if self.found_version is not None:
            cause = (
                f"found version {self.found_version}, expected {self.expected_version}"
            )
        else:
            cause = "its contents could not be parsed"
        if self.scope_count is None:
            holds = "It may hold workflow scopes, including recorded gate input."
        else:
            plural = "" if self.scope_count == 1 else "s"
            holds = (
                f"It holds {self.scope_count} workflow scope{plural}, "
                "including any recorded gate input."
            )
        return (
            f"{self.where} cannot be read ({cause}).\n"
            f"       {holds}\n"
            "\n"
            "  The file has been left where it is. To move it aside and "
            "start fresh:\n"
            "      func builtin data clear --scopes"
        )


class TerminalUnavailable(Exception):  # noqa: N818 — reads as a state, not an error
    """Raised when a job needs an interactive terminal but none is available.

    A job that declares ``tty: TTY`` (a hard requirement) owns the terminal for
    the duration of ``tty.run(app)``. In contexts that cannot grant terminal
    ownership — MCP, CI, piped/redirected I/O, background execution — the job is
    refused with this error (pre-flight where the router can see the
    ``requires_tty`` marker; at ``tty.run`` time otherwise), naming the fix.

    Attributes:
        job_name: The job that required a terminal, if known.
    """

    def __init__(
        self, message: str | None = None, *, job_name: str | None = None
    ) -> None:
        self.job_name = job_name
        super().__init__(
            message
            or "This job needs an interactive terminal (it declares `tty: TTY`)."
        )


class ScopeCancelledError(Exception):
    """Raised when a walk is asked to advance a scope that was cancelled.

    ``cancel_workflow``'s own description has always said *"Cancelled scopes
    are not resumable"* and nothing enforced it: the string ``cancelled``
    appeared zero times across the executor, the walker and the runner, so
    invoking the workflow job against a cancelled scope walked it to completion
    and overwrote the status. The promise was documentation, not a rule.

    Enforced in ``WorkflowRunner.prelude`` rather than at each calling surface,
    because a check a caller can skip by not calling it is not a rule either —
    the same reasoning that puts the gate-tool policy at the MCP execute funnel.

    Terminal means terminal: there is no ``--force`` and no un-cancel. The
    recovery is a fresh run, which the message names.

    Attributes:
        scope_id: The cancelled scope.
        workflow: The workflow it belongs to, when known — a caller starting
            fresh needs the job name, not just the id it cannot reuse.
    """

    def __init__(self, scope_id: str, *, workflow: str | None = None) -> None:
        self.scope_id = scope_id
        self.workflow = workflow
        start = (
            f"Start a fresh run with: {workflow}" if workflow else "Start a fresh run"
        )
        super().__init__(
            f"Workflow scope '{scope_id}' was cancelled and cannot be resumed. {start}."
        )


class AgentExecutorUnavailableError(Exception):
    """Raised at validation when an agent step has no executor to run it.

    A refusal, not a degradation. The walk never starts, and the step is
    **not** handed to a human instead: swapping who answers changes the
    program, and a step declared as an agent's work was declared that way for a
    reason. It is also not substituted with another executor — an executor the
    step did not name cannot honour what the step declared.

    Raised before the walk rather than at the node, so that nothing has
    happened yet when it fires.

    Attributes:
        step_name: The agent step that could not be serviced.
        executor: The executor the step named, or None when it named none and
            no executor is registered at all.
        registered: The executor names that *are* registered, sorted.
        hint: How to make it available, as the install clause from
            ``_engine.agent_providers.EXECUTOR_PROVIDERS``. Empty for a core
            name — a core executor that is missing is a registry built by hand,
            not a package waiting to be installed.
    """

    def __init__(
        self,
        step_name: str,
        executor: str | None = None,
        *,
        registered: Sequence[str] = (),
        hint: str = "",
    ) -> None:
        self.step_name = step_name
        self.executor = executor
        self.registered = tuple(registered)
        self.hint = hint
        super().__init__(self._message())

    def _message(self) -> str:
        # Three situations, not two. Naming an executor that is not registered
        # is one; naming none is the other two, and they need different
        # sentences. One sentence covered both and produced "has no executor
        # registered for it (registered: ai, cli-prompt)" — a contradiction in
        # eleven words, on the case a user is most likely to hit (asp M-1).
        if self.executor is not None:
            wanted = f"names executor {self.executor!r}, which is not registered"
            known = (
                f" (registered: {', '.join(self.registered)})"
                if self.registered
                else " (no executor is registered at all)"
            )
        elif self.registered:
            # `resolve` returns the sole executor when exactly one is
            # registered, so reaching here with a non-empty list means two or
            # more — and picking between them is what nothing may do.
            wanted = (
                f"names no executor and {len(self.registered)} are registered, "
                "so which one should service it cannot be identified"
            )
            known = f" (registered: {', '.join(self.registered)})"
        else:
            wanted = "has no executor registered for it"
            known = " (no executor is registered at all)"
        remedy = f" {self.hint.capitalize()}." if self.hint else ""
        return (
            f"Agent step {self.step_name!r} {wanted}{known}.{remedy} "
            "The step is refused — it is never answered by prompting a human "
            "instead."
        )


class AgentCapabilityRefusedError(Exception):
    """Raised at validation when an executor cannot honour what a step requires.

    The engine refuses rather than running with the constraint unenforced:
    running anyway is the silent degradation an agent step exists to avoid —
    the workflow would appear to have restricted something it left wide open.

    Raised before the walk starts, so no step has run and no step record
    exists to reconcile.

    Attributes:
        step_name: The agent step whose requirement cannot be honoured.
        executor: The registered executor that was chosen for it.
        capability: The required capability that executor does not declare.
        declared: The capabilities the executor does declare, sorted.
    """

    def __init__(
        self,
        step_name: str,
        *,
        executor: str,
        capability: AgentCapability,
        declared: Sequence[AgentCapability] = (),
    ) -> None:
        self.step_name = step_name
        self.executor = executor
        self.capability = capability
        self.declared = tuple(declared)
        super().__init__(self._message())

    def _message(self) -> str:
        declared = (
            ", ".join(sorted(str(cap) for cap in self.declared)) or "no capabilities"
        )
        return (
            f"Agent step {self.step_name!r} requires "
            f"{str(self.capability)!r}, which executor {self.executor!r} does "
            f"not declare (it declares: {declared}). The step is refused — "
            "running it would leave the constraint unenforced."
        )


class SubstrateUnreadableError(Exception):
    """A stored document exists but its bytes could not be turned into a mapping.

    **Raised, never swallowed.** Whether that is fatal is the *store's*
    decision, not storage's: ``fresh_format`` degrades to an empty envelope
    because its content is recomputable, and ``scope_format`` refuses because a
    scope is the only trace of an in-flight run — see
    :class:`ScopeStoreUnreadableError`, which is what a store raises once it has
    decided. A substrate that chose between those would be taking a decision
    about *meaning* it has no standing to take.

    The document is **left where it is**, for the same reason
    :class:`ScopeStoreUnreadableError` leaves its file: a refusal has to be a
    repeatable state.

    Attributes:
        key: The document name that could not be read. A key, not a path — a
            substrate over SQLite or S3 has no path to report.
    """

    def __init__(self, key: str, detail: str) -> None:
        self.key = key
        super().__init__(f"Cannot read {key!r}: {detail}")
